from __future__ import annotations

import json
from typing import Any

from compliancegate.config import HarnessConfig, get_api_key
from compliancegate.llm import LLMClient

REASONING_SYSTEM = """You are ComplianceGate's reasoning layer — a senior governance reviewer for AI-assisted software development.

Your job is deep analysis, not formatting. For each enabled rule pack:
- Map changes to pack rules and frameworks
- Identify security, privacy, auth, and regulatory gaps
- Assess severity (low | medium | high | critical) with justification
- Cite file paths and line hints when visible in the diff
- Note false-positive risks and what context is missing

Write clear prose with sections: Summary, Pack-by-pack analysis, Severity assessment, Recommended actions.
Do NOT output JSON."""

ANALYTICAL_SYSTEM = """You are ComplianceGate's analytical layer — a compliance analyst that produces audit-ready structured output.

You receive:
1) Enabled rule packs and their rules
2) A reasoning review from the reasoning layer
3) The underlying diff context summary

Convert supported reasoning into ONLY valid JSON:
{
  "verdict": "pass" | "warn" | "fail",
  "reasoning": "overall assessment in 2-4 sentences",
  "findings": [
    {
      "severity": "low" | "medium" | "high" | "critical",
      "category": "security" | "privacy" | "auth" | "data-retention" | "licensing" | "general",
      "framework": "SOC2" | "GDPR" | "HIPAA" | "PCI-DSS" | "internal" | "",
      "title": "short title",
      "description": "what was found and why it matters",
      "file_path": "path if applicable",
      "line_hint": "line number or range if applicable",
      "recommendation": "specific remediation"
    }
  ]
}

Rules:
- Do not invent findings absent from the reasoning review
- If reasoning found no issues, return verdict "pass" with empty findings
- Prefer pack framework tags when assigning framework field"""


def is_langchain_available() -> bool:
    try:
        import langchain_core  # noqa: F401
        import langchain_openai  # noqa: F401
        return True
    except ImportError:
        return False


