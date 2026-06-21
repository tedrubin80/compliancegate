from __future__ import annotations

import os
import shutil
import stat
import subprocess
import sys
from pathlib import Path

HOOK_PRE_COMMIT = """#!/usr/bin/env bash
# ComplianceGate — pre-commit gate
set -euo pipefail

CG_CMD="${CG_CMD:-}"
if [[ -z "$CG_CMD" ]]; then
  if [[ -x ".venv/bin/compliancegate" ]]; then
    CG_CMD=".venv/bin/compliancegate"
  elif command -v compliancegate &>/dev/null; then
    CG_CMD="compliancegate"
  else
    CG_CMD="python3 -m compliancegate.cli"
  fi
fi

if [[ -n "${CG_SKIP:-}" ]]; then
  echo "[compliancegate] CG_SKIP set — bypassing pre-commit"
  exit 0
fi

echo "[compliancegate] Running pre-commit compliance review..."
if ! $CG_CMD pre-commit; then
  echo "[compliancegate] COMMIT BLOCKED — resolve compliance findings or override with CG_SKIP=1"
  exit 1
fi
"""

HOOK_PRE_PUSH = """#!/usr/bin/env bash
# ComplianceGate — pre-push gate + loopback review
set -euo pipefail

CG_CMD="${CG_CMD:-}"
if [[ -z "$CG_CMD" ]]; then
  if [[ -x ".venv/bin/compliancegate" ]]; then
    CG_CMD=".venv/bin/compliancegate"
  elif command -v compliancegate &>/dev/null; then
    CG_CMD="compliancegate"
  else
    CG_CMD="python3 -m compliancegate.cli"
  fi
fi

if [[ -n "${CG_SKIP:-}" ]]; then
  echo "[compliancegate] CG_SKIP set — bypassing pre-push"
  exit 0
fi

echo "[compliancegate] Running pre-push compliance review + loopback..."
if ! $CG_CMD pre-push; then
  echo "[compliancegate] PUSH BLOCKED — resolve compliance findings or override with CG_SKIP=1"
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

    compliance_dir = repo_root / ".compliancegate"
    compliance_dir.mkdir(exist_ok=True)

    config_dst = repo_root / "config.yaml"
    config_src = harness_root / "config.example.yaml"
    if not config_dst.exists() and config_src.exists():
        shutil.copy(config_src, config_dst)
        print(f"Created {config_dst} from example — edit before use.")

    print("\nHooks installed. Set CG_SKIP=1 to bypass in emergencies (logged).")


def init_project(repo_root: Path, harness_root: Path, storage_mode: str | None = None) -> None:
    from compliancegate.config import load_config
    from compliancegate.storage import resolve_storage_mode

    config_dst = repo_root / "config.yaml"
    config_src = harness_root / "config.example.yaml"
    if not config_dst.exists() and config_src.exists():
        shutil.copy(config_src, config_dst)

    if storage_mode and config_dst.exists():
        _set_config_mode(config_dst, storage_mode)

    try:
        cfg = load_config(config_dst)
        flags = resolve_storage_mode(cfg.storage.mode)
    except Exception:
        flags = resolve_storage_mode(storage_mode or "sqlite_markdown")

    (repo_root / ".compliancegate").mkdir(exist_ok=True)
    if flags["persist_sqlite"]:
        (repo_root / ".compliancegate" / "data").mkdir(parents=True, exist_ok=True)
    if flags["use_markdown"]:
        (repo_root / ".compliancegate" / "reports").mkdir(parents=True, exist_ok=True)

    gitignore = repo_root / ".gitignore"
    entries = [".compliancegate/.session.db"]
    if flags["persist_sqlite"]:
        entries.append(".compliancegate/data/")
    if flags["use_markdown"]:
        entries.append(".compliancegate/reports/")
    if gitignore.exists():
        content = gitignore.read_text()
        with gitignore.open("a") as f:
            for e in entries:
                if e not in content:
                    f.write(f"\n{e}")
    elif entries:
        gitignore.write_text("\n".join(entries) + "\n")

    install_hooks(repo_root, harness_root)
    print(f"Initialized ComplianceGate in {repo_root}")


def _set_config_mode(config_path: Path, mode: str) -> None:
    import re
    text = config_path.read_text()
    if re.search(r"^  mode:\s", text, re.MULTILINE):
        text = re.sub(r"^  mode:\s.*$", f"  mode: {mode}", text, count=1, flags=re.MULTILINE)
    else:
        text = text.replace(
            "storage:\n",
            f"storage:\n  mode: {mode}\n",
            1,
        )
    config_path.write_text(text)
