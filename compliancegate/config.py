from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from compliancegate.storage import resolve_storage_mode


@dataclass
class LLMConfig:
    provider: str = "openai"  # openai | openrouter | ollama
    api_url: str = "https://api.openai.com/v1/chat/completions"
    api_key_env: str = "OPENAI_API_KEY"
    model: str = "gpt-4o-mini"
    fallback_models: list[str] = field(default_factory=list)
    ollama_url: str = "http://localhost:11434/api/chat"
    ollama_model: str = "llama3.2"
    timeout_seconds: int = 120
    redact_before_send: bool = True
    json_mode: bool = True
    site_url: str = "https://compliancegate.dev"
    app_title: str = "ComplianceGate"


@dataclass
class LangChainStageConfig:
    model: str = ""
    temperature: float = 0.2


@dataclass
class LangChainConfig:
    enabled: bool = False
    reasoning: LangChainStageConfig = field(default_factory=LangChainStageConfig)
    analytical: LangChainStageConfig = field(default_factory=LangChainStageConfig)


@dataclass
class StorageConfig:
    # sqlite | markdown | remote | sqlite_markdown | all
    mode: str = "sqlite_markdown"
    sqlite_path: str = ".compliancegate/data/compliancegate.db"
    markdown_dir: str = ".compliancegate/reports"
    persist_sqlite: bool = True
    use_markdown: bool = True
    use_remote: bool = False


@dataclass
class RemoteBackendConfig:
    enabled: bool = False
    url_env: str = ""


@dataclass
class RetentionConfig:
    sync_on_review: bool = False
    remote_payload: str = "metadata_only"  # metadata_only | redacted | full
    sync_sensitive_findings: bool = False
    postgres: RemoteBackendConfig = field(
        default_factory=lambda: RemoteBackendConfig(enabled=False, url_env="CG_POSTGRES_URL")
    )
    mysql: RemoteBackendConfig = field(
        default_factory=lambda: RemoteBackendConfig(enabled=False, url_env="CG_MYSQL_URL")
    )


@dataclass
class ComplianceConfig:
    rule_packs: list[str] = field(default_factory=lambda: ["base"])
    rules_dir: str = ""
    frameworks: list[str] = field(default_factory=list)
    block_push_on: str = "high"
    block_commit_on: str = "critical"
    custom_rules: list[str] = field(default_factory=list)


@dataclass
class WatchConfig:
    enabled: bool = True
    debounce_seconds: int = 3
    ignore_patterns: list[str] = field(default_factory=list)


@dataclass
class ReportingConfig:
    session_markdown: bool = True
    daily_markdown: bool = True


@dataclass
class HarnessConfig:
    project_name: str = "unknown"
    repo_root: Path = Path(".")
    storage: StorageConfig = field(default_factory=StorageConfig)
    retention: RetentionConfig = field(default_factory=RetentionConfig)
    llm: LLMConfig = field(default_factory=LLMConfig)
    langchain: LangChainConfig = field(default_factory=LangChainConfig)
    compliance: ComplianceConfig = field(default_factory=ComplianceConfig)
    watch: WatchConfig = field(default_factory=WatchConfig)
    reporting: ReportingConfig = field(default_factory=ReportingConfig)
    config_path: Path = Path("config.yaml")

    @property
    def sqlite_path(self) -> Path | str:
        if self.storage.persist_sqlite:
            return self.repo_root / self.storage.sqlite_path
        # Ephemeral session cache (not audit retention) for markdown/remote modes
        return self.repo_root / ".compliancegate/.session.db"

    @property
    def markdown_dir(self) -> Path:
        return self.repo_root / self.storage.markdown_dir

    @property
    def rules_dir(self) -> Path:
        if self.compliance.rules_dir:
            return (self.repo_root / self.compliance.rules_dir).resolve()
        from compliancegate.rules.loader import RULES_DIR
        return RULES_DIR


SEVERITY_ORDER = {"low": 0, "medium": 1, "high": 2, "critical": 3}

LLM_PROVIDER_DEFAULTS = {
    "openai": {
        "api_url": "https://api.openai.com/v1/chat/completions",
        "api_key_env": "OPENAI_API_KEY",
        "model": "gpt-4o-mini",
    },
    "openrouter": {
        "api_url": "https://openrouter.ai/api/v1/chat/completions",
        "api_key_env": "OPENROUTER_API_KEY",
        "model": "anthropic/claude-3.5-sonnet",
    },
}


def build_llm_config(llm_raw: dict[str, Any]) -> LLMConfig:
    provider = str(llm_raw.get("provider", "openai")).lower()
    defaults = LLM_PROVIDER_DEFAULTS.get(provider, LLM_PROVIDER_DEFAULTS["openai"])

    return LLMConfig(
        provider=provider,
        api_url=llm_raw.get("api_url", defaults["api_url"]),
        api_key_env=llm_raw.get("api_key_env", defaults["api_key_env"]),
        model=llm_raw.get("model", defaults["model"]),
        fallback_models=list(llm_raw.get("fallback_models", [])),
        ollama_url=llm_raw.get("ollama_url", "http://localhost:11434/api/chat"),
        ollama_model=llm_raw.get("ollama_model", "llama3.2"),
        timeout_seconds=int(llm_raw.get("timeout_seconds", 120)),
        redact_before_send=bool(llm_raw.get("redact_before_send", True)),
        json_mode=bool(llm_raw.get("json_mode", True)),
        site_url=llm_raw.get("site_url", "https://compliancegate.dev"),
        app_title=llm_raw.get("app_title", "ComplianceGate"),
    )