def run_langchain_review(
    config: HarnessConfig,
    diff_text: str,
    frameworks: list[str],
    custom_rules: list[str],
    trigger: str,
    prior_decisions: list[dict] | None,
    pack_context: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    if not is_langchain_available():
        return LLMClient(config)._fallback_response(
            "LangChain pipeline enabled but dependencies missing. "
            "Install with: pip install 'compliancegate[langchain]'",
            include_finding=False,
        )

    api_key = get_api_key(config)
    if not api_key:
        return LLMClient(config)._fallback_response(
            f"No API key in env var {config.llm.api_key_env}. Running heuristic-only review.",
            include_finding=False,
        )

    try:
        pipeline = LangChainReviewPipeline(config)
        return pipeline.review(
            diff_text=diff_text,
            frameworks=frameworks,
            custom_rules=custom_rules,
            trigger=trigger,
            prior_decisions=prior_decisions,
            pack_context=pack_context or [],
        )
    except Exception as exc:
        return LLMClient(config)._fallback_response(f"LangChain pipeline failed: {exc}")


class LangChainReviewPipeline:
    def __init__(self, config: HarnessConfig):
        self.config = config
        self._client = LLMClient(config)

    def review(
        self,
        diff_text: str,
        frameworks: list[str],
        custom_rules: list[str],
        trigger: str,
        prior_decisions: list[dict] | None,
        pack_context: list[dict[str, Any]],
    ) -> dict[str, Any]:
        from langchain_core.output_parsers import StrOutputParser
        from langchain_core.prompts import ChatPromptTemplate

        pack_block = _format_pack_context(pack_context)
        context = _format_review_context(
            diff_text, frameworks, custom_rules, trigger, prior_decisions, pack_block
        )

        reasoning_llm = _build_stage_llm(self.config, self.config.langchain.reasoning)
        analytical_llm = _build_stage_llm(
            self.config, self.config.langchain.analytical, json_mode=self.config.llm.json_mode
        )

        reasoning_prompt = ChatPromptTemplate.from_messages([
            ("system", REASONING_SYSTEM),
            ("human", "{context}"),
        ])
        analytical_prompt = ChatPromptTemplate.from_messages([
            ("system", ANALYTICAL_SYSTEM),
            ("human", "{context}"),
        ])

        reasoning_chain = reasoning_prompt | reasoning_llm | StrOutputParser()
        analytical_chain = analytical_prompt | analytical_llm | StrOutputParser()

        reasoning_pass = reasoning_chain.invoke({"context": context})

        analytical_context = (
            f"Review trigger: {trigger}\n"
            f"Frameworks: {', '.join(frameworks) or 'none'}\n\n"
            f"{pack_block}\n\n"
            f"--- REASONING LAYER OUTPUT ---\n{reasoning_pass}\n\n"
            f"--- DIFF EXCERPT ---\n{diff_text[:12000] or '(no diff)'}"
        )
        analytical_raw = analytical_chain.invoke({"context": analytical_context})

        parsed = self._client._parse_json(analytical_raw)
        parsed["pipeline"] = "langchain"
        parsed["reasoning_model"] = self.config.langchain.reasoning.model
        parsed["analytical_model"] = self.config.langchain.analytical.model
        parsed["reasoning_pass"] = reasoning_pass[:8000]
        if not parsed.get("reasoning"):
            parsed["reasoning"] = _summarize_reasoning_pass(reasoning_pass)
        return parsed

    def probe(self) -> dict[str, Any]:
        return self.review(
            diff_text="+# compliancegate langchain connectivity probe\n+# no secrets in probe diff",
            frameworks=["internal"],
            custom_rules=["Probe rule — flag hardcoded secrets"],
            trigger="probe",
            prior_decisions=None,
            pack_context=[{
                "id": "base",
                "name": "Base Security",
                "sensitive": False,
                "frameworks": ["internal"],
                "rules": ["No hardcoded secrets in source"],
            }],
        )


def _format_pack_context(pack_context: list[dict[str, Any]]) -> str:
    if not pack_context:
        return "Enabled rule packs: none"
    lines = ["Enabled rule packs:"]
    for pack in pack_context:
        sensitive = "SENSITIVE" if pack.get("sensitive") else "safe"
        lines.append(f"\n## {pack.get('name')} ({pack.get('id')}) [{sensitive}]")
        fws = pack.get("frameworks") or []
        if fws:
            lines.append(f"Frameworks: {', '.join(fws)}")
        for rule in pack.get("rules") or []:
            lines.append(f"- {rule}")
    return "\n".join(lines)


def _format_review_context(
    diff_text: str,
    frameworks: list[str],
    custom_rules: list[str],
    trigger: str,
    prior_decisions: list[dict] | None,
    pack_block: str,
) -> str:
    parts = [
        f"Review trigger: {trigger}",
        f"Compliance frameworks: {', '.join(frameworks) or 'none'}",
        pack_block,
    ]
    if custom_rules:
        parts.append("Additional custom rules:\n" + "\n".join(f"- {r}" for r in custom_rules))
    if prior_decisions:
        parts.append("Prior decisions this session:\n" + json.dumps(prior_decisions, indent=2))
    parts.append("--- DIFF / CHANGES ---")
    parts.append(diff_text[:50000] or "(no diff provided)")
    return "\n\n".join(parts)


def _summarize_reasoning_pass(reasoning_pass: str) -> str:
    line = reasoning_pass.strip().splitlines()[0] if reasoning_pass.strip() else ""
    if len(line) > 280:
        return line[:277] + "..."
    return line or "LangChain two-stage review completed."


def _api_base_url(config: HarnessConfig) -> str:
    url = config.llm.api_url.rstrip("/")
    if url.endswith("/chat/completions"):
        return url[: -len("/chat/completions")]
    return url


def _build_stage_llm(config: HarnessConfig, stage, json_mode: bool = False):
    from langchain_openai import ChatOpenAI

    api_key = get_api_key(config)
    if not api_key:
        raise ValueError(f"Missing API key env var: {config.llm.api_key_env}")

    kwargs: dict[str, Any] = {
        "model": stage.model,
        "temperature": stage.temperature,
        "timeout": config.llm.timeout_seconds,
        "max_retries": 1,
        "openai_api_key": api_key,
    }

    if config.llm.provider == "ollama":
        kwargs["openai_api_base"] = config.llm.ollama_url.replace("/api/chat", "/v1")
    else:
        kwargs["openai_api_base"] = _api_base_url(config)

    if config.llm.provider == "openrouter":
        kwargs["default_headers"] = {
            "HTTP-Referer": config.llm.site_url,
            "X-OpenRouter-Title": config.llm.app_title,
        }

    if json_mode and config.llm.provider in ("openrouter", "openai"):
        kwargs["model_kwargs"] = {"response_format": {"type": "json_object"}}

    return ChatOpenAI(**kwargs)


def describe_langchain_pipeline(config: HarnessConfig) -> str:
    lc = config.langchain
    if not lc.enabled:
        return "disabled (single-pass LLM)"
    return (
        f"langchain: {lc.reasoning.model} (reasoning) → "
        f"{lc.analytical.model} (analytical)"
    )
