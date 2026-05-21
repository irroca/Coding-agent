"""Domain types shared across the agent.

These are the canonical, provider-agnostic shapes. Provider adapters convert
to and from these. The agent loop and tools never touch raw provider payloads.
"""

from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum
from typing import Any, Literal
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field


def _utcnow() -> datetime:
    return datetime.now(UTC)


def _new_id() -> str:
    return uuid4().hex[:16]


class Role(StrEnum):
    SYSTEM = "system"
    USER = "user"
    ASSISTANT = "assistant"
    TOOL = "tool"


class ToolCall(BaseModel):
    """A request from the model to invoke a tool."""

    model_config = ConfigDict(extra="forbid")

    id: str = Field(default_factory=_new_id)
    name: str
    arguments: dict[str, Any]


class ToolResult(BaseModel):
    """The result of a tool invocation, fed back to the model."""

    model_config = ConfigDict(extra="forbid")

    call_id: str
    tool: str
    ok: bool
    content: str
    """Human / model-readable rendering of the result. May be truncated."""

    metadata: dict[str, Any] = Field(default_factory=dict)
    """Structured details (exit code, file path, etc.) — not sent to the model."""


class Message(BaseModel):
    """A canonical chat message."""

    model_config = ConfigDict(extra="forbid")

    role: Role
    content: str = ""
    reasoning_content: str | None = None
    """DeepSeek thinking-mode reasoning trace; must be passed back to the API."""
    tool_calls: list[ToolCall] = Field(default_factory=list)
    """Set when role == assistant and the model requested tool calls."""

    tool_results: list[ToolResult] = Field(default_factory=list)
    """Set when role == tool. Multiple results may be batched in one turn."""

    name: str | None = None
    created_at: datetime = Field(default_factory=_utcnow)


class Usage(BaseModel):
    model_config = ConfigDict(extra="forbid")

    prompt_tokens: int = 0
    completion_tokens: int = 0
    cached_prompt_tokens: int = 0
    """Tokens served from prompt cache (cheap)."""

    cache_creation_tokens: int = 0
    """Tokens written to the cache this turn (Anthropic charges 1.25x, only once)."""

    @property
    def total_tokens(self) -> int:
        return self.prompt_tokens + self.completion_tokens

    @property
    def cache_hit_rate(self) -> float:
        """Fraction of prompt_tokens that were served from cache (0.0-1.0)."""
        if not self.prompt_tokens:
            return 0.0
        return self.cached_prompt_tokens / self.prompt_tokens


class StreamEventType(StrEnum):
    REASONING_DELTA = "reasoning_delta"
    TEXT_DELTA = "text_delta"
    TOOL_USE_START = "tool_use_start"
    TOOL_USE_DELTA = "tool_use_delta"
    TOOL_USE_END = "tool_use_end"
    USAGE = "usage"
    DONE = "done"
    ERROR = "error"


class StreamEvent(BaseModel):
    """Provider-agnostic streaming event.

    The provider layer normalizes vendor SSE chunks into these. Upper layers
    (agent loop, TUI) consume this stream without caring about the vendor.
    """

    model_config = ConfigDict(extra="forbid")

    type: StreamEventType
    text: str | None = None
    tool_call_id: str | None = None
    tool_name: str | None = None
    arguments_delta: str | None = None
    usage: Usage | None = None
    error: str | None = None
    finish_reason: Literal["stop", "tool_calls", "length", "error"] | None = None


class ToolSchema(BaseModel):
    """JSON-Schema description of a tool, sent to the LLM."""

    model_config = ConfigDict(extra="forbid")

    name: str
    description: str
    parameters: dict[str, Any]
