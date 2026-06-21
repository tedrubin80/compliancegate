#!/usr/bin/env bash
# ComplianceGate (compliancegate.dev) — install into a git repo
set -euo pipefail

HARNESS_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
REPO="."
MODE="sqlite_markdown"
VENV=1
RULE_PACKS="base"

usage() {
  cat <<EOF
Usage: $(basename "$0") [options]

Install ComplianceGate (compliancegate.dev) into a git repository.

Options:
  --repo PATH          Target git repo (default: current directory)
  --mode MODE          Storage mode (default: sqlite_markdown)
  --packs LIST         Comma-separated rule packs (default: base)
  --no-venv            Skip creating .venv in target repo
  -h, --help           Show this help
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --repo) REPO="$2"; shift 2 ;;
    --mode) MODE="$2"; shift 2 ;;
    --packs) RULE_PACKS="$2"; shift 2 ;;
    --no-venv) VENV=0; shift ;;
    -h|--help) usage; exit 0 ;;
    *) echo "Unknown option: $1"; usage; exit 1 ;;
  esac
done

REPO="$(cd "$REPO" && pwd)"

if [[ ! -d "$REPO/.git" ]]; then
  echo "Error: $REPO is not a git repository"
  exit 1
fi

echo "==> Installing ComplianceGate (compliancegate.dev)"
echo "    npx:      npx compliancegate install"
echo "    Source:   $HARNESS_ROOT"
echo "    Repo:     $REPO"
echo "    Storage:  $MODE"

cd "$REPO"

if [[ "$VENV" -eq 1 ]]; then
  [[ -d .venv ]] || python3 -m venv .venv
  # shellcheck disable=SC1091
  source .venv/bin/activate
  pip install -q -e "$HARNESS_ROOT"
  if [[ "$MODE" == "remote" || "$MODE" == "all" ]]; then
    pip install -q -e "$HARNESS_ROOT[postgres,mysql]" 2>/dev/null || true
  fi
else
  pip install -q -e "$HARNESS_ROOT"
fi

CG_CMD="compliancegate"
[[ -x .venv/bin/compliancegate ]] && CG_CMD=".venv/bin/compliancegate"

"$CG_CMD" init --repo "$REPO" --mode "$MODE"

CONFIG="$REPO/config.yaml"
if [[ -f "$CONFIG" ]]; then
  python3 - <<PY
import re
from pathlib import Path
config = Path("$CONFIG")
text = config.read_text()
packs = "$RULE_PACKS".split(",")
block = "  rule_packs:\n" + "".join(f"    - {p.strip()}\n" for p in packs if p.strip())
text = re.sub(r"  rule_packs:\n(?:    - .+\n)+", block, text, count=1)
config.write_text(text)
PY
fi

echo ""
echo "==> Done — https://compliancegate.dev"
"$CG_CMD" status 2>/dev/null || true

SKILLS_SRC="$HARNESS_ROOT/skills/compliancegate"
SKILLS_DEST="$REPO/.cursor/skills/compliancegate"
if [[ -f "$SKILLS_SRC/SKILL.md" ]]; then
  mkdir -p "$SKILLS_DEST"
  cp -a "$SKILLS_SRC/." "$SKILLS_DEST/"
  echo "==> Project skill installed → $SKILLS_DEST"
fi

echo ""
echo "  compliancegate watch"
echo "  npx compliancegate skills install --project   # agent skill (personal)"
echo "  CG_SKIP=1 git commit   # emergency bypass"
