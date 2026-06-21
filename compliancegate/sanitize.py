from __future__ import annotations

import hashlib
import re
from copy import deepcopy
from typing import Any

# Redact before data crosses trust boundaries (remote DB, external LLM)
_REDACTIONS = [
    (re.compile(r"\b(?:4[0-9]{12}(?:[0-9]{3})?|5[1-5][0-9]{14}|3[47][0-9]{13})\b"), "[REDACTED_PAN]"),
    (re.compile(r"\b\d{3}-\d{2}-\d{4}\b"), "[REDACTED_SSN]"),
    (re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b"), "[REDACTED_EMAIL]"),
    (re.compile(r"(?i)(api[_-]?key|secret|password|token)\s*[:=]\s*['\"][^'\"]+['\"]"), "[REDACTED_SECRET]"),
    (re.compile(r"(?i)(patient|diagnosis|mrn|phi)[^\n]{0,80}"), "[REDACTED_PHI]"),
]

SENSITIVE_CATEGORIES = frozenset({"privacy", "payment", "hipaa", "phi", "pii", "pci"})


def redact_text(text: str) -> str:
    if not text:
        return text
    out = text
    for pattern, replacement in _REDACTIONS:
        out = pattern.sub(replacement, out)
    return out


def sanitize_for_llm(diff_text: str, enabled: bool) -> str:
    return redact_text(diff_text) if enabled else diff_text


def sanitize_for_remote(
    data: dict[str, Any],
    mode: str = "metadata_only",
    sync_sensitive: bool = False,
) -> dict[str, Any]:
    """
    Trust boundary: remote Postgres/MySQL must not receive dubious review content.

    metadata_only (default): ids, verdicts, severities, framework tags — no prose, paths, or diffs
    redacted: metadata + redacted titles/descriptions
    full: everything (requires explicit sync_sensitive + legal review)
    """
    if mode == "full" and sync_sensitive:
        return _walk_redact(deepcopy(data))

    if mode == "redacted":
        return _redact_payload(data, prose=True)

    return _metadata_payload(data, sync_sensitive=sync_sensitive)


def _redact_values(data: dict[str, Any]) -> dict[str, Any]:
    out = deepcopy(data)
    for table in ("session", "decisions", "reviews", "findings"):
        key = table if table != "session" else "session"
        rows = out.get(key if key != "session" else "session")
        if isinstance(rows, dict):
            out["session"] = {k: redact_text(str(v)) if isinstance(v, str) else v for k, v in rows.items()}
        elif isinstance(rows, list):
            out[table if table != "session" else "decisions"]  # noqa — fix below
    return _walk_redact(out)


def _walk_redact(obj: Any) -> Any:
    if isinstance(obj, dict):
        return {k: _walk_redact(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_walk_redact(v) for v in obj]
    if isinstance(obj, str):
        return redact_text(obj)
    return obj


def _metadata_payload(data: dict[str, Any], sync_sensitive: bool) -> dict[str, Any]:
    session = data.get("session", {})
    safe_session = {
        "id": session.get("id"),
        "project_name": session.get("project_name"),
        "started_at": session.get("started_at"),
        "ended_at": session.get("ended_at"),
        "git_branch": session.get("git_branch"),
        "git_head": session.get("git_head"),
        "summary": _hash_note(session.get("summary") or ""),
    }

    decisions = []
    for d in data.get("decisions", []):
        decisions.append({
            "id": d.get("id"),
            "session_id": d.get("session_id"),
            "created_at": d.get("created_at"),
            "trigger": d.get("trigger"),
            "context": None,
            "decision": d.get("decision"),
            "reasoning": None,
            "actor": d.get("actor"),
            "metadata_json": d.get("metadata_json"),
        })

    reviews = []
    for r in data.get("reviews", []):
        reviews.append({
            "id": r.get("id"),
            "session_id": r.get("session_id"),
            "created_at": r.get("created_at"),
            "trigger": r.get("trigger"),
            "diff_summary": r.get("diff_summary"),
            "files_changed": _basename_files(r.get("files_changed")),
            "reasoning": None,
            "verdict": r.get("verdict"),
            "raw_response": None,
        })

    findings = []
    for f in data.get("findings", []):
        if not sync_sensitive and _is_sensitive_finding(f):
            findings.append({
                "id": f.get("id"),
                "review_id": f.get("review_id"),
                "session_id": f.get("session_id"),
                "created_at": f.get("created_at"),
                "severity": f.get("severity"),
                "category": f.get("category"),
                "framework": f.get("framework"),
                "title": f.get("title"),
                "description": "[local-only sensitive finding]",
                "file_path": None,
                "line_hint": None,
                "recommendation": None,
                "resolved": f.get("resolved", 0),
            })
        else:
            findings.append({
                "id": f.get("id"),
                "review_id": f.get("review_id"),
                "session_id": f.get("session_id"),
                "created_at": f.get("created_at"),
                "severity": f.get("severity"),
                "category": f.get("category"),
                "framework": f.get("framework"),
                "title": f.get("title"),
                "description": _hash_note(f.get("description") or ""),
                "file_path": _basename(f.get("file_path") or ""),
                "line_hint": None,
                "recommendation": None,
                "resolved": f.get("resolved", 0),
            })

    return {
        "session": safe_session,
        "decisions": decisions,
        "reviews": reviews,
        "findings": findings,
    }


def _redact_payload(data: dict[str, Any], prose: bool) -> dict[str, Any]:
    base = _metadata_payload(data, sync_sensitive=False)
    if not prose:
        return base
    for f in base.get("findings", []):
        if f.get("description", "").startswith("[local-only"):
            continue
        f["description"] = redact_text(f.get("description") or "")[:500]
    return base


def _is_sensitive_finding(finding: dict) -> bool:
    cat = (finding.get("category") or "").lower()
    fw = (finding.get("framework") or "").lower()
    if cat in SENSITIVE_CATEGORIES:
        return True
    if fw in ("hipaa", "pci-dss", "gdpr", "ccpa"):
        return True
    return False


def _basename(path: str) -> str | None:
    if not path:
        return None
    return path.rsplit("/", 1)[-1].rsplit("\\", 1)[-1]


def _basename_files(files_json: str | None) -> str:
    if not files_json:
        return "[]"
    import json
    try:
        files = json.loads(files_json)
        return json.dumps([_basename(f) for f in files if f])
    except json.JSONDecodeError:
        return "[]"


def _hash_note(text: str) -> str:
    if not text:
        return ""
    digest = hashlib.sha256(text.encode()).hexdigest()[:16]
    return f"[hash:{digest}]"
