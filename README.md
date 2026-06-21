# Compliance Review Harness

A governance **gap layer** for AI-assisted development. It sits between your editor, commit, and push — recording every compliance decision, persisting audit data to **SQLite**, and writing **markdown reports** per session and per day.

> Governance and compliance in AI coding is the wild west. This is a stopgap: alert while coding, gate before commit, loopback review before push.

## What it does

| Layer | When | What |
|-------|------|------|
| **Live watch** | While coding | File change alerts for critical/high compliance issues |
| **Pre-commit** | Before commit | Heuristic + LLM review; blocks on critical findings |
| **Pre-push** | Before push | Loopback review of entire session with decision context |
| **Retention** | Always | SQLite archive + daily/session markdown audit trails |

## Architecture

```
┌─────────────┐     ┌──────────────────┐     ┌─────────────────┐
│  File Watch │────▶│  Review Engine   │────▶│  SQLite DB      │
│  (alerts)   │     │  heuristic+LLM   │     │  decisions      │
└─────────────┘     └────────┬─────────┘     │  reviews        │
                              │               │  findings       │
┌─────────────┐               │               └────────┬────────┘
│ Pre-commit  │───────────────┤                        │
│ Pre-push    │───────────────┤                        ▼
└─────────────┘               │               ┌─────────────────┐
                              └──────────────▶│  MD Reports     │
                                              │  session + daily│
                                              └─────────────────┘
```

## Quick start

```bash
cd /path/to/your/repo
pip install -e /var/www/compliance

# Initialize in your project (installs git hooks, creates .compliance/)
crh init

# Copy and edit config
cp config.example.yaml config.yaml   # or edit the one crh init creates

# Set your LLM key (OpenAI-compatible API)
export OPENAI_API_KEY=sk-...

# Live coding alerts
crh watch

# Manual review
crh review

# Check status / unresolved findings
crh status
```

## LLM providers

### OpenAI / Azure / any OpenAI-compatible API

```yaml
llm:
  provider: openai
  api_url: "https://api.openai.com/v1/chat/completions"
  api_key_env: OPENAI_API_KEY
  model: "gpt-4o-mini"
```

### Local Ollama

```yaml
llm:
  provider: ollama
  ollama_url: "http://localhost:11434/api/chat"
  ollama_model: "llama3.2"
```

Without an LLM configured, heuristic pattern scanning still runs (secrets, PII patterns, eval/exec, SSL bypass).

## SQLite retention

All decisions, reviews, and findings are stored in `.compliance/data/compliance.db`:

- **sessions** — coding sessions with git branch/HEAD
- **decisions** — allow/block/skip with reasoning and trigger
- **reviews** — full review records with diff summaries
- **compliance_findings** — severity-tagged issues with framework mapping

Export for external systems:

```bash
crh export-json -o .compliance/archive.json
crh export-md --daily
crh export-md --session-id <uuid>
```

### Postgres / MySQL retention

SQLite stays the local source of truth. Enable remote mirroring in `config.yaml`:

```yaml
retention:
  sync_on_review: true
  postgres:
    enabled: true
    url_env: CRH_POSTGRES_URL
  mysql:
    enabled: true
    url_env: CRH_MYSQL_URL
```

```bash
pip install 'compliance-review-harness[postgres]'   # psycopg
pip install 'compliance-review-harness[mysql]'       # pymysql

export CRH_POSTGRES_URL=postgresql://user:pass@localhost:5432/compliance
export CRH_MYSQL_URL=mysql://user:pass@localhost:3306/compliance

crh sync-db              # full sync
crh sync-db --session-id <uuid>
```

Remote sync runs automatically after each review when enabled.

## Git hooks

`crh init` installs:

- **pre-commit** — compliance review; blocks on `critical` (configurable)
- **pre-push** — loopback session review; blocks on `high` (configurable)

Emergency bypass (logged to SQLite):

```bash
CRH_SKIP=1 git commit -m "hotfix"
```

## Configuration

See `config.example.yaml` for all options:

- `compliance.frameworks` — SOC2, GDPR, HIPAA, etc.
- `compliance.custom_rules` — project-specific policy rules
- `compliance.block_commit_on` / `block_push_on` — severity thresholds
- `watch.ignore_patterns` — paths to skip in live watch

## CLI reference

```
crh init              Initialize harness + hooks in a repo
crh install-hooks     Re-install git hooks
crh watch             Live coding compliance alerts
crh review            On-demand review of current diff
crh pre-commit        Pre-commit gate (called by hook)
crh pre-push          Pre-push loopback gate (called by hook)
crh loopback          Re-review entire session
crh status            Session + unresolved findings
crh end-session       Close session, write reports
crh export-md         Generate markdown from SQLite
crh export-json       Export SQLite data to JSON
crh sync-db           Mirror SQLite to Postgres/MySQL
```

## Repo

Target GitHub repo: [tedrubin80/ComplianceReviewharness](https://github.com/tedrubin80/ComplianceReviewharness)

## License

MIT
