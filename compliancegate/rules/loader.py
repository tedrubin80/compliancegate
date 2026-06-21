from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml


RULES_DIR = Path(__file__).resolve().parent


@dataclass
class RulePattern:
    pattern: str
    severity: str
    title: str
    category: str = "general"


@dataclass
class RulePack:
    id: str
    name: str
    sensitive: bool = False
    frameworks: list[str] = field(default_factory=list)
    rules: list[str] = field(default_factory=list)
    patterns: list[RulePattern] = field(default_factory=list)


def load_rule_packs(pack_ids: list[str], rules_dir: Path | None = None) -> list[RulePack]:
    base = rules_dir or RULES_DIR
    packs: list[RulePack] = []
    for pack_id in pack_ids:
        path = base / f"{pack_id}.yaml"
        if not path.exists():
            raise FileNotFoundError(f"Rule pack not found: {path}")
        packs.append(_load_pack(path))
    return packs


def merge_packs(packs: list[RulePack]) -> tuple[list[str], list[str], list[RulePattern], bool]:
    """Return (frameworks, rules, patterns, any_sensitive)."""
    frameworks: list[str] = []
    rules: list[str] = []
    patterns: list[RulePattern] = []
    any_sensitive = False

    for pack in packs:
        any_sensitive = any_sensitive or pack.sensitive
        for fw in pack.frameworks:
            if fw not in frameworks:
                frameworks.append(fw)
        rules.extend(pack.rules)
        patterns.extend(pack.patterns)

    return frameworks, rules, patterns, any_sensitive


def list_available_packs(rules_dir: Path | None = None) -> list[dict[str, Any]]:
    base = rules_dir or RULES_DIR
    out: list[dict[str, Any]] = []
    for path in sorted(base.glob("*.yaml")):
        pack = _load_pack(path)
        out.append({
            "id": pack.id,
            "name": pack.name,
            "sensitive": pack.sensitive,
            "frameworks": pack.frameworks,
            "rules": len(pack.rules),
            "patterns": len(pack.patterns),
        })
    return out


def _load_pack(path: Path) -> RulePack:
    with path.open() as f:
        raw = yaml.safe_load(f) or {}
    patterns = [
        RulePattern(
            pattern=p["pattern"],
            severity=p.get("severity", "medium"),
            title=p.get("title", "Pattern match"),
            category=p.get("category", "general"),
        )
        for p in raw.get("patterns", [])
    ]
    return RulePack(
        id=raw.get("id", path.stem),
        name=raw.get("name", path.stem),
        sensitive=bool(raw.get("sensitive", False)),
        frameworks=list(raw.get("frameworks", [])),
        rules=list(raw.get("rules", [])),
        patterns=patterns,
    )
