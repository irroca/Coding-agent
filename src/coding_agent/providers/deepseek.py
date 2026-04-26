"""DeepSeek adapter (OpenAI Chat Completions wire format)."""

from __future__ import annotations

from coding_agent.providers.openai_compat import OpenAICompatProvider


class DeepSeekProvider(OpenAICompatProvider):
    name = "deepseek"
    default_base_url = "https://api.deepseek.com"
    default_model = "deepseek-chat"
    supports_stream_usage = True
