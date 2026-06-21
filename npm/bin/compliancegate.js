#!/usr/bin/env node

import { checkInstallation, installComplianceGate } from "../lib/install.mjs";
import { checkSkills, installSkill, installSkills, SKILL_IDS } from "../lib/skills.mjs";
import { cgBinary, runCommand } from "../lib/python.mjs";
import { resolve } from "path";

const args = process.argv.slice(2);
const cmd = args[0];

function flagValue(name) {
  const idx = args.indexOf(name);
  if (idx === -1) return undefined;
  return args[idx + 1];
}

function hasFlag(name) {
  return args.includes(name);
}

function usage() {
  console.log(`
compliancegate — npx installer for the Python governance gate (compliancegate.dev)

Install into a git repo (creates .venv, pip install, init, hooks):
  npx compliancegate install
  npx compliancegate install --repo /path/to/project --mode sqlite_markdown --packs base,pii
  npx compliancegate install --langchain

Verify an install:
  npx compliancegate check
  npx compliancegate check --repo /path/to/project

Passthrough to the Python CLI (after install):
  npx compliancegate run status
  npx compliancegate run rules list
  npx compliancegate run watch

Agent skills (Cursor / Claude):
  npx compliancegate skills install
  npx compliancegate skills install --all
  npx compliancegate skills install --all-skills --all
  npx compliancegate skills install --project --repo /path/to/project
  npx compliancegate skills check

Options for install:
  --repo PATH       Target git repo (default: current directory)
  --mode MODE       sqlite | markdown | remote | sqlite_markdown | all
  --packs LIST      Comma-separated rule packs (default: base)
  --source SPEC     pip install source (default: GitHub main)
  --langchain       Also pip install compliancegate[langchain] for two-stage LLM review
  --no-venv         Install with system python3 instead of .venv

Environment:
  CG_INSTALL_SOURCE   Override pip source (path or git+https://...)
`);
}

function runInstall() {
  installComplianceGate({
    repo: flagValue("--repo"),
    mode: flagValue("--mode"),
    packs: flagValue("--packs"),
    source: flagValue("--source"),
    venv: !hasFlag("--no-venv"),
    langchain: hasFlag("--langchain"),
  });
}

function runCheck() {
  const { repo, checks } = checkInstallation(flagValue("--repo"));
  console.log(`ComplianceGate check — ${repo}\n`);
  let failed = 0;
  for (const row of checks) {
    console.log(`${row.ok ? "✓" : "✗"} ${row.name}${row.detail ? `: ${row.detail}` : ""}`);
    if (!row.ok) failed += 1;
  }
  if (failed) {
    console.log(`\n${failed} check(s) failed. Run: npx compliancegate install`);
    process.exitCode = 1;
  } else {
    console.log("\nAll checks passed.");
  }
}

function runPassthrough() {
  const passthrough = args.slice(1);
  if (!passthrough.length) {
    usage();
    process.exitCode = 1;
    return;
  }
  const repo = flagValue("--repo") || process.cwd();
  const cg = cgBinary(repo);
  runCommand(cg, passthrough, { cwd: repo });
}

function runSkillsInstall() {
  const skillArg = hasFlag("--all-skills") ? "all" : (flagValue("--skills") || "compliancegate");
  const installed = [];

  if (hasFlag("--project")) {
    const repo = resolve(flagValue("--repo") || process.cwd());
    const ids = skillArg === "all" ? Object.keys(SKILL_IDS) : skillArg.split(",").map(s => s.trim());
    for (const id of ids) {
      if (!SKILL_IDS[id]) continue;
      const dest = installSkill(id, "project", resolve(repo, ".cursor", "skills", id));
      installed.push({ id, dest });
    }
  } else {
    const harnesses = [];
    if (hasFlag("--all") || hasFlag("--cursor") || (!hasFlag("--claude") && !hasFlag("--cursor"))) {
      harnesses.push("cursor");
    }
    if (hasFlag("--all") || hasFlag("--claude")) {
      harnesses.push("claude");
    }
    for (const harness of [...new Set(harnesses)]) {
      installed.push(...installSkills({ harness, skills: skillArg }));
    }
  }

  console.log("\nInstalled ComplianceGate skill(s):");
  for (const row of installed) {
    console.log(`  ${row.id} → ${row.dest}`);
  }
  console.log("\n  compliancegate       — CG hooks, CLI, audit trail");
  console.log("  compliance-review    — standalone in-chat review (no CG required)");
}

function runSkillsCheck() {
  const harness = hasFlag("--project") ? "project" : (hasFlag("--claude") ? "claude" : "cursor");
  const rows = checkSkills(hasFlag("--all") ? "all" : harness);
  console.log("ComplianceGate skills\n");
  for (const row of rows) {
    console.log(`${row.installed ? "✓" : "✗"} [${row.harness}] ${row.id}: ${row.dest}`);
  }
  const missing = rows.filter(r => !r.installed).length;
  if (missing) {
    console.log(`\n${missing} missing. Run: npx compliancegate skills install`);
    process.exitCode = 1;
  }
}

function main() {
  if (!cmd || cmd === "help" || hasFlag("--help") || hasFlag("-h")) {
    usage();
    return;
  }
  if (cmd === "skills") {
    const sub = args[1];
    if (sub === "install") runSkillsInstall();
    else if (sub === "check") runSkillsCheck();
    else {
      console.error("Usage: npx compliancegate skills install|check\n");
      process.exitCode = 1;
    }
    return;
  }
  if (cmd === "install") runInstall();
  else if (cmd === "check") runCheck();
  else if (cmd === "run") runPassthrough();
  else {
    console.error(`Unknown command: ${cmd}\n`);
    usage();
    process.exitCode = 1;
  }
}

main();
