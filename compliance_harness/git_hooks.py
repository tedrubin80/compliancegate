from __future__ import annotations

import os
import shutil
import stat
import subprocess
import sys
from pathlib import Path

HOOK_PRE_COMMIT = """#!/usr/bin/env bash
# Compliance Review Harness — pre-commit gate
set -euo pipefail

CRH_CMD="${CRH_CMD:-}"
if [[ -z "$CRH_CMD" ]]; then
  if [[ -x ".venv/bin/crh" ]]; then
    CRH_CMD=".venv/bin/crh"
  elif command -v crh &>/dev/null; then
    CRH_CMD="crh"
  else
    CRH_CMD="python3 -m compliance_harness.cli"
  fi
fi

if [[ -n "${CRH_SKIP:-}" ]]; then
  echo "[crh] CRH_SKIP set — bypassing pre-commit"
  exit 0
fi

echo "[crh] Running pre-commit compliance review..."
if ! $CRH_CMD pre-commit; then
  echo "[crh] COMMIT BLOCKED — resolve compliance findings or override with CRH_SKIP=1"
  exit 1
fi
"""

HOOK_PRE_PUSH = """#!/usr/bin/env bash
# Compliance Review Harness — pre-push gate + loopback review
set -euo pipefail

CRH_CMD="${CRH_CMD:-}"
if [[ -z "$CRH_CMD" ]]; then
  if [[ -x ".venv/bin/crh" ]]; then
    CRH_CMD=".venv/bin/crh"
  elif command -v crh &>/dev/null; then
    CRH_CMD="crh"
  else
    CRH_CMD="python3 -m compliance_harness.cli"
  fi
fi

if [[ -n "${CRH_SKIP:-}" ]]; then
  echo "[crh] CRH_SKIP set — bypassing pre-push"
  exit 0
fi

echo "[crh] Running pre-push compliance review + loopback..."
if ! $CRH_CMD pre-push; then
  echo "[crh] PUSH BLOCKED — resolve compliance findings or override with CRH_SKIP=1"
  exit 1
fi
"""


def install_hooks(repo_root: Path, harness_root: Path) -> None:
    git_dir = repo_root / ".git"
    if not git_dir.exists():
        raise FileNotFoundError(f"No .git directory at {repo_root}")

    hooks_dir = git_dir / "hooks"
    hooks_dir.mkdir(exist_ok=True)

    for name, content in (("pre-commit", HOOK_PRE_COMMIT), ("pre-push", HOOK_PRE_PUSH)):
        hook_path = hooks_dir / name
        hook_path.write_text(content)
        hook_path.chmod(hook_path.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
        print(f"Installed {hook_path}")

    compliance_dir = repo_root / ".compliance"
    compliance_dir.mkdir(exist_ok=True)

    config_dst = repo_root / "config.yaml"
    config_src = harness_root / "config.example.yaml"
    if not config_dst.exists() and config_src.exists():
        shutil.copy(config_src, config_dst)
        print(f"Created {config_dst} from example — edit before use.")

    print("\nHooks installed. Set CRH_SKIP=1 to bypass in emergencies (logged).")


def init_project(repo_root: Path, harness_root: Path) -> None:
    (repo_root / ".compliance" / "data").mkdir(parents=True, exist_ok=True)
    (repo_root / ".compliance" / "reports").mkdir(parents=True, exist_ok=True)

    gitignore = repo_root / ".gitignore"
    entries = [".compliance/data/", ".compliance/reports/"]
    if gitignore.exists():
        content = gitignore.read_text()
        with gitignore.open("a") as f:
            for e in entries:
                if e not in content:
                    f.write(f"\n{e}")
    else:
        gitignore.write_text("\n".join(entries) + "\n")

    install_hooks(repo_root, harness_root)
    print(f"Initialized compliance harness in {repo_root}")
