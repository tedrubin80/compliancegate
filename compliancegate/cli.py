from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import click

from compliancegate import __version__
from compliancegate.config import load_config, severity_at_or_above
from compliancegate.db import ComplianceDB
from compliancegate.git_hooks import init_project, install_hooks
from compliancegate.markdown_export import write_daily_report, write_session_report
from compliancegate.reviewer import ComplianceReviewer
from compliancegate.session import SessionManager
from compliancegate.storage import describe_storage_mode


def _skip_check() -> bool:
    return os.environ.get("CG_SKIP", "").strip() in ("1", "true", "yes")


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
    click.echo(f"{'=' * 60}\n")


def _storage_note(cfg) -> str:
    parts = []
    if cfg.storage.persist_sqlite:
        parts.append(f"SQLite → {cfg.repo_root / cfg.storage.sqlite_path}")
    if cfg.storage.use_markdown:
        parts.append(f"Markdown → {cfg.markdown_dir}")
    if cfg.storage.use_remote:
        parts.append("Remote DB (Postgres/MySQL)")
    if not parts:
        parts.append("in-memory session only")
    return " | ".join(parts)


@click.group()
@click.version_option(__version__, prog_name="compliancegate")
def main():
    """ComplianceGate — governance gap layer between AI-assisted coding and ship."""
    pass


@main.group("rules")
def rules_group():
    """Inspect modular compliance rule packs (HIPAA, PII, PCI, etc.)."""
    pass


@rules_group.command("list")
@click.option("--config", "config_path", type=click.Path(exists=True), default=None)
def rules_list(config_path: str | None):
    """List available rule packs and sensitivity flags."""
    from compliancegate.rules.loader import list_available_packs

    cfg = load_config(Path(config_path) if config_path else None)
    click.echo(f"Rules dir: {cfg.rules_dir}\n")
    for pack in list_available_packs(cfg.rules_dir):
        flag = "SENSITIVE" if pack["sensitive"] else "safe"
        click.echo(
            f"  {pack['id']:8}  [{flag:9}]  {pack['name']}  "
            f"({pack['rules']} rules, {pack['patterns']} patterns)"
        )
    click.echo(f"\nEnabled in config: {', '.join(cfg.compliance.rule_packs)}")


@rules_group.command("show")
@click.argument("pack_id")
@click.option("--config", "config_path", type=click.Path(exists=True), default=None)
def rules_show(pack_id: str, config_path: str | None):
    """Show rules and patterns for one pack."""
    from compliancegate.rules.loader import load_rule_packs

    cfg = load_config(Path(config_path) if config_path else None)
    pack = load_rule_packs([pack_id], cfg.rules_dir)[0]
    click.echo(f"# {pack.name} ({pack.id})")
    click.echo(f"sensitive: {pack.sensitive}")
    click.echo(f"frameworks: {', '.join(pack.frameworks)}\n")
    click.echo("## Rules")
    for rule in pack.rules:
        click.echo(f"  - {rule}")
    if pack.patterns:
        click.echo("\n## Patterns")
        for p in pack.patterns:
            click.echo(f"  - [{p.severity}] {p.title} ({p.category})")


@main.group("llm")
def llm_group():
    """Test and inspect LLM provider routing (OpenAI, OpenRouter, Ollama)."""
    pass


@llm_group.command("route")
@click.option("--config", "config_path", type=click.Path(exists=True), default=None)
def llm_route(config_path: str | None):
    """Show the active LLM route and env var requirements."""
    from compliancegate.config import get_api_key
    from compliancegate.langchain_pipeline import describe_langchain_pipeline, is_langchain_available

    cfg = load_config(Path(config_path) if config_path else None)
    llm = cfg.llm
    key_set = bool(get_api_key(cfg))

    click.echo(f"Provider:    {llm.provider}")
    click.echo(f"Pipeline:    {describe_langchain_pipeline(cfg)}")
    if cfg.langchain.enabled:
        deps = "installed" if is_langchain_available() else "missing — pip install 'compliancegate[langchain]'"
        click.echo(f"LangChain:   {deps}")
        click.echo(f"  Reasoning: {cfg.langchain.reasoning.model} (temp {cfg.langchain.reasoning.temperature})")
        click.echo(f"  Analytical:{cfg.langchain.analytical.model} (temp {cfg.langchain.analytical.temperature})")
    click.echo(f"Endpoint:    {llm.api_url}")
    click.echo(f"Model:       {llm.model}")
    if llm.fallback_models:
        click.echo(f"Fallbacks:   {', '.join(llm.fallback_models)}")
    click.echo(f"API key env: {llm.api_key_env} ({'set' if key_set else 'missing'})")
    click.echo(f"JSON mode:   {llm.json_mode}")
    click.echo(f"Redact:      {llm.redact_before_send}")
    if llm.provider == "openrouter":
        click.echo(f"Referer:     {llm.site_url}")
        click.echo(f"App title:   {llm.app_title}")
    elif llm.provider == "ollama":
        click.echo(f"Ollama URL:  {llm.ollama_url}")
        click.echo(f"Ollama model:{llm.ollama_model}")


