from __future__ import annotations

import json
import os
from typing import Any

import httpx

from compliancegate.config import HarnessConfig, get_api_key
from compliancegate.sanitize import sanitize_for_llm


SYSTEM_PROMPT = """You are a governance and compliance reviewer for software development.
You analyze code changes, AI-assisted decisions, and diffs for security, privacy, and policy risks.

Respond ONLY with valid JSON in this exact schema:
{
  "verdict": "pass" | "warn" | "fail",
  "reasoning": "overall assessment in 2-4 sentences",
  "findings": [
    {
      "severity": "low" | "medium" | "high" | "critical",
      "category": "security" | "privacy" | "auth" | "data-retention" | "licensing" | "general",
      "framework": "SOC2" | "GDPR" | "HIPAA" | "internal" | "",
      "title": "short title",
      "description": "what was found and why it matters",
      "file_path": "path if applicable",
      "line_hint": "line number or range if applicable",
      "recommendation": "specific remediation"
    }
  ]
}

Be precise. Flag hardcoded secrets, PII exposure, missing auth, unsafe defaults, and regulatory gaps.
If no issues found, return verdict "pass" with an empty findings array."""


class LLMClient:
    def __init__(self, config: HarnessConfig):
        self.config = config

    def review(
        self,
        diff_text: str,
        frameworks: list[str],
        custom_rules: list[str],
        trigger: str,
        prior_decisions: list[dict] | None = None,
    ) -> dict[str, Any]:
        if self.config.llm.redact_before_send:
            diff_text = sanitize_for_llm(diff_text, True)
        user_content = self._build_prompt(diff_text, frameworks, custom_rules, trigger, prior_decisions)

        if self.config.llm.provider == "ollama":
            return self._call_ollama(user_content)
        return self._call_openai_compatible(user_content)

    def _build_prompt(
        self,
        diff_text: str,
        frameworks: list[str],
        custom_rules: list[str],
        trigger: str,
        prior_decisions: list[dict] | None,
    ) -> str:
        parts = [
            f"Review trigger: {trigger}",
            f"Compliance frameworks: {', '.join(frameworks)}",
        ]
        if custom_rules:
            parts.append("Custom rules:\n" + "\n".join(f"- {r}" for r in custom_rules))
        if prior_decisions:
            parts.append("Prior decisions this session:\n" + json.dumps(prior_decisions, indent=2))
        parts.append("--- DIFF / CHANGES ---")
        parts.append(diff_text[:50000] or "(no diff provided)")
        return "\n\n".join(parts)

    def _call_openai_compatible(self, user_content: str) -> dict[str, Any]:
        api_key = get_api_key(self.config)
        if not api_key:
            return self._fallback_response(
                f"No API key in env var {self.config.llm.api_key_env}. Running heuristic-only review.",
                include_finding=False,
            )

        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        }
        payload = {
            "model": self.config.llm.model,
            "messages": [
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": user_content},
            ],
            "temperature": 0.1,
            "response_format": {"type": "json_object"},
        }

        with httpx.Client(timeout=self.config.llm.timeout_seconds) as client:
            resp = client.post(self.config.llm.api_url, headers=headers, json=payload)
            resp.raise_for_status()
            content = resp.json()["choices"][0]["message"]["content"]
            return self._parse_json(content)

    def _call_ollama(self, user_content: str) -> dict[str, Any]:
        payload = {
            "model": self.config.llm.ollama_model,
            "messages": [
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": user_content},
            ],
            "stream": False,
            "format": "json",
        }
        with httpx.Client(timeout=self.config.llm.timeout_seconds) as client:
            resp = client.post(self.config.llm.ollama_url, json=payload)
            resp.raise_for_status()
            content = resp.json()["message"]["content"]
            return self._parse_json(content)

    def _parse_json(self, content: str) -> dict[str, Any]:
        try:
            data = json.loads(content)
            data.setdefault("verdict", "warn")
            data.setdefault("reasoning", "")
            data.setdefault("findings", [])
            return data
        except json.JSONDecodeError:
            return self._fallback_response(f"LLM returned non-JSON: {content[:500]}")

    def _fallback_response(self, reason: str, include_finding: bool = True) -> dict[str, Any]:
        result: dict[str, Any] = {
            "verdict": "warn",
            "reasoning": reason,
            "findings": [],
        }
        if include_finding:
            result["findings"] = [
                {
                    "severity": "medium",
                    "category": "general",
                    "framework": "internal",
                    "title": "LLM review unavailable",
                    "description": reason,
                    "file_path": "",
                    "line_hint": "",
                    "recommendation": "Configure LLM provider or inspect changes manually.",
                }
            ]
        return result


def _is_heuristic_excluded(line: str) -> bool:
    """Skip docs, comments, and regex pattern definitions to reduce false positives."""
    stripped = line.strip()
    if not stripped or stripped.startswith("#"):
        return True
    if "(?i)" in stripped and ('"' in stripped or "'" in stripped):
        return True
    if stripped.startswith(("- ", "* ", "| ", "```")):
        return True
    return False


def heuristic_scan(diff_text: str, extra_patterns: list | None = None) -> list[dict]:
    """Fast local pattern scan — runs even without LLM. Only inspects added lines."""
    findings = []
    added_lines = [
        line[1:] for line in diff_text.splitlines()
        if line.startswith("+") and not line.startswith("+++")
        and not _is_heuristic_excluded(line[1:])
    ]
    scan_text = "\n".join(added_lines)
    if not scan_text.strip():
        return findings

    patterns = [
        (r"(?i)(api[_-]?key|secret|password|token)\s*=\s*['\"][^'\"]{8,}", "critical", "Possible hardcoded secret", "security"),
        (r"(?i)(aws_secret|private_key|BEGIN RSA PRIVATE KEY)", "critical", "Possible credential leak", "security"),
        (r"(?i)eval\s*\(", "high", "Use of eval() detected", "security"),
        (r"(?i)exec\s*\(", "high", "Use of exec() detected", "security"),
        (r"(?i)disable.*ssl|verify\s*=\s*False", "high", "SSL verification disabled", "security"),
    ]
    if extra_patterns:
        for p in extra_patterns:
            patterns.append((p.pattern, p.severity, p.title, p.category))

    import re
    for pattern, severity, title, category in patterns:
        if re.search(pattern, scan_text):
            findings.append({
                "severity": severity,
                "category": category,
                "framework": "internal",
                "title": title,
                "description": f"Pattern matched in added lines",
                "file_path": "",
                "line_hint": "",
                "recommendation": "Review change against enabled compliance rule packs.",
            })
    return findings
