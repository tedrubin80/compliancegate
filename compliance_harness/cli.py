from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import click

from compliance_harness import __version__
from compliance_harness.config import load_config, severity_at_or_above
from compliance_harness.db import ComplianceDB
from compliance_harness.git_hooks import init_project, install_hooks
from compliance_harness.markdown_export import write_daily_report, write_session_report
from compliance_harness.reviewer import ComplianceReviewer
from compliance_harness.session import SessionManager


def _skip_check() -> bool:
    return os.environ.get("CRH_SKIP", "").strip() in ("1", "true", "yes")


def _print_result(result, label: str) -> None:
    click.echo(f"\n{'=' * 60}")
    click.echo(f"  {label}")
    click.echo(f"{'=' * 60}")
    click.echo(f"Verdict:   {result.verdict}")
    click.echo(f"Decision:  {'ALLOW' if result.allowed else 'BLOCK'}")
    click.echo(f"Reasoning: {result.reasoning}")
    click.echo(f"Changes:   {result.diff_summary}")

    if result.findings:
        click.echo(f"\nFindings ({len(result.findings)}):")
        for f in result.findings:
            click.echo(f"  [{f.severity.upper()}] {f.title}")
            if f.file_path:
                click.echo(f"    File: {f.file_path} {f.line_hint}")
            click.echo(f"    {f.description[:300]}")
            if f.recommendation:
                click.echo(f"    → {f.recommendation}")
    click.echo(f"\nSession: {result.session_id[:8]}... | Review: {result.review_id[:8]}...")
    click.echo(f"SQLite:  decisions + findings persisted")
    click.echo(f"{'=' * 60}\n")


@click.group()
@click.version_option(__version__, prog_name="crh")
def main():
    """Compliance Review Harness — governance gap layer for AI-assisted development."""
    pass


@main.command("init")
@click.option("--repo", type=click.Path(exists=True), default=".", help="Target git repo root")
@click.option("--config", "config_path", type=click.Path(exists=True), default=None)
def cmd_init(repo: str, config_path: str | None):
    """Initialize harness, SQLite storage, and git hooks in a repo."""
    repo_root = Path(repo).resolve()
    harness_root = Path(__file__).resolve().parent.parent
    init_project(repo_root, harness_root)


@main.command("install-hooks")
@click.option("--repo", type=click.Path(exists=True), default=".")
def cmd_install_hooks(repo: str):
    """Install pre-commit and pre-push hooks only."""
    repo_root = Path(repo).resolve()
    harness_root = Path(__file__).resolve().parent.parent
    install_hooks(repo_root, harness_root)


@main.command("pre-commit")
@click.option("--config", "config_path", type=click.Path(exists=True), default=None)
def cmd_pre_commit(config_path: str | None):
    """Gate: run compliance review before commit."""
    if _skip_check():
        click.echo("[crh] CRH_SKIP set — bypassing pre-commit review (decision logged if possible)")
        try:
            cfg = load_config(Path(config_path) if config_path else None)
            db = ComplianceDB(cfg.sqlite_path)
            sm = SessionManager(cfg, db)
            sid = sm.ensure_session()
            db.record_decision(sid, "pre-commit", "skip", reasoning="CRH_SKIP override", actor="developer")
        except Exception:
            pass
        sys.exit(0)

    cfg = load_config(Path(config_path) if config_path else None)
    reviewer = ComplianceReviewer(cfg)
    result = reviewer.review_changes(
        trigger="pre-commit",
        block_threshold=cfg.compliance.block_commit_on,
    )
    _print_result(result, "PRE-COMMIT COMPLIANCE REVIEW")
    sys.exit(0 if result.allowed else 1)


@main.command("pre-push")
@click.option("--config", "config_path", type=click.Path(exists=True), default=None)
def cmd_pre_push(config_path: str | None):
    """Gate: loopback review of all session changes before push."""
    if _skip_check():
        click.echo("[crh] CRH_SKIP set — bypassing pre-push review")
        sys.exit(0)

    cfg = load_config(Path(config_path) if config_path else None)
    reviewer = ComplianceReviewer(cfg)

    # Full diff against remote
    result = reviewer.loopback_review()
    # Also check against push threshold
    blocked = any(
        severity_at_or_above(f.severity, cfg.compliance.block_push_on)
        for f in result.findings
    )
    result.allowed = not blocked

    _print_result(result, "PRE-PUSH LOOPBACK COMPLIANCE REVIEW")
    sys.exit(0 if result.allowed else 1)


@main.command("review")
@click.option("--config", "config_path", type=click.Path(exists=True), default=None)
@click.option("--trigger", default="manual", help="Review trigger label")
def cmd_review(config_path: str | None, trigger: str):
    """Run an on-demand compliance review of current changes."""
    cfg = load_config(Path(config_path) if config_path else None)
    reviewer = ComplianceReviewer(cfg)
    result = reviewer.review_changes(trigger=trigger)
    _print_result(result, f"COMPLIANCE REVIEW ({trigger})")
    sys.exit(0 if result.allowed else 1)


