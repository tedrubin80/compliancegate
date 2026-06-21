---
name: compliancegate
description: >
  ComplianceGate-integrated governance skill. Invokes the ComplianceGate CLI (watch, review, pre-commit,
  pre-push loopback) and interprets findings against enabled rule packs (base, pii, hipaa, pci). Use in
  repos where ComplianceGate is initialized with hooks installed. Triggers on code touching secrets, PII,
  PHI, payment data, config changes, or explicit requests to run compliance review, check findings, or
  read the audit trail. For in-chat-only review without CG installed, use the compliance-review skill.
version: 0.1.0
user-invocable: true
argument-hint: "[review|rules|status|report|llm]"
---

# ComplianceGate Skill

You operate as the AI reasoning layer on top of ComplianceGate's gate pipeline. CG runs heuristic pattern
scans (local) plus optional LLM review (OpenRouter, OpenAI, or Ollama). Your job is to invoke the right
CG commands, interpret findings, suggest fixes, and help resolve blocks before commit or push.

ComplianceGate should already be initialized in this repo. Do not re-run `compliancegate init` unless the
user explicitly asks to reinstall.

Short CLI alias: **`cg`** (same as `compliancegate`).

---

## CLI Reference

```bash
compliancegate watch              # Live file watcher (debounced alerts)
compliancegate review             # Manual review of current staged/working diff
compliancegate pre-commit         # Pre-commit gate (hooks call this automatically)
compliancegate pre-push           # Pre-push loopback (hooks call this automatically)
compliancegate loopback           # Manual session loopback review
compliancegate rules list         # Enabled rule packs
compliancegate rules show <pack>  # Pack detail: base | pii | hipaa | pci
compliancegate status             # Session, storage paths, unresolved findings
compliancegate export-md          # Write session/daily markdown reports
compliancegate llm route          # Show LLM / LangChain pipeline config
compliancegate llm test           # Probe LLM or LangChain route
```

Install (if missing): `npx compliancegate install` or `bash scripts/install.sh`

Default thresholds: `block_commit_on: critical` · `block_push_on: high`

Without an LLM API key, CG runs **heuristic-only** review — pattern matches still fire; LLM rule evaluation is skipped.

---

## Gate Pipeline

```
Edit → watch (live) → commit (pre-commit gate) → push (pre-push loopback) → audit log
```

| Gate | Command | Default block |
|------|---------|---------------|
| Live watch | `compliancegate watch` | Surfaces Critical + High |
| Pre-commit | hook → `pre-commit` | Critical |
| Pre-push | hook → `pre-push` | High (loopback) |

---

## LLM Routing

Recommended: OpenRouter with one API key and model fallbacks.

```yaml
llm:
  provider: openrouter
  api_key_env: OPENROUTER_API_KEY
  model: anthropic/claude-3.5-sonnet
  fallback_models: [openai/gpt-4o-mini]
  redact_before_send: true
```

Optional two-stage LangChain pipeline (`pip install 'compliancegate[langchain]'`):

```yaml
langchain:
  enabled: true
  reasoning:
    model: anthropic/claude-3.5-sonnet
  analytical:
    model: openai/gpt-4o-mini
```

Verify: `compliancegate llm route` and `compliancegate llm test`

Pack rules are injected into the reasoning pass; the analytical pass produces structured JSON findings.

---

## Your Role at Each Gate

### Watch (live)
- CG surfaces findings as files change
- Explain *why* a finding fired, suggest a fix, warn if Critical findings are accumulating

### Pre-commit
- Hook runs `compliancegate pre-commit` on staged diff
- If blocked: identify finding, provide fix, confirm before re-staging
- If passed with warnings: surface High findings before push

### Pre-push loopback
- Hook runs `compliancegate pre-push` — full session re-review
- If blocked: a High+ issue slipped past commit — treat as urgent
- Read audit: `compliancegate export-md` or `.compliancegate/reports/sessions/`

---

## Invoking ComplianceGate

When the developer asks for a compliance check:

