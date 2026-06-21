#!/usr/bin/env node

import { checkInstallation, installComplianceGate } from "../lib/install.mjs";
import { cgBinary, runCommand } from "../lib/python.mjs";

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

Verify an install:
  npx compliancegate check
  npx compliancegate check --repo /path/to/project

Passthrough to the Python CLI (after install):
  npx compliancegate run status
  npx compliancegate run rules list
  npx compliancegate run watch

Options for install:
  --repo PATH       Target git repo (default: current directory)
  --mode MODE       sqlite | markdown | remote | sqlite_markdown | all
  --packs LIST      Comma-separated rule packs (default: base)
  --source SPEC     pip install source (default: GitHub main)
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

function main() {
  if (!cmd || cmd === "help" || hasFlag("--help") || hasFlag("-h")) {
    usage();
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
