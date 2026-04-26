"""Token counting helpers.

For OpenAI / DeepSeek / Qwen we use ``tiktoken`` with the ``cl100k_base``
encoding as a reasonable approximation. Exact tokenization differs per model
but counts are within ~5% which is good enough for context-budget decisions.

The counter caches the encoding to avoid the ~50 ms per-call overhead.
"""

from __future__ import annotations

from functools import lru_cache

import tiktoken

from coding_agent.core.types import Message, Role


@lru_cache(maxsize=1)
def _encoding() -> tiktoken.Encoding:
    return tiktoken.get_encoding("cl100k_base")


def count_text(text: str) -> int:
    if not text:
        return 0
    return len(_encoding().encode(text, disallowed_special=()))


def count_message(msg: Message) -> int:
    """Approximate per-message token count, including envelope overhead.

    The chat-completions wire format adds ~4 tokens per message for role +
    delimiters; we use that as a flat overhead.
    """
    n = 4
    n += count_text(msg.content)
    if msg.role == Role.ASSISTANT and msg.tool_calls:
        for call in msg.tool_calls:
            n += count_text(call.name)
            n += count_text(str(call.arguments))
            n += 6
    if msg.role == Role.TOOL:
        for result in msg.tool_results:
            n += count_text(result.content)
            n += 4
    return n


def count_messages(messages: list[Message]) -> int:
    return sum(count_message(m) for m in messages) + 2  # priming tokens
