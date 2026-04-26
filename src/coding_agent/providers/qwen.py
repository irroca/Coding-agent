"""Qwen / DashScope OpenAI-compatible adapter."""

from __future__ import annotations

from coding_agent.providers.openai_compat import OpenAICompatProvider


class QwenProvider(OpenAICompatProvider):
    name = "qwen"
    default_base_url = "https://dashscope.aliyuncs.com/compatible-mode/v1"
    default_model = "qwen3-coder-plus"
    supports_stream_usage = True
