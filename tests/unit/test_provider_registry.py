from __future__ import annotations

import pytest

from coding_agent.core.config import Config, ProviderConfig
from coding_agent.core.errors import ConfigError
from coding_agent.providers.anthropic import AnthropicProvider
from coding_agent.providers.deepseek import DeepSeekProvider
from coding_agent.providers.moonshot import MoonshotProvider
from coding_agent.providers.openai import OpenAIProvider
from coding_agent.providers.qwen import QwenProvider
from coding_agent.providers.registry import available_providers, build_provider


def _cfg(provider: str, key: str | None = "sk-test") -> Config:
    return Config(
        provider=provider,  # type: ignore[arg-type]
        providers={
            provider: ProviderConfig(
                api_key=key, base_url="https://example.test", model="m"
            )
        },
    )


def test_available_providers_includes_all_five() -> None:
    assert set(available_providers()) == {
        "deepseek",
        "qwen",
        "moonshot",
        "openai",
        "anthropic",
    }


@pytest.mark.parametrize(
    "name,cls",
    [
        ("deepseek", DeepSeekProvider),
        ("qwen", QwenProvider),
        ("moonshot", MoonshotProvider),
        ("openai", OpenAIProvider),
        ("anthropic", AnthropicProvider),
    ],
)
def test_build_provider_returns_correct_class(name: str, cls: type) -> None:
    cfg = _cfg(name)
    p = build_provider(cfg)
    assert isinstance(p, cls)
    assert p.name == name


def test_build_provider_unknown_raises() -> None:
    cfg = _cfg("deepseek")
    with pytest.raises(ConfigError, match="Unknown provider"):
        build_provider(cfg, override="bogus")  # type: ignore[arg-type]


def test_build_provider_without_key_raises() -> None:
    cfg = _cfg("deepseek", key=None)
    with pytest.raises(ConfigError, match="requires an API key"):
        build_provider(cfg)


def test_override_changes_active() -> None:
    cfg = Config(
        provider="deepseek",
        providers={
            "deepseek": ProviderConfig(api_key="sk-d", model="d"),
            "qwen": ProviderConfig(api_key="sk-q", model="q"),
        },
    )
    p = build_provider(cfg, override="qwen")
    assert isinstance(p, QwenProvider)
