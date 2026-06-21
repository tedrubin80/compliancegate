from __future__ import annotations

import json
import re
from typing import Any

import httpx

from compliancegate.config import HarnessConfig, get_api_key
from compliancegate.sanitize import sanitize_for_llm

OPENROUTER_MODELS_URL = "https://openrouter.ai/api/v1/models"

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
        pack_context: list[dict] | None = None,
    ) -> dict[str, Any]:
        if self.config.llm.redact_before_send:
            diff_text = sanitize_for_llm(diff_text, True)

        if self.config.langchain.enabled:
            from compliancegate.langchain_pipeline import run_langchain_review
            return run_langchain_review(
                self.config,
                diff_text=diff_text,
                frameworks=frameworks,
                custom_rules=custom_rules,
                trigger=trigger,
                prior_decisions=prior_decisions,
                pack_context=pack_context,
            )

        user_content = self._build_prompt(diff_text, frameworks, custom_rules, trigger, prior_decisions)

        if self.config.llm.provider == "ollama":
            return self._call_ollama(user_content)
        return self._call_chat_completions(user_content)

    def probe(self) -> dict[str, Any]:
        """Lightweight connectivity check for configured provider."""
        if self.config.langchain.enabled:
            from compliancegate.langchain_pipeline import (
                LangChainReviewPipeline,
                is_langchain_available,
            )
            if not is_langchain_available():
                return self._fallback_response(
                    "LangChain pipeline enabled but dependencies missing. "
                    "Install with: pip install 'compliancegate[langchain]'",
                    include_finding=False,
                )
            try:
                return LangChainReviewPipeline(self.config).probe()
            except Exception as exc:
                return self._fallback_response(f"LangChain probe failed: {exc}")

        prompt = (
            'Reply with JSON only: {"verdict":"pass","reasoning":"probe ok","findings":[]}'
        )
        if self.config.llm.provider == "ollama":
            return self._call_ollama(prompt)
        return self._call_chat_completions(prompt, json_mode=True)

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
            f"Compliance frameworks: {', '.join(frameworks) or 'none'}",
        ]
        if custom_rules:
            parts.append("Custom rules:\n" + "\n".join(f"- {r}" for r in custom_rules))
        if prior_decisions:
            parts.append("Prior decisions this session:\n" + json.dumps(prior_decisions, indent=2))
        parts.append("--- DIFF / CHANGES ---")
        parts.append(diff_text[:50000] or "(no diff provided)")
        return "\n\n".join(parts)

    def _call_chat_completions(self, user_content: str, json_mode: bool | None = None) -> dict[str, Any]:
        api_key = get_api_key(self.config)
        if not api_key:
            return self._fallback_response(
                f"No API key in env var {self.config.llm.api_key_env}. Running heuristic-only review.",
                include_finding=False,
            )

        use_json = self.config.llm.json_mode if json_mode is None else json_mode
        headers = self._chat_headers(api_key)
        payload = self._chat_payload(user_content, use_json)

        try:
            content = self._post_chat(headers, payload)
            return self._parse_json(content)
        except httpx.HTTPStatusError as exc:
            if use_json and exc.response.status_code in (400, 422):
                payload = self._chat_payload(user_content, False)
                try:
                    content = self._post_chat(headers, payload)
                    return self._parse_json(content)
                except httpx.HTTPError as retry_exc:
                    return self._fallback_response(f"LLM request failed: {retry_exc}")
            return self._fallback_response(f"LLM request failed: {exc}")
        except httpx.HTTPError as exc:
            return self._fallback_response(f"LLM request failed: {exc}")

    def _chat_headers(self, api_key: str) -> dict[str, str]:
        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        }
        if self.config.llm.provider == "openrouter":
            if self.config.llm.site_url:
                headers["HTTP-Referer"] = self.config.llm.site_url
            if self.config.llm.app_title:
                headers["X-OpenRouter-Title"] = self.config.llm.app_title
        return headers

    def _chat_payload(self, user_content: str, json_mode: bool) -> dict[str, Any]:
        messages = [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user_content},
        ]
        payload: dict[str, Any] = {
            "messages": messages,
            "temperature": 0.1,
        }

        fallbacks = [m for m in self.config.llm.fallback_models if m and m != self.config.llm.model]
        if self.config.llm.provider == "openrouter" and fallbacks:
            payload["models"] = [self.config.llm.model, *fallbacks]
        else:
            payload["model"] = self.config.llm.model

        if json_mode:
            payload["response_format"] = {"type": "json_object"}

        return payload

    def _post_chat(self, headers: dict[str, str], payload: dict[str, Any]) -> str:
        with httpx.Client(timeout=self.config.llm.timeout_seconds) as client:
            resp = client.post(self.config.llm.api_url, headers=headers, json=payload)
            resp.raise_for_status()
            data = resp.json()
            return data["choices"][0]["message"]["content"]

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
        try:
            with httpx.Client(timeout=self.config.llm.timeout_seconds) as client:
                resp = client.post(self.config.llm.ollama_url, json=payload)
                resp.raise_for_status()
                content = resp.json()["message"]["content"]
                return self._parse_json(content)
        except httpx.HTTPError as exc:
            return self._fallback_response(f"Ollama request failed: {exc}")

    def _parse_json(self, content: str) -> dict[str, Any]:
        cleaned = content.strip()
        if cleaned.startswith("```"):
            cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned)
            cleaned = re.sub(r"\s*```$", "", cleaned)

        try:
            data = json.loads(cleaned)
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


def fetch_openrouter_models(api_key: str | None = None, timeout: int = 30) -> list[dict[str, Any]]:
    headers: dict[str, str] = {"Content-Type": "application/json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"

    with httpx.Client(timeout=timeout) as client:
        resp = client.get(OPENROUTER_MODELS_URL, headers=headers)
        resp.raise_for_status()
        payload = resp.json()

    models = payload.get("data", payload if isinstance(payload, list) else [])
    out: list[dict[str, Any]] = []
    for item in models:
        if not isinstance(item, dict):
            continue
        out.append({
            "id": item.get("id", ""),
            "name": item.get("name", item.get("id", "")),
            "context_length": item.get("context_length"),
            "pricing": item.get("pricing"),
        })
    return out


def _is_heuristic_excluded(line: str) -> bool:
    """Skip docs, comments, and regex pattern definitions to reduce false positives."""
    stripped = line.strip()
    if not stripped or stripped.startswith("#"):
        return True
    if "(?i)" in stripped and ('"' in stripped or "'" in stripped):
        return True
    if stripped.startswith(("- ", "* ", "| ", "```", "<", ">")):
        return True
    if "eval()" in stripped or "exec()" in stripped:
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
        (r"(?i)\beval\s*\(", "high", "Use of eval() detected", "security"),
        (r"(?i)\bexec\s*\(", "high", "Use of exec() detected", "security"),
        (r"(?i)disable.*ssl|verify\s*=\s*False", "high", "SSL verification disabled", "security"),
    ]
    if extra_patterns:
        for p in extra_patterns:
            patterns.append((p.pattern, p.severity, p.title, p.category))

    for pattern, severity, title, category in patterns:
        if re.search(pattern, scan_text):
            findings.append({
                "severity": severity,
                "category": category,
                "framework": "internal",
                "title": title,
                "description": "Pattern matched in added lines",
                "file_path": "",
                "line_hint": "",
                "recommendation": "Review change against enabled compliance rule packs.",
            })
    return findings