@main.command("watch")
@click.option("--config", "config_path", type=click.Path(exists=True), default=None)
def cmd_watch(config_path: str | None):
    """Live coding alert layer — watches file changes and flags compliance issues."""
    from compliance_harness.watcher import run_watcher

    run_watcher(Path(config_path) if config_path else None)


@main.command("loopback")
@click.option("--config", "config_path", type=click.Path(exists=True), default=None)
def cmd_loopback(config_path: str | None):
    """Re-review all changes in the current session with accumulated context."""
    cfg = load_config(Path(config_path) if config_path else None)
    reviewer = ComplianceReviewer(cfg)
    result = reviewer.loopback_review()
    _print_result(result, "LOOPBACK SESSION REVIEW")


@main.command("export-md")
@click.option("--config", "config_path", type=click.Path(exists=True), default=None)
@click.option("--session-id", default=None, help="Export specific session markdown")
@click.option("--daily", is_flag=True, help="Export today's daily rollup")
def cmd_export_md(config_path: str | None, session_id: str | None, daily: bool):
    """Generate markdown audit reports from SQLite retention."""
    cfg = load_config(Path(config_path) if config_path else None)
    db = ComplianceDB(cfg.sqlite_path)

    if session_id:
        path = write_session_report(cfg, session_id)
        click.echo(f"Session report: {path}")
    elif daily:
        path = write_daily_report(cfg)
        click.echo(f"Daily report: {path}")
    else:
        active = db.get_active_session(cfg.project_name)
        if active:
            path = write_session_report(cfg, active)
            click.echo(f"Active session report: {path}")
        path = write_daily_report(cfg)
        click.echo(f"Daily report: {path}")


@main.command("sync-db")
@click.option("--config", "config_path", type=click.Path(exists=True), default=None)
@click.option("--session-id", default=None, help="Sync one session; default syncs all")
def cmd_sync_db(config_path: str | None, session_id: str | None):
    """Push SQLite retention to configured Postgres/MySQL backends."""
    cfg = load_config(Path(config_path) if config_path else None)
    db = ComplianceDB(cfg.sqlite_path)

    from compliance_harness.remote_db import sync_all, sync_session

    try:
        if session_id:
            counts = sync_session(cfg, db, session_id)
        else:
            counts = sync_all(cfg, db)
    except ImportError as exc:
        click.echo(f"Missing driver: {exc}. Install with: pip install 'compliance-review-harness[postgres]' or '[mysql]'")
        sys.exit(1)
    except RuntimeError as exc:
        click.echo(str(exc))
        sys.exit(1)

    if not counts:
        click.echo("No remote backends enabled. Set retention.postgres or retention.mysql in config.yaml.")
        sys.exit(0)

    for backend, n in counts.items():
        click.echo(f"{backend}: synced {n} rows")


@main.command("export-json")
@click.option("--config", "config_path", type=click.Path(exists=True), default=None)
@click.option("--output", "-o", default=".compliance/export.json")
def cmd_export_json(config_path: str | None, output: str):
    """Export all SQLite retention data to JSON."""
    cfg = load_config(Path(config_path) if config_path else None)
    db = ComplianceDB(cfg.sqlite_path)
    out = cfg.repo_root / output
    db.export_json(out, cfg.project_name)
    click.echo(f"Exported to {out}")


@main.command("status")
@click.option("--config", "config_path", type=click.Path(exists=True), default=None)
def cmd_status(config_path: str | None):
    """Show current session, unresolved findings, and storage paths."""
    cfg = load_config(Path(config_path) if config_path else None)
    db = ComplianceDB(cfg.sqlite_path)
    active = db.get_active_session(cfg.project_name)
    unresolved = db.get_unresolved_findings(cfg.project_name, "medium")

    click.echo(f"Project:     {cfg.project_name}")
    click.echo(f"Repo:        {cfg.repo_root}")
    click.echo(f"SQLite:      {cfg.sqlite_path}")
    click.echo(f"Reports:     {cfg.markdown_dir}")
    click.echo(f"LLM:         {cfg.llm.provider} / {cfg.llm.model}")
    click.echo(f"Session:     {active or 'none'}")
    click.echo(f"Unresolved:  {len(unresolved)} findings (medium+)")


@main.command("end-session")
@click.option("--config", "config_path", type=click.Path(exists=True), default=None)
@click.option("--summary", default="", help="Optional session summary")
def cmd_end_session(config_path: str | None, summary: str):
    """Close the active compliance session."""
    cfg = load_config(Path(config_path) if config_path else None)
    db = ComplianceDB(cfg.sqlite_path)
    sm = SessionManager(cfg, db)
    sid = sm.ensure_session()
    write_session_report(cfg, sid)
    sm.end_session(summary)
    write_daily_report(cfg)
    click.echo(f"Session {sid[:8]}... ended. Reports written.")


if __name__ == "__main__":
    main()
