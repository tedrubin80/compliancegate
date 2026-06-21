from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml


@dataclass
class LLMConfig:
    provider: str = "openai"
    api_url: str = "https://api.openai.com/v1/chat/completions"
    api_key_env: str = "OPENAI_API_KEY"
    model: str = "gpt-4o-mini"
    ollama_url: str = "http://localhost:11434/api/chat"
    ollama_model: str = "llama3.2"
    timeout_seconds: int = 120


@dataclass
class StorageConfig:
    sqlite_path: str = ".compliance/data/compliance.db"
    markdown_dir: str = ".compliance/reports"


@dataclass
class RemoteBackendConfig:
    enabled: bool = False
    url_env: str = ""


@dataclass
class RetentionConfig:
    sync_on_review: bool = True
    postgres: RemoteBackendConfig = field(
        default_factory=lambda: RemoteBackendConfig(enabled=False, url_env="CRH_POSTGRES_URL")
    )
    mysql: RemoteBackendConfig = field(
        default_factory=lambda: RemoteBackendConfig(enabled=False, url_env="CRH_MYSQL_URL")
    )


@dataclass
class ComplianceConfig:
    frameworks: list[str] = field(default_factory=lambda: ["SOC2", "GDPR"])
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
    compliance: ComplianceConfig = field(default_factory=ComplianceConfig)
    watch: WatchConfig = field(default_factory=WatchConfig)
    reporting: ReportingConfig = field(default_factory=ReportingConfig)
    config_path: Path = Path("config.yaml")

    @property
    def sqlite_path(self) -> Path:
        return self.repo_root / self.storage.sqlite_path

    @property
    def markdown_dir(self) -> Path:
        return self.repo_root / self.storage.markdown_dir


SEVERITY_ORDER = {"low": 0, "medium": 1, "high": 2, "critical": 3}


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

    return HarnessConfig(
        project_name=raw.get("project", {}).get("name", repo_root.name),
        repo_root=repo_root,
        storage=StorageConfig(**raw.get("storage", {})),
        retention=RetentionConfig(
            sync_on_review=retention_raw.get("sync_on_review", True),
            postgres=RemoteBackendConfig(
                enabled=postgres_raw.get("enabled", False),
                url_env=postgres_raw.get("url_env", "CRH_POSTGRES_URL"),
            ),
            mysql=RemoteBackendConfig(
                enabled=mysql_raw.get("enabled", False),
                url_env=mysql_raw.get("url_env", "CRH_MYSQL_URL"),
            ),
        ),
        llm=LLMConfig(**raw.get("llm", {})),
        compliance=ComplianceConfig(**raw.get("compliance", {})),
        watch=WatchConfig(**raw.get("watch", {})),
        reporting=ReportingConfig(**raw.get("reporting", {})),
        config_path=config_path,
    )


def _find_config() -> Path:
    for candidate in (Path("config.yaml"), Path(".compliance/config.yaml")):
        if candidate.exists():
            return candidate.resolve()
    return Path("config.yaml").resolve()


def severity_at_or_above(severity: str, threshold: str) -> bool:
    return SEVERITY_ORDER.get(severity.lower(), 0) >= SEVERITY_ORDER.get(threshold.lower(), 99)


def get_api_key(cfg: HarnessConfig) -> str | None:
    return os.environ.get(cfg.llm.api_key_env)
