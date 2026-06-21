# compliancegate (npm)

Node wrapper for installing [ComplianceGate](https://compliancegate.dev) into a git repo. The npm package bootstraps the **Python CLI** — hooks, rule packs, and review logic live in the Python package.

**Site:** [compliancegate.dev](https://compliancegate.dev) · **GitHub:** [tedrubin80/compliancegate](https://github.com/tedrubin80/compliancegate)

> **Status:** Scaffold — not yet published to npm. Test locally with `node bin/compliancegate.js` or `npm link`.

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
```

## Verify

```bash
npx compliancegate check
```

## Run the Python CLI via npx

After install, passthrough to the venv binary:

```bash
npx compliancegate run status
npx compliancegate run rules list
npx compliancegate run watch
```

Or use the venv directly:

```bash
.venv/bin/compliancegate watch
```

## Agent skills

```bash
npx compliancegate skills install              # compliancegate → ~/.cursor/skills/
npx compliancegate skills install --all          # Cursor + Claude
npx compliancegate skills install --all-skills   # + compliance-review standalone skill
npx compliancegate skills install --project      # .cursor/skills/ in current repo
npx compliancegate skills check
```

## Local development

Install from this monorepo instead of GitHub:

```bash
export CG_INSTALL_SOURCE=/var/www/compliance
node bin/compliancegate.js install --repo /path/to/test-repo
```

Or:

```bash
node bin/compliancegate.js install --source /var/www/compliance --repo .
```

## Publish (maintainers)

```bash
cd npm
npm login
npm publish --access public
```

## License

MIT
