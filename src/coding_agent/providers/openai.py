"""OpenAI native adapter."""

from __future__ import annotations

from coding_agent.providers.openai_compat import OpenAICompatProvider


class OpenAIProvider(OpenAICompatProvider):
    name = "openai"
    default_base_url = "https://api.openai.com/v1"
    default_model = "gpt-4o-mini"
    supports_stream_usage = True
