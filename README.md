# ComplianceGate

**[compliancegate.dev](https://compliancegate.dev)** — governance gap layer between AI-assisted coding and ship.

ComplianceGate records policy decisions, runs pre-commit/pre-push checks, and saves audit data to **your choice of storage**: local SQLite, markdown, or remote Postgres/MySQL.

> AI governance is the wild west. ComplianceGate is the gate before push.

## Install

```bash
npx compliancegate install
```

Or clone and use the install script:

```bash
bash scripts/install.sh --repo /path/to/your/project --mode sqlite_markdown
```

See [`npm/README.md`](npm/README.md) for the npx wrapper (scaffold — not yet on npm registry).

## CLI

```bash
compliancegate init --mode markdown
compliancegate watch
compliancegate rules list
compliancegate status
```

Short alias: **`cg`**

## Agent skills

Two Cursor / Claude skills ship in `skills/`:

| Skill | Use when |
|-------|----------|
| `compliancegate` | Repo has CG hooks — invoke CLI, interpret findings |
| `compliance-review` | Standalone in-chat review — no CG install required |

```bash
# Personal skills (Cursor / Claude home)
npx compliancegate skills install
npx compliancegate skills install --all-skills --all

# Project-local (copies to .cursor/skills/ in repo)
npx compliancegate skills install --project
bash scripts/install.sh --repo .   # also installs compliancegate skill
```

## Storage modes

| Mode | Saves to |
|------|----------|
| `sqlite` | `.compliancegate/data/compliancegate.db` |
| `markdown` | Session + daily `.md` in `.compliancegate/reports/` |
| `remote` | Postgres/MySQL (metadata-only by default) |
| `sqlite_markdown` | SQLite + markdown **(default)** |
| `all` | SQLite + markdown + remote |

```yaml
storage:
  mode: sqlite_markdown
```

## Rule packs

```bash
compliancegate rules show hipaa
```

```yaml
compliance:
  rule_packs: [base, pii, hipaa, pci]
```

## LLM routing (OpenRouter)

Route reviews through [OpenRouter](https://openrouter.ai) for model choice, fallbacks, and one API key:

```yaml
llm:
  provider: openrouter
  api_key_env: OPENROUTER_API_KEY
  model: anthropic/claude-3.5-sonnet
  fallback_models:
    - openai/gpt-4o-mini
  redact_before_send: true
```

```bash
export OPENROUTER_API_KEY=sk-or-...
compliancegate llm route
compliancegate llm test
compliancegate llm models --filter claude --limit 10
```

Defaults when `provider: openrouter`: endpoint `https://openrouter.ai/api/v1/chat/completions`, attribution headers for compliancegate.dev.

## LangChain pipeline (optional)

Two-stage review: **reasoning model** analyzes diffs against enabled rule packs, then **analytical model** produces structured findings JSON.

```bash
pip install 'compliancegate[langchain]'
```

```yaml
llm:
  provider: openrouter
  api_key_env: OPENROUTER_API_KEY
  redact_before_send: true

langchain:
  enabled: true
  reasoning:
    model: anthropic/claude-3.5-sonnet
    temperature: 0.3
  analytical:
    model: openai/gpt-4o-mini
    temperature: 0.1
```

```bash
compliancegate llm route
compliancegate llm test
```

Pack rules are injected into the reasoning pass; the analytical pass converts reasoning into audit-ready findings without inventing new issues.

## Remote database (optional)

```bash
pip install 'compliancegate[postgres,mysql]'
export CG_POSTGRES_URL=postgresql://user:pass@localhost:5432/compliancegate
compliancegate sync-db
```

## Git hooks

Emergency bypass: `CG_SKIP=1 git commit`

## Links

- **Site:** [compliancegate.dev](https://compliancegate.dev)
- **Repo:** [github.com/tedrubin80/compliancegate](https://github.com/tedrubin80/compliancegate)

## License

MIT