@llm_group.command("test")
@click.option("--config", "config_path", type=click.Path(exists=True), default=None)
def llm_test(config_path: str | None):
    """Probe the configured LLM route with a minimal JSON request."""
    from compliancegate.llm import LLMClient

    cfg = load_config(Path(config_path) if config_path else None)
    client = LLMClient(cfg)
    result = client.probe()

    click.echo(f"Provider:  {cfg.llm.provider}")
    click.echo(f"Model:     {cfg.llm.model}")
    click.echo(f"Verdict:   {result.get('verdict', 'unknown')}")
    click.echo(f"Reasoning: {result.get('reasoning', '')}")

    reasoning = str(result.get("reasoning", "")).lower()
    if result.get("findings"):
        click.echo(f"Findings:  {len(result['findings'])} returned during probe")

    if any(token in reasoning for token in ("no api key", "unavailable", "failed")):
        sys.exit(1)

    if result.get("verdict") == "fail":
        sys.exit(1)


@llm_group.command("models")
@click.option("--config", "config_path", type=click.Path(exists=True), default=None)
@click.option("--filter", "name_filter", default="", help="Filter model ids (case-insensitive substring)")
@click.option("--limit", default=20, show_default=True, help="Max models to print")
def llm_models(config_path: str | None, name_filter: str, limit: int):
    """List models from OpenRouter (provider must be openrouter or pass OPENROUTER_API_KEY)."""
    from compliancegate.config import get_api_key
    from compliancegate.llm import fetch_openrouter_models

    cfg = load_config(Path(config_path) if config_path else None)
    api_key = get_api_key(cfg) if cfg.llm.provider == "openrouter" else os.environ.get("OPENROUTER_API_KEY")

    try:
        models = fetch_openrouter_models(api_key)
    except Exception as exc:
        click.echo(f"Failed to fetch OpenRouter models: {exc}")
        sys.exit(1)

    filt = name_filter.lower().strip()
    shown = 0
    for model in models:
        model_id = str(model.get("id", ""))
        if filt and filt not in model_id.lower():
            continue
        ctx = model.get("context_length")
        ctx_label = f"{ctx} ctx" if ctx else "ctx ?"
        click.echo(f"  {model_id:<44} {ctx_label}")
        shown += 1
        if shown >= limit:
            break

    if not shown:
        click.echo("No models matched.")
        sys.exit(1)

    if shown == limit:
        click.echo(f"\nShowing first {limit}. Use --limit or --filter to narrow.")


@main.command("init")
@click.option("--repo", type=click.Path(exists=True), default=".", help="Target git repo root")
@click.option(
    "--mode",
    type=click.Choice(["sqlite", "markdown", "remote", "sqlite_markdown", "all"]),
    default=None,
    help="Where review data is persisted",
)
def cmd_init(repo: str, mode: str | None):
    """Initialize harness, storage, and git hooks in a repo."""
    repo_root = Path(repo).resolve()
    harness_root = Path(__file__).resolve().parent.parent
    init_project(repo_root, harness_root, storage_mode=mode)
    if mode:
        click.echo(f"Storage mode: {describe_storage_mode(mode)}")


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
        click.echo("[compliancegate] CG_SKIP set — bypassing pre-commit review (decision logged if possible)")
        try:
            cfg = load_config(Path(config_path) if config_path else None)
            db = ComplianceDB(cfg.sqlite_path)
            sm = SessionManager(cfg, db)
            sid = sm.ensure_session()
            db.record_decision(sid, "pre-commit", "skip", reasoning="CG_SKIP override", actor="developer")
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
    click.echo(f"Saved: {_storage_note(cfg)}")
    sys.exit(0 if result.allowed else 1)


@main.command("pre-push")
@click.option("--config", "config_path", type=click.Path(exists=True), default=None)
def cmd_pre_push(config_path: str | None):
    """Gate: loopback review of all session changes before push."""
    if _skip_check():
        click.echo("[compliancegate] CG_SKIP set — bypassing pre-push review")
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
    from compliancegate.watcher import run_watcher

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

    from compliancegate.remote_db import sync_all, sync_session

    try:
        if session_id:
            counts = sync_session(cfg, db, session_id)
        else:
            counts = sync_all(cfg, db)
    except ImportError as exc:
        click.echo(f"Missing driver: {exc}. Install with: pip install 'compliancegate[postgres]' or '[mysql]'")
        sys.exit(1)
    except RuntimeError as exc:
        click.echo(str(exc))
        sys.exit(1)

    if not counts:
        click.echo("No remote backends enabled. Enable retention.postgres or retention.mysql in config.yaml.")
        sys.exit(1)

    for backend, n in counts.items():
        click.echo(f"{backend}: synced {n} rows")


@main.command("export-json")
@click.option("--config", "config_path", type=click.Path(exists=True), default=None)
@click.option("--output", "-o", default=".compliancegate/export.json")
def cmd_export_json(config_path: str | None, output: str):
    """Export all SQLite retention data to JSON."""
    cfg = load_config(Path(config_path) if config_path else None)
    if not cfg.storage.persist_sqlite:
        click.echo("storage.mode does not persist SQLite — nothing to export. Use export-md or sync-db.")
        sys.exit(1)
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
    click.echo(f"Storage:     {describe_storage_mode(cfg.storage.mode)}")
    if cfg.storage.persist_sqlite:
        click.echo(f"SQLite:      {cfg.sqlite_path}")
    if cfg.storage.use_markdown:
        click.echo(f"Reports:     {cfg.markdown_dir}")
    if cfg.storage.use_remote:
        pg = "on" if cfg.retention.postgres.enabled else "off"
        my = "on" if cfg.retention.mysql.enabled else "off"
        click.echo(f"Remote:      postgres={pg} mysql={my} payload={cfg.retention.remote_payload}")
    click.echo(f"LLM:         {cfg.llm.provider} / {cfg.llm.model}")
    from compliancegate.langchain_pipeline import describe_langchain_pipeline
    click.echo(f"Pipeline:    {describe_langchain_pipeline(cfg)}")
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
