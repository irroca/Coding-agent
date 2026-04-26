"""Configuration loading.

Sources are layered, later wins:
  1. Built-in defaults in this file
  2. ~/.coding_agent/config.yaml (user-level)
  3. <cwd>/.coding_agent/config.yaml (project-level)
  4. Environment variables (incl. .env file in cwd)
  5. CLI flags (handled by typer, passed via .with_overrides)

Pydantic-settings owns env-var binding; YAML layering happens above it.
"""

from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path
from typing import Any, Literal

import yaml
from platformdirs import user_config_dir
from pydantic import BaseModel, Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from coding_agent.core.errors import ConfigError

ProviderName = Literal["deepseek", "qwen", "moonshot", "openai", "anthropic"]


class ProviderConfig(BaseModel):
    api_key: str | None = None
    base_url: str | None = None
    model: str | None = None
    context_window: int = 128_000
    max_output_tokens: int = 8_192
    supports_prompt_cache: bool = False


class PermissionsConfig(BaseModel):
    """High-level permission defaults; full rule DSL lives in security/rules.py."""

    file_read: Literal["allow", "ask", "deny"] = "allow"
    file_write: Literal["allow", "ask", "deny"] = "ask"
    bash: Literal["allow", "ask", "deny"] = "ask"
    network: Literal["allow", "ask", "deny"] = "ask"
    rules_file: Path | None = None
    """Optional path to a YAML file containing the full rule list."""


class AgentConfig(BaseModel):
    max_iterations: int = 50
    """Hard cap on Agent loop turns per user message — last-resort safety net."""

    parallel_tool_calls: bool = True
    compact_threshold: float = 0.85
    """Fraction of context window that triggers compaction."""

    keep_recent_turns: int = 6
    """Turns kept verbatim during compaction; older ones get summarized."""

    tool_output_max_chars: int = 30_000
    """Per-tool-result truncation budget."""


class UIConfig(BaseModel):
    theme: Literal["dark", "light"] = "dark"
    show_token_usage: bool = True
    show_cost: bool = True
    markdown: bool = True


class Config(BaseSettings):
    """Top-level configuration."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        env_prefix="CODING_AGENT_",
        env_nested_delimiter="__",
        extra="ignore",
    )

    provider: ProviderName = "deepseek"
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR"] = "INFO"
    workspace: Path = Field(default_factory=Path.cwd)

    providers: dict[str, ProviderConfig] = Field(default_factory=dict)
    permissions: PermissionsConfig = Field(default_factory=PermissionsConfig)
    agent: AgentConfig = Field(default_factory=AgentConfig)
    ui: UIConfig = Field(default_factory=UIConfig)

    @model_validator(mode="after")
    def _hydrate_providers_from_env(self) -> Config:
        """Backfill provider configs from well-known env vars when YAML is silent."""
        env_map: dict[str, dict[str, str]] = {
            "deepseek": {
                "api_key": "DEEPSEEK_API_KEY",
                "base_url": "DEEPSEEK_BASE_URL",
                "model": "DEEPSEEK_MODEL",
            },
            "qwen": {
                "api_key": "DASHSCOPE_API_KEY",
                "base_url": "DASHSCOPE_BASE_URL",
                "model": "DASHSCOPE_MODEL",
            },
            "moonshot": {
                "api_key": "MOONSHOT_API_KEY",
                "base_url": "MOONSHOT_BASE_URL",
                "model": "MOONSHOT_MODEL",
            },
            "openai": {
                "api_key": "OPENAI_API_KEY",
                "base_url": "OPENAI_BASE_URL",
                "model": "OPENAI_MODEL",
            },
            "anthropic": {
                "api_key": "ANTHROPIC_API_KEY",
                "base_url": "ANTHROPIC_BASE_URL",
                "model": "ANTHROPIC_MODEL",
            },
        }
        defaults = {
            "deepseek": {"base_url": "https://api.deepseek.com", "model": "deepseek-chat"},
            "qwen": {
                "base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1",
                "model": "qwen3-coder-plus",
            },
            "moonshot": {"base_url": "https://api.moonshot.cn/v1", "model": "kimi-k2-0905-preview"},
            "openai": {"base_url": "https://api.openai.com/v1", "model": "gpt-4o-mini"},
            "anthropic": {
                "base_url": "https://api.anthropic.com",
                "model": "claude-sonnet-4-6",
            },
        }
        for name, mapping in env_map.items():
            existing = self.providers.get(name, ProviderConfig())
            for field, env_key in mapping.items():
                if getattr(existing, field) is None:
                    val = os.getenv(env_key)
                    if val:
                        setattr(existing, field, val)
            for field, default in defaults[name].items():
                if getattr(existing, field) is None:
                    setattr(existing, field, default)
            self.providers[name] = existing
        return self

    def active_provider(self) -> ProviderConfig:
        cfg = self.providers.get(self.provider)
        if cfg is None or not cfg.api_key:
            raise ConfigError(
                f"Provider '{self.provider}' is not configured. "
                f"Set the corresponding API key (e.g. DEEPSEEK_API_KEY) "
                f"in your environment or .env file."
            )
        return cfg


def _load_dotenv(workspace: Path) -> None:
    """Load .env file into os.environ so non-prefixed keys are visible."""
    env_path = workspace / ".env"
    if not env_path.is_file():
        return
    from dotenv import load_dotenv

    load_dotenv(env_path, override=False)


def _load_yaml(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {}
    try:
        loaded = yaml.safe_load(path.read_text(encoding="utf-8"))
    except yaml.YAMLError as e:
        raise ConfigError(f"Failed to parse config file {path}: {e}") from e
    return loaded or {}


def _deep_merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    out = dict(base)
    for k, v in override.items():
        if k in out and isinstance(out[k], dict) and isinstance(v, dict):
            out[k] = _deep_merge(out[k], v)
        else:
            out[k] = v
    return out


@lru_cache(maxsize=1)
def load_config(workspace: Path | None = None) -> Config:
    """Load configuration with YAML layering applied on top of env vars."""
    workspace = (workspace or Path.cwd()).resolve()

    # Load .env into os.environ so that provider-specific keys
    # (e.g. DEEPSEEK_API_KEY) are visible to os.getenv() in
    # _hydrate_providers_from_env. pydantic-settings only maps
    # env_prefix-matched vars to Config fields, not to os.environ.
    _load_dotenv(workspace)

    user_yaml = _load_yaml(Path(user_config_dir("coding_agent")) / "config.yaml")
    project_yaml = _load_yaml(workspace / ".coding_agent" / "config.yaml")
    merged = _deep_merge(user_yaml, project_yaml)
    if "workspace" not in merged:
        merged["workspace"] = str(workspace)
    return Config(**merged)


def reset_config_cache() -> None:
    load_config.cache_clear()
