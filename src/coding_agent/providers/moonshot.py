"""Moonshot Kimi (OpenAI-compatible) adapter."""

from __future__ import annotations

from coding_agent.providers.openai_compat import OpenAICompatProvider


class MoonshotProvider(OpenAICompatProvider):
    name = "moonshot"
    default_base_url = "https://api.moonshot.cn/v1"
    default_model = "kimi-k2-0905-preview"
    supports_stream_usage = True