```bash
compliancegate rules list
compliancegate review
compliancegate status
```

If findings exist, read reports:

```bash
compliancegate export-md
# or open .compliancegate/reports/sessions/
```

Pack-specific detail:

```bash
compliancegate rules show pii
compliancegate rules show hipaa
compliancegate rules show pci
compliancegate rules show base
```

---

## Interpreting Findings

```markdown
## ComplianceGate Findings: [context]

**Gate:** watch | pre-commit | pre-push | review
**Verdict:** ok | warn | BLOCK
**Session:** [from status or report filename]

### Blocked / Critical
[title] — [pack] — [file:line if available]
→ Why: [plain English]
→ Fix: [code suggestion]
→ Regulation: [GDPR / HIPAA / PCI-DSS / SOC2]

### Warnings / High
[same structure]

### Next Steps
[ ] Fix criticals → git add → compliancegate review
[ ] Commit (pre-commit hook runs automatically)
[ ] Push (pre-push loopback runs automatically)
```

---

## Rule Packs

| Pack | Scope | Sensitive |
|------|-------|-----------|
| `base` | Secrets, auth, eval/exec, SSL bypass | No |
| `pii` | SSN, email, phone, PII in logs/exports | Yes |
| `hipaa` | PHI fields, external LLM routing, encryption | Yes |
| `pci` | PAN, CVV, track data | Yes |

Sensitive packs default to **local-only retention**. Raw findings do not sync remotely unless
`sync_sensitive_findings: true` is set in config.

Enable in `config.yaml`:

```yaml
compliance:
  rule_packs: [base, pii]  # add hipaa, pci when scope applies
```

---

## Severity → Gate Behavior

| Severity | Watch | Pre-commit | Pre-push |
|----------|-------|------------|----------|
| Critical | Alert | **BLOCK** | BLOCK |
| High | Alert | Warn | **BLOCK** |
| Medium | Log | Log | Log |
| Low | — | — | Log |

---

## Fix → Re-Check Loop

```
1. compliancegate status  or  read .compliancegate/reports/
2. Apply fix (your code suggestion)
3. git add [file]
4. compliancegate review
5. If clean: git commit (hook re-runs pre-commit)
6. git push (pre-push loopback runs automatically)
```

Emergency bypass (logged — use sparingly):

```bash
CG_SKIP=1 git commit -m "hotfix: documented reason"
```

`CG_SKIP` creates an audit record when storage is enabled. It is not invisible.

---

## Audit Trail

| Storage | Path |
|---------|------|
| Session markdown | `.compliancegate/reports/sessions/` |
| Daily rollup | `.compliancegate/reports/daily/` |
| SQLite | `.compliancegate/data/compliancegate.db` |

Commands: `compliancegate export-md` · `compliancegate status`

---

## Behavioral Rules

### Always
- Run `compliancegate rules list` before first review in a session
- Explain *why* a finding fired — heuristic titles alone are not enough
- Provide a code fix for every Critical and High finding
- Confirm the fix resolves the pattern before telling the developer to commit
- Flag PHI routed to external LLMs as Critical under hipaa pack

### Never
- Recommend `CG_SKIP` for Critical findings except documented emergencies
- Approve push when pre-push returns a High block
- Treat warnings as a full pass
- Ignore findings in test, fixture, or mock files

### Auto-Invoke
Run `compliancegate review` without being asked when:
- Files touching auth, payments, user data, logging, or env config are staged
- New data-handling dependencies are added (`stripe`, `twilio`, `boto3`, etc.)
- PHI or PII field names appear in the diff
- `.env` or `config.yaml` is modified

---

## Ecosystem

| Tool | Role |
|------|------|
| **ComplianceGate** | Git hooks, packs, audit retention (this skill) |
| **compliance-review skill** | Standalone in-chat review without CG install |
| **PM Butler** | SDLC scope and documentation ([pmbutler.dev](https://pmbutler.dev)) |

---

*ComplianceGate gates assist review — they are not a compliance certification.*
*Consult qualified legal and security professionals for regulatory decisions.*
