from __future__ import annotations

import os
import sqlite3
from typing import Any

from compliance_harness.config import HarnessConfig
from compliance_harness.db import ComplianceDB

TABLES = ("sessions", "decisions", "reviews", "compliance_findings")

PG_SCHEMA = """
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
    metadata_json TEXT
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
    raw_response TEXT
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
    resolved INTEGER DEFAULT 0
);
"""

MYSQL_SCHEMA = """
CREATE TABLE IF NOT EXISTS sessions (
    id VARCHAR(36) PRIMARY KEY,
    project_name TEXT NOT NULL,
    started_at TEXT NOT NULL,
    ended_at TEXT,
    git_branch TEXT,
    git_head TEXT,
    summary TEXT
) ENGINE=InnoDB;
CREATE TABLE IF NOT EXISTS decisions (
    id VARCHAR(36) PRIMARY KEY,
    session_id VARCHAR(36) NOT NULL,
    created_at TEXT NOT NULL,
    `trigger` TEXT NOT NULL,
    context TEXT,
    decision TEXT NOT NULL,
    reasoning TEXT,
    actor TEXT DEFAULT 'harness',
    metadata_json TEXT
) ENGINE=InnoDB;
CREATE TABLE IF NOT EXISTS reviews (
    id VARCHAR(36) PRIMARY KEY,
    session_id VARCHAR(36) NOT NULL,
    created_at TEXT NOT NULL,
    `trigger` TEXT NOT NULL,
    diff_summary TEXT,
    files_changed TEXT,
    reasoning TEXT,
    verdict TEXT NOT NULL,
    raw_response TEXT
) ENGINE=InnoDB;
CREATE TABLE IF NOT EXISTS compliance_findings (
    id VARCHAR(36) PRIMARY KEY,
    review_id VARCHAR(36) NOT NULL,
    session_id VARCHAR(36) NOT NULL,
    created_at TEXT NOT NULL,
    severity TEXT NOT NULL,
    category TEXT,
    framework TEXT,
    title TEXT NOT NULL,
    description TEXT NOT NULL,
    file_path TEXT,
    line_hint TEXT,
    recommendation TEXT,
    resolved INT DEFAULT 0
) ENGINE=InnoDB;
"""


def maybe_sync_retention(config: HarnessConfig, db: ComplianceDB, session_id: str) -> None:
    """Hook: mirror SQLite session data to enabled Postgres/MySQL backends."""
    retention = config.retention
    if not retention.sync_on_review:
        return
    if not (retention.postgres.enabled or retention.mysql.enabled):
        return
    sync_session(config, db, session_id)


def sync_session(config: HarnessConfig, db: ComplianceDB, session_id: str) -> dict[str, int]:
    data = db.get_session_data(session_id)
    counts: dict[str, int] = {}

    if config.retention.postgres.enabled:
        counts["postgres"] = _sync_postgres(config, data)
    if config.retention.mysql.enabled:
        counts["mysql"] = _sync_mysql(config, data)

    return counts


def sync_all(config: HarnessConfig, db: ComplianceDB) -> dict[str, int]:
    with db.connection() as conn:
        rows = conn.execute(
            "SELECT id FROM sessions WHERE project_name = ? ORDER BY started_at",
            (config.project_name,),
        ).fetchall()
    totals: dict[str, int] = {}
    for row in rows:
        part = sync_session(config, db, row["id"])
        for k, v in part.items():
            totals[k] = totals.get(k, 0) + v
    return totals


def _sync_postgres(config: HarnessConfig, data: dict[str, Any]) -> int:
    import psycopg

    dsn = _resolve_dsn(config.retention.postgres.url_env)
    upserted = 0
    with psycopg.connect(dsn) as conn:
        with conn.cursor() as cur:
            for stmt in PG_SCHEMA.strip().split(";"):
                if stmt.strip():
                    cur.execute(stmt)
            upserted += _upsert_rows(cur, "sessions", [data["session"]], _pg_upsert)
            upserted += _upsert_rows(cur, "decisions", data["decisions"], _pg_upsert)
            upserted += _upsert_rows(cur, "reviews", data["reviews"], _pg_upsert)
            upserted += _upsert_rows(cur, "compliance_findings", data["findings"], _pg_upsert)
        conn.commit()
    return upserted


def _sync_mysql(config: HarnessConfig, data: dict[str, Any]) -> int:
    import pymysql

    dsn = _parse_mysql_dsn(_resolve_dsn(config.retention.mysql.url_env))
    upserted = 0
    conn = pymysql.connect(**dsn)
    try:
        with conn.cursor() as cur:
            for stmt in MYSQL_SCHEMA.strip().split(";"):
                if stmt.strip():
                    cur.execute(stmt)
            upserted += _upsert_rows(cur, "sessions", [data["session"]], _mysql_upsert)
            upserted += _upsert_rows(cur, "decisions", data["decisions"], _mysql_upsert)
            upserted += _upsert_rows(cur, "reviews", data["reviews"], _mysql_upsert)
            upserted += _upsert_rows(cur, "compliance_findings", data["findings"], _mysql_upsert)
        conn.commit()
    finally:
        conn.close()
    return upserted


def _upsert_rows(cur, table: str, rows: list[dict], upsert_fn) -> int:
    count = 0
    for row in rows:
        if not row or not row.get("id"):
            continue
        cols = list(row.keys())
        upsert_fn(cur, table, cols, row)
        count += 1
    return count


def _pg_upsert(cur, table: str, cols: list[str], row: dict) -> None:
    placeholders = ", ".join(["%s"] * len(cols))
    col_list = ", ".join(cols)
    updates = ", ".join(f"{c} = EXCLUDED.{c}" for c in cols if c != "id")
    cur.execute(
        f"INSERT INTO {table} ({col_list}) VALUES ({placeholders}) "
        f"ON CONFLICT (id) DO UPDATE SET {updates}",
        [row[c] for c in cols],
    )


def _mysql_upsert(cur, table: str, cols: list[str], row: dict) -> None:
    placeholders = ", ".join(["%s"] * len(cols))
    col_list = ", ".join(f"`{c}`" if c == "trigger" else c for c in cols)
    updates = ", ".join(
        f"`{c}` = VALUES(`{c}`)" if c == "trigger" else f"{c} = VALUES({c})"
        for c in cols if c != "id"
    )
    cur.execute(
        f"INSERT INTO {table} ({col_list}) VALUES ({placeholders}) "
        f"ON DUPLICATE KEY UPDATE {updates}",
        [row[c] for c in cols],
    )


def _resolve_dsn(env_var: str) -> str:
    dsn = os.environ.get(env_var, "").strip()
    if not dsn:
        raise RuntimeError(f"Retention DSN not set: export {env_var}=...")
    return dsn


def _parse_mysql_dsn(dsn: str) -> dict[str, Any]:
    # mysql://user:pass@host:3306/dbname
    from urllib.parse import urlparse

    u = urlparse(dsn)
    if u.scheme not in ("mysql", "mysql+pymysql"):
        raise ValueError(f"Expected mysql:// DSN, got {u.scheme}")
    return {
        "host": u.hostname or "localhost",
        "port": u.port or 3306,
        "user": u.username or "",
        "password": u.password or "",
        "database": (u.path or "/").lstrip("/"),
        "charset": "utf8mb4",
    }
