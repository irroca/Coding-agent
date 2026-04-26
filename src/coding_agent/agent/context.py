"""Context budget monitoring.

Tracks token usage against the provider's context window and decides
when compaction is needed.
"""

from __future__ import annotations

from dataclasses import dataclass

from coding_agent.core.logging import get_logger
from coding_agent.core.tokens import count_messages
from coding_agent.core.types import Message

log = get_logger("agent.context")


@dataclass
class ContextBudget:
    """Monitors token budget and signals when compaction is needed."""

    context_window: int
    compact_threshold: float = 0.85
    keep_recent_turns: int = 6

    def current_tokens(self, messages: list[Message]) -> int:
        return count_messages(messages)

    def should_compact(self, messages: list[Message]) -> bool:
        used = self.current_tokens(messages)
        limit = int(self.context_window * self.compact_threshold)
        if used > limit:
            log.info(
                "context_budget_exceeded",
                used=used,
                limit=limit,
                window=self.context_window,
            )
            return True
        return False

    def utilization(self, messages: list[Message]) -> float:
        used = self.current_tokens(messages)
        return used / self.context_window if self.context_window > 0 else 0.0
