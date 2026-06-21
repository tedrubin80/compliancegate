from __future__ import annotations

import subprocess
from dataclasses import dataclass
from pathlib import Path

from compliance_harness.config import HarnessConfig, severity_at_or_above
from compliance_harness.db import ComplianceDB, Finding
from compliance_harness.llm import LLMClient, heuristic_scan
from compliance_harness.markdown_export import write_daily_report, write_session_report
from compliance_harness.session import SessionManager


@dataclass
class ReviewResult:
    allowed: bool
    verdict: str
    reasoning: str
    findings: list[Finding]
    review_id: str
    session_id: str
    diff_summary: str
    files_changed: list[str]


class ComplianceReviewer:
    def __init__(self, config: HarnessConfig):
        self.config = config
        self.db = ComplianceDB(config.sqlite_path)
        self.llm = LLMClient(config)
        self.sessions = SessionManager(config, self.db)

    def review_changes(
        self,
        trigger: str,
        diff_text: str | None = None,
        files_changed: list[str] | None = None,
        block_threshold: str | None = None,
    ) -> ReviewResult:
        session_id = self.sessions.ensure_session()
        session_data = self.db.get_session_data(session_id)
        prior_decisions = session_data.get("decisions", [])

        if diff_text is None:
            diff_text, files_changed = get_git_diff(self.config.repo_root)

        files_changed = files_changed or []
        diff_summary = _summarize_diff(diff_text, files_changed)

        # Layer 1: fast heuristic scan
        heuristic_findings = [Finding(**f) for f in heuristic_scan(diff_text)]

        # Layer 2: LLM reasoning review
        llm_result = self.llm.review(
            diff_text=diff_text,
            frameworks=self.config.compliance.frameworks,
            custom_rules=self.config.compliance.custom_rules,
            trigger=trigger,
            prior_decisions=prior_decisions,
        )

        llm_findings = [
            Finding(
                severity=f.get("severity", "medium"),
                category=f.get("category", "general"),
                framework=f.get("framework", ""),
                title=f.get("title", "Untitled finding"),
                description=f.get("description", ""),
                file_path=f.get("file_path", ""),
                line_hint=f.get("line_hint", ""),
                recommendation=f.get("recommendation", ""),
            )
            for f in llm_result.get("findings", [])
        ]

        all_findings = _dedupe_findings(heuristic_findings + llm_findings)
        verdict = llm_result.get("verdict", "warn")
        reasoning = llm_result.get("reasoning", "")

        if any(severity_at_or_above(f.severity, "critical") for f in all_findings):
            verdict = "fail"
        elif any(severity_at_or_above(f.severity, "high") for f in all_findings) and verdict == "pass":
            verdict = "warn"

        review_id = self.db.record_review(
            session_id=session_id,
            trigger=trigger,
            verdict=verdict,
            reasoning=reasoning,
            diff_summary=diff_summary,
            files_changed=files_changed,
            raw_response=str(llm_result),
        )
        self.db.record_findings(review_id, session_id, all_findings)

        threshold = block_threshold or self.config.compliance.block_commit_on
        blocked = any(severity_at_or_above(f.severity, threshold) for f in all_findings)

        decision = "allow" if not blocked else "block"
        self.db.record_decision(
            session_id=session_id,
            trigger=trigger,
            decision=decision,
            reasoning=reasoning,
            context=diff_summary,
            metadata={"verdict": verdict, "finding_count": len(all_findings)},
        )

        try:
            from compliance_harness.remote_db import maybe_sync_retention
            maybe_sync_retention(self.config, self.db, session_id)
        except Exception as exc:
            import sys
            print(f"[crh] retention sync warning: {exc}", file=sys.stderr)

        if self.config.reporting.session_markdown:
            write_session_report(self.config, session_id)

        if self.config.reporting.daily_markdown:
            write_daily_report(self.config)

        return ReviewResult(
            allowed=not blocked,
            verdict=verdict,
            reasoning=reasoning,
            findings=all_findings,
            review_id=review_id,
            session_id=session_id,
            diff_summary=diff_summary,
            files_changed=files_changed,
        )

    def loopback_review(self) -> ReviewResult:
        """Re-review all session changes with accumulated decision context."""
        session_id = self.sessions.ensure_session()
        session_data = self.db.get_session_data(session_id)

        combined = []
        for review in session_data.get("reviews", []):
            combined.append(review.get("diff_summary", ""))

        diff_text = "\n\n".join(combined) or get_git_diff(self.config.repo_root)[0]
        return self.review_changes(trigger="loopback", diff_text=diff_text)


def get_git_diff(repo_root: Path) -> tuple[str, list[str]]:
    try:
        diff = subprocess.run(
            ["git", "diff", "--cached"],
            cwd=repo_root,
            capture_output=True,
            text=True,
            check=False,
        ).stdout
        if not diff.strip():
            diff = subprocess.run(
                ["git", "diff", "HEAD"],
                cwd=repo_root,
                capture_output=True,
                text=True,
                check=False,
            ).stdout

        stat = subprocess.run(
            ["git", "diff", "--cached", "--name-only"],
            cwd=repo_root,
            capture_output=True,
            text=True,
            check=False,
        ).stdout
        files = [f for f in stat.strip().split("\n") if f]
        if not files:
            stat = subprocess.run(
                ["git", "diff", "HEAD", "--name-only"],
                cwd=repo_root,
                capture_output=True,
                text=True,
                check=False,
            ).stdout
            files = [f for f in stat.strip().split("\n") if f]

        return diff, files
    except FileNotFoundError:
        return "", []


def _summarize_diff(diff_text: str, files: list[str]) -> str:
    lines = diff_text.count("\n")
    adds = diff_text.count("\n+")
    dels = diff_text.count("\n-")
    file_list = ", ".join(files[:10])
    if len(files) > 10:
        file_list += f" (+{len(files) - 10} more)"
    return f"{len(files)} files, ~{lines} diff lines (+{adds}/-{dels}): {file_list}"


def _dedupe_findings(findings: list[Finding]) -> list[Finding]:
    seen: set[str] = set()
    out: list[Finding] = []
    for f in findings:
        key = f"{f.severity}:{f.title}:{f.file_path}"
        if key not in seen:
            seen.add(key)
            out.append(f)
    return out
