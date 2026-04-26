"""Provider registry — maps a provider name to its implementation."""

from __future__ import annotations

from coding_agent.core.config import Config, ProviderName
from coding_agent.core.errors import ConfigError
from coding_agent.providers.anthropic import AnthropicProvider
from coding_agent.providers.base import LLMProvider
from coding_agent.providers.deepseek import DeepSeekProvider
from coding_agent.providers.moonshot import MoonshotProvider
from coding_agent.providers.openai import OpenAIProvider
from coding_agent.providers.qwen import QwenProvider

_REGISTRY: dict[str, type[LLMProvider]] = {
    "deepseek": DeepSeekProvider,
    "qwen": QwenProvider,
    "moonshot": MoonshotProvider,
    "openai": OpenAIProvider,
    "anthropic": AnthropicProvider,
}


def build_provider(config: Config, override: ProviderName | None = None) -> LLMProvider:
    name = override or config.provider
    cls = _REGISTRY.get(name)
    if cls is None:
        raise ConfigError(
            f"Unknown provider '{name}'. Available: {sorted(_REGISTRY)}"
        )
    provider_cfg = config.providers.get(name)
    if provider_cfg is None:
        raise ConfigError(f"Provider '{name}' has no configuration entry.")
    return cls(provider_cfg)


def available_providers() -> list[str]:
    return sorted(_REGISTRY)
