# ComplianceGate

**compliancegate.dev** — governance gap layer between AI-assisted coding and ship.

ComplianceGate records policy decisions, runs pre-commit/pre-push checks, and saves audit data to **your choice of storage**: local SQLite, markdown, or remote Postgres/MySQL.

> AI governance is the wild west. ComplianceGate is the gate before push.

## Install

```bash
bash scripts/install.sh --repo /path/to/your/project --mode sqlite_markdown
```

## CLI

```bash
compliancegate init --mode markdown
compliancegate watch
compliancegate rules list
compliancegate status
```

Short alias: **`cg`**

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
