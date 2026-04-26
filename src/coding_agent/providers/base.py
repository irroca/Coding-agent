"""Provider abstraction layer.

A `LLMProvider` is the only thing the agent core needs to know about the
outside world. It exposes:

  * `stream()` — async iterator of vendor-neutral `StreamEvent`s
  * `count_tokens()` — best-effort token estimate for budget decisions
  * `context_window` / `max_output_tokens` — capability metadata

Provider adapters convert vendor-specific request bodies and SSE chunks into
the canonical types in `coding_agent.core.types`. The core never sees vendor
payloads. This is the boundary that makes the agent vendor-portable.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import AsyncIterator
from typing import TYPE_CHECKING

from coding_agent.core.tokens import count_messages
from coding_agent.core.types import Message, StreamEvent, ToolSchema

if TYPE_CHECKING:
    from coding_agent.core.config import ProviderConfig


class LLMProvider(ABC):
    """Vendor-neutral interface used by the agent loop.

    Concrete adapters live next to this file (`deepseek.py`, `openai.py`,
    `anthropic.py`, …). They MUST yield vendor-neutral `StreamEvent`s with the
    contract described in `core/types.py`:

      1. The first tool-related event for any tool call is `TOOL_USE_START`
         with both `tool_call_id` and `tool_name` set.
      2. Argument fragments arrive as `TOOL_USE_DELTA` carrying
         `arguments_delta` (a JSON-string fragment) and the same `tool_call_id`.
      3. A `TOOL_USE_END` event with the same `tool_call_id` marks the end of
         that tool call's arguments.
      4. `TEXT_DELTA` and tool events may interleave; ordering is preserved.
      5. Exactly one `USAGE` event SHOULD appear before `DONE` when the vendor
         reports token usage. `DONE` carries `finish_reason`.
      6. Errors are surfaced as `ERROR` events; the iterator then ends.

    Adapters are responsible for retries on transient errors and for mapping
    auth / rate-limit failures to `ProviderAuthError` / `ProviderRateLimitError`.
    """

    name: str

    def __init__(self, config: ProviderConfig) -> None:
        if not config.api_key:
            from coding_agent.core.errors import ConfigError

            raise ConfigError(
                f"Provider '{self.name}' requires an API key but none was configured."
            )
        self.config = config

    @abstractmethod
    def stream(
        self,
        messages: list[Message],
        tools: list[ToolSchema],
        *,
        temperature: float | None = None,
        max_tokens: int | None = None,
    ) -> AsyncIterator[StreamEvent]:
        """Stream a single assistant turn. Raises ProviderError on failure."""

    def count_tokens(self, messages: list[Message]) -> int:
        return count_messages(messages)

    @property
    def context_window(self) -> int:
        return self.config.context_window

    @property
    def max_output_tokens(self) -> int:
        return self.config.max_output_tokens

    @property
    def model(self) -> str:
        assert self.config.model is not None
        return self.config.model
