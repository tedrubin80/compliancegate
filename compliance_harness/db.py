from __future__ import annotations

import json
import sqlite3
import uuid
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator


def _utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


SCHEMA = """
CREATE TABLE IF NOT EXISTS sessions (
    id TEXT PRIMARY KEY,
    project_name TEXT NOT NULL,
    started_at TEXT NOT NULL,
    ended_at TEXT,
    git_branch TEXT,
    git_head TEXT,
    summary TEXT
);

CREATE TABLE IF NOT EXISTS decisions (
    id TEXT PRIMARY KEY,
    session_id TEXT NOT NULL,
    created_at TEXT NOT NULL,
    trigger TEXT NOT NULL,
    context TEXT,
    decision TEXT NOT NULL,
    reasoning TEXT,
    actor TEXT DEFAULT 'harness',
    metadata_json TEXT,
    FOREIGN KEY (session_id) REFERENCES sessions(id)
);

CREATE TABLE IF NOT EXISTS reviews (
    id TEXT PRIMARY KEY,
    session_id TEXT NOT NULL,
    created_at TEXT NOT NULL,
    trigger TEXT NOT NULL,
    diff_summary TEXT,
    files_changed TEXT,
    reasoning TEXT,
    verdict TEXT NOT NULL,
    raw_response TEXT,
    FOREIGN KEY (session_id) REFERENCES sessions(id)
);

CREATE TABLE IF NOT EXISTS compliance_findings (
    id TEXT PRIMARY KEY,
    review_id TEXT NOT NULL,
    session_id TEXT NOT NULL,
    created_at TEXT NOT NULL,
    severity TEXT NOT NULL,
    category TEXT,
    framework TEXT,
    title TEXT NOT NULL,
    description TEXT NOT NULL,
    file_path TEXT,
    line_hint TEXT,
    recommendation TEXT,
    resolved INTEGER DEFAULT 0,
    FOREIGN KEY (review_id) REFERENCES reviews(id),
    FOREIGN KEY (session_id) REFERENCES sessions(id)
);

CREATE INDEX IF NOT EXISTS idx_decisions_session ON decisions(session_id);
CREATE INDEX IF NOT EXISTS idx_reviews_session ON reviews(session_id);
CREATE INDEX IF NOT EXISTS idx_findings_review ON compliance_findings(review_id);
CREATE INDEX IF NOT EXISTS idx_findings_severity ON compliance_findings(severity);
CREATE INDEX IF NOT EXISTS idx_findings_session ON compliance_findings(session_id);
"""


@dataclass
class Finding:
    severity: str
    title: str
    description: str
    category: str = "general"
    framework: str = ""
    file_path: str = ""
    line_hint: str = ""
    recommendation: str = ""