def build_langchain_config(raw: dict[str, Any], llm: LLMConfig) -> LangChainConfig:
    if not raw:
        return LangChainConfig()

    reasoning_raw = raw.get("reasoning", {}) or {}
    analytical_raw = raw.get("analytical", {}) or {}

    if llm.provider == "openrouter":
        default_reasoning = "anthropic/claude-3.5-sonnet"
        default_analytical = "openai/gpt-4o-mini"
    elif llm.provider == "openai":
        default_reasoning = "gpt-4o"
        default_analytical = "gpt-4o-mini"
    else:
        default_reasoning = llm.model or llm.ollama_model
        default_analytical = llm.model or llm.ollama_model

    return LangChainConfig(
        enabled=bool(raw.get("enabled", False)),
        reasoning=LangChainStageConfig(
            model=str(reasoning_raw.get("model") or default_reasoning),
            temperature=float(reasoning_raw.get("temperature", 0.3)),
        ),
        analytical=LangChainStageConfig(
            model=str(analytical_raw.get("model") or default_analytical),
            temperature=float(analytical_raw.get("temperature", 0.1)),
        ),
    )


def load_config(path: Path | None = None) -> HarnessConfig:
    config_path = path or _find_config()
    if not config_path.exists():
        raise FileNotFoundError(
            f"No config found at {config_path}. Copy config.example.yaml to config.yaml."
        )

    with config_path.open() as f:
        raw: dict[str, Any] = yaml.safe_load(f) or {}

    repo_root = (config_path.parent / raw.get("project", {}).get("repo_root", ".")).resolve()

    retention_raw = raw.get("retention", {})
    postgres_raw = retention_raw.get("postgres", {})
    mysql_raw = retention_raw.get("mysql", {})

    compliance_raw = raw.get("compliance", {})
    llm_raw = raw.get("llm", {})
    langchain_raw = raw.get("langchain", {})
    storage_raw = raw.get("storage", {})

    mode = storage_raw.get("mode", "sqlite_markdown")
    flags = resolve_storage_mode(mode)
    storage = StorageConfig(
        mode=mode,
        sqlite_path=storage_raw.get("sqlite_path", ".compliancegate/data/compliancegate.db"),
        markdown_dir=storage_raw.get("markdown_dir", ".compliancegate/reports"),
        persist_sqlite=flags["persist_sqlite"],
        use_markdown=flags["use_markdown"],
        use_remote=flags["use_remote"],
    )

    sync_on_review = retention_raw.get("sync_on_review")
    if sync_on_review is None:
        sync_on_review = storage.use_remote

    reporting_raw = raw.get("reporting", {})
    reporting = ReportingConfig(
        session_markdown=reporting_raw.get("session_markdown", storage.use_markdown),
        daily_markdown=reporting_raw.get("daily_markdown", storage.use_markdown),
    )

    llm_cfg = build_llm_config(llm_raw)

    return HarnessConfig(
        project_name=raw.get("project", {}).get("name", repo_root.name),
        repo_root=repo_root,
        storage=storage,
        retention=RetentionConfig(
            sync_on_review=sync_on_review,
            remote_payload=retention_raw.get("remote_payload", "metadata_only"),
            sync_sensitive_findings=retention_raw.get("sync_sensitive_findings", False),
            postgres=RemoteBackendConfig(
                enabled=postgres_raw.get("enabled", False),
                url_env=postgres_raw.get("url_env", "CG_POSTGRES_URL"),
            ),
            mysql=RemoteBackendConfig(
                enabled=mysql_raw.get("enabled", False),
                url_env=mysql_raw.get("url_env", "CG_MYSQL_URL"),
            ),
        ),
        llm=llm_cfg,
        langchain=build_langchain_config(langchain_raw, llm_cfg),
        compliance=ComplianceConfig(
            rule_packs=compliance_raw.get("rule_packs", ["base"]),
            rules_dir=compliance_raw.get("rules_dir", ""),
            frameworks=compliance_raw.get("frameworks", []),
            block_push_on=compliance_raw.get("block_push_on", "high"),
            block_commit_on=compliance_raw.get("block_commit_on", "critical"),
            custom_rules=compliance_raw.get("custom_rules", []),
        ),
        watch=WatchConfig(**raw.get("watch", {})),
        reporting=reporting,
        config_path=config_path,
    )


def _find_config() -> Path:
    for candidate in (Path("config.yaml"), Path(".compliancegate/config.yaml")):
        if candidate.exists():
            return candidate.resolve()
    return Path("config.yaml").resolve()


def severity_at_or_above(severity: str, threshold: str) -> bool:
    return SEVERITY_ORDER.get(severity.lower(), 0) >= SEVERITY_ORDER.get(threshold.lower(), 99)


def get_api_key(cfg: HarnessConfig) -> str | None:
    return os.environ.get(cfg.llm.api_key_env)
