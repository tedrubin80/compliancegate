# compliancegate (npm)

Node installer for [ComplianceGate](https://compliancegate.dev) — hooks, rule packs, LLM routing, and agent skills.

**Site:** [compliancegate.dev](https://compliancegate.dev) · **GitHub:** [tedrubin80/compliancegate](https://github.com/tedrubin80/compliancegate) · **npm:** [compliancegate](https://www.npmjs.com/package/compliancegate)

## What it does

| Command | Purpose |
|---------|---------|
| `npx compliancegate install` | venv + pip + hooks + config + project agent skill |
| `npx compliancegate check` | Verify hooks, venv, CLI |
| `npx compliancegate skills install` | Cursor / Claude agent skills |
| `npx compliancegate run …` | Passthrough to Python CLI |

## Requirements

- Node.js 18+
- Python 3.10+
- A git repository (target project)

## Install into your repo

```bash
cd /path/to/your/project
npx compliancegate install
```

With options:

```bash
npx compliancegate install --mode sqlite_markdown --packs base,pii
npx compliancegate install --repo . --mode markdown
npx compliancegate install --langchain   # two-stage LLM review deps
```

This also copies the **compliancegate** agent skill to `.cursor/skills/compliancegate/`.

## Verify

```bash
npx compliancegate check
```

## Agent skills

```bash
npx compliancegate skills install              # compliancegate → ~/.cursor/skills/
npx compliancegate skills install --all        # Cursor + Claude
npx compliancegate skills install --all-skills # + compliance-review standalone
npx compliancegate skills install --project    # .cursor/skills/ in current repo
npx compliancegate skills check
```

| Skill | Use when |
|-------|----------|
| `compliancegate` | Repo has CG hooks — invoke CLI, interpret findings |
| `compliance-review` | Standalone in-chat review — no CG install required |

## Run the Python CLI via npx

```bash
npx compliancegate run status
npx compliancegate run rules list
npx compliancegate run llm route
npx compliancegate run watch
```

Or use the venv directly:

```bash
.venv/bin/compliancegate watch
```

## LLM routing (after install)

Configure `config.yaml` in your repo:

```yaml
llm:
  provider: openrouter
  api_key_env: OPENROUTER_API_KEY
  model: anthropic/claude-3.5-sonnet

langchain:
  enabled: true   # use --langchain on install, or: pip install 'compliancegate[langchain]'
```

```bash
npx compliancegate run llm test
```

## Local development

```bash
export CG_INSTALL_SOURCE=/var/www/compliance
node bin/compliancegate.js install --repo /path/to/test-repo
```

Sync skills before npm publish:

```bash
npm run sync-skills
```

## Publish (maintainers)

```bash
cd npm
npm run sync-skills
npm login
npm publish --access public
```

`prepublishOnly` runs `sync-skills` automatically.

## License

MIT