class ComplianceDB:
    def __init__(self, db_path: Path):
        self.db_path = db_path
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_schema()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA foreign_keys=ON")
        return conn

    @contextmanager
    def connection(self) -> Iterator[sqlite3.Connection]:
        conn = self._connect()
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def _init_schema(self) -> None:
        with self.connection() as conn:
            conn.executescript(SCHEMA)

    def create_session(
        self,
        project_name: str,
        git_branch: str = "",
        git_head: str = "",
    ) -> str:
        session_id = str(uuid.uuid4())
        with self.connection() as conn:
            conn.execute(
                """
                INSERT INTO sessions (id, project_name, started_at, git_branch, git_head)
                VALUES (?, ?, ?, ?, ?)
                """,
                (session_id, project_name, _utcnow(), git_branch, git_head),
            )
        return session_id

    def end_session(self, session_id: str, summary: str = "") -> None:
        with self.connection() as conn:
            conn.execute(
                "UPDATE sessions SET ended_at = ?, summary = ? WHERE id = ?",
                (_utcnow(), summary, session_id),
            )

    def get_active_session(self, project_name: str) -> str | None:
        with self.connection() as conn:
            row = conn.execute(
                """
                SELECT id FROM sessions
                WHERE project_name = ? AND ended_at IS NULL
                ORDER BY started_at DESC LIMIT 1
                """,
                (project_name,),
            ).fetchone()
        return row["id"] if row else None

    def record_decision(
        self,
        session_id: str,
        trigger: str,
        decision: str,
        reasoning: str = "",
        context: str = "",
        actor: str = "harness",
        metadata: dict[str, Any] | None = None,
    ) -> str:
        decision_id = str(uuid.uuid4())
        with self.connection() as conn:
            conn.execute(
                """
                INSERT INTO decisions
                (id, session_id, created_at, trigger, context, decision, reasoning, actor, metadata_json)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    decision_id,
                    session_id,
                    _utcnow(),
                    trigger,
                    context,
                    decision,
                    reasoning,
                    actor,
                    json.dumps(metadata or {}),
                ),
            )
        return decision_id

    def record_review(
        self,
        session_id: str,
        trigger: str,
        verdict: str,
        reasoning: str = "",
        diff_summary: str = "",
        files_changed: list[str] | None = None,
        raw_response: str = "",
    ) -> str:
        review_id = str(uuid.uuid4())
        with self.connection() as conn:
            conn.execute(
                """
                INSERT INTO reviews
                (id, session_id, created_at, trigger, diff_summary, files_changed, reasoning, verdict, raw_response)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    review_id,
                    session_id,
                    _utcnow(),
                    trigger,
                    diff_summary,
                    json.dumps(files_changed or []),
                    reasoning,
                    verdict,
                    raw_response,
                ),
            )
        return review_id

    def record_findings(
        self,
        review_id: str,
        session_id: str,
        findings: list[Finding],
    ) -> list[str]:
        ids: list[str] = []
        with self.connection() as conn:
            for f in findings:
                fid = str(uuid.uuid4())
                conn.execute(
                    """
                    INSERT INTO compliance_findings
                    (id, review_id, session_id, created_at, severity, category, framework,
                     title, description, file_path, line_hint, recommendation)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        fid,
                        review_id,
                        session_id,
                        _utcnow(),
                        f.severity.lower(),
                        f.category,
                        f.framework,
                        f.title,
                        f.description,
                        f.file_path,
                        f.line_hint,
                        f.recommendation,
                    ),
                )
                ids.append(fid)
        return ids

    def get_session_data(self, session_id: str) -> dict[str, Any]:
        with self.connection() as conn:
            session = conn.execute("SELECT * FROM sessions WHERE id = ?", (session_id,)).fetchone()
            decisions = conn.execute(
                "SELECT * FROM decisions WHERE session_id = ? ORDER BY created_at",
                (session_id,),
            ).fetchall()
            reviews = conn.execute(
                "SELECT * FROM reviews WHERE session_id = ? ORDER BY created_at",
                (session_id,),
            ).fetchall()
            findings = conn.execute(
                "SELECT * FROM compliance_findings WHERE session_id = ? ORDER BY created_at",
                (session_id,),
            ).fetchall()
        return {
            "session": dict(session) if session else {},
            "decisions": [dict(r) for r in decisions],
            "reviews": [dict(r) for r in reviews],
            "findings": [dict(r) for r in findings],
        }

    def get_daily_data(self, date_str: str, project_name: str) -> dict[str, Any]:
        """date_str format: YYYY-MM-DD"""
        with self.connection() as conn:
            sessions = conn.execute(
                """
                SELECT * FROM sessions
                WHERE project_name = ? AND started_at LIKE ?
                ORDER BY started_at
                """,
                (project_name, f"{date_str}%"),
            ).fetchall()
            session_ids = [r["id"] for r in sessions]
            if not session_ids:
                return {"sessions": [], "decisions": [], "reviews": [], "findings": []}

            placeholders = ",".join("?" * len(session_ids))
            decisions = conn.execute(
                f"SELECT * FROM decisions WHERE session_id IN ({placeholders}) ORDER BY created_at",
                session_ids,
            ).fetchall()
            reviews = conn.execute(
                f"SELECT * FROM reviews WHERE session_id IN ({placeholders}) ORDER BY created_at",
                session_ids,
            ).fetchall()
            findings = conn.execute(
                f"SELECT * FROM compliance_findings WHERE session_id IN ({placeholders}) ORDER BY created_at",
                session_ids,
            ).fetchall()

        return {
            "sessions": [dict(r) for r in sessions],
            "decisions": [dict(r) for r in decisions],
            "reviews": [dict(r) for r in reviews],
            "findings": [dict(r) for r in findings],
        }

    def get_unresolved_findings(self, project_name: str, min_severity: str = "low") -> list[dict]:
        severity_map = {"low": 0, "medium": 1, "high": 2, "critical": 3}
        min_level = severity_map.get(min_severity.lower(), 0)
        with self.connection() as conn:
            rows = conn.execute(
                """
                SELECT f.*, s.project_name
                FROM compliance_findings f
                JOIN sessions s ON f.session_id = s.id
                WHERE s.project_name = ? AND f.resolved = 0
                ORDER BY f.created_at DESC
                """,
                (project_name,),
            ).fetchall()
        return [
            dict(r)
            for r in rows
            if severity_map.get(r["severity"], 0) >= min_level
        ]

    def export_json(self, output_path: Path, project_name: str | None = None) -> None:
        with self.connection() as conn:
            if project_name:
                sessions = conn.execute(
                    "SELECT * FROM sessions WHERE project_name = ? ORDER BY started_at",
                    (project_name,),
                ).fetchall()
            else:
                sessions = conn.execute("SELECT * FROM sessions ORDER BY started_at").fetchall()

            data = []
            for s in sessions:
                data.append(self.get_session_data(s["id"]))

        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(json.dumps(data, indent=2, default=str))
