"""Agent loop — the core run loop that drives the conversation.

The loop repeats:
  1. Check context budget → compact if needed
  2. Stream an LLM turn → collect text + tool calls
  3. If no tool calls → done
  4. Execute tool calls → feed results back → next iteration

The loop emits ``AgentEvent`` objects that the TUI consumes for real-time
rendering. It is fully async and supports cancellation via ``asyncio.Event``.
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator
from dataclasses import dataclass
from enum import StrEnum

from coding_agent.agent.compaction import compact_messages
from coding_agent.agent.context import ContextBudget
from coding_agent.agent.orchestrator import ConfirmCallback, execute_tool_calls
from coding_agent.agent.prompts import build_system_prompt
from coding_agent.core.config import Config
from coding_agent.core.logging import get_logger
from coding_agent.core.session import Session
from coding_agent.core.types import (
    Role,
    StreamEventType,
    ToolCall,
    ToolResult,
    Usage,
)
from coding_agent.providers.base import LLMProvider
from coding_agent.security.audit import AuditLog
from coding_agent.security.permissions import PermissionEngine
from coding_agent.security.rules import RuleSet
from coding_agent.tools.base import ToolContext, all_schemas

log = get_logger("agent.loop")


# ---------------------------------------------------------------------------
# Events emitted to the TUI
# ---------------------------------------------------------------------------


class EventKind(StrEnum):
    TEXT_DELTA = "text_delta"
    TOOL_START = "tool_start"
    TOOL_RESULT = "tool_result"
    USAGE = "usage"
    TURN_END = "turn_end"
    ERROR = "error"


@dataclass
class AgentEvent:
    kind: EventKind
    text: str = ""
    tool_call: ToolCall | None = None
    tool_result: ToolResult | None = None
    usage: Usage | None = None
    finish_reason: str | None = None
    error: str | None = None


# ---------------------------------------------------------------------------
# Agent
# ---------------------------------------------------------------------------


class Agent:
    """Stateful agent that processes one user message at a time."""

    def __init__(
        self,
        provider: LLMProvider,
        config: Config,
        session: Session,
        *,
        confirm: ConfirmCallback | None = None,
    ) -> None:
        self.provider = provider
        self.config = config
        self.session = session
        self.confirm = confirm
        self._cancel = asyncio.Event()

        self._ctx = ToolContext(
            workspace=config.workspace.resolve(),
            session_id=session.id,
        )

        user_rules = RuleSet()
        if config.permissions.rules_file:
            user_rules = RuleSet.from_yaml_file(str(config.permissions.rules_file))
        self._permission_engine = PermissionEngine(config.permissions, user_rules)
        self._audit_log = AuditLog()
        self._context_budget = ContextBudget(
            context_window=provider.context_window,
            compact_threshold=config.agent.compact_threshold,
            keep_recent_turns=config.agent.keep_recent_turns,
        )

        if not session.messages or session.messages[0].role != Role.SYSTEM:
            system_prompt = build_system_prompt(
                config.workspace, config.provider, provider.model
            )
            session.add_system(system_prompt)

    def cancel(self) -> None:
        self._cancel.set()

    async def run(self, user_input: str) -> AsyncIterator[AgentEvent]:
        """Process one user message through the full agent loop.

        Yields ``AgentEvent`` objects for TUI rendering. The loop runs until
        the model stops calling tools or ``max_iterations`` is reached.
        """
        self._cancel.clear()
        self.session.add_user(user_input)

        iterations = 0
        max_iter = self.config.agent.max_iterations

        while iterations < max_iter:
            iterations += 1

            if self._cancel.is_set():
                yield AgentEvent(kind=EventKind.ERROR, error="Cancelled by user.")
                return

            # -- context budget check → compact if needed --
            if self._context_budget.should_compact(self.session.messages):
                try:
                    self.session.messages = await compact_messages(
                        self.session.messages,
                        self.provider,
                        keep_recent=self.config.agent.keep_recent_turns,
                    )
                    log.info("context_compacted", message_count=len(self.session.messages))
                except Exception as e:
                    log.warning("compaction_failed", error=str(e))

            # -- stream LLM turn --
            text_buf: list[str] = []
            reasoning_buf: list[str] = []
            tool_calls: list[ToolCall] = []
            turn_usage: Usage | None = None
            finish_reason: str | None = None

            tool_arg_buffers: dict[str, list[str]] = {}
            tool_names: dict[str, str] = {}

            try:
                schemas = all_schemas()
                stream = self.provider.stream(
                    self.session.messages,
                    schemas,
                    temperature=0.0,
                )

                async for event in stream:
                    if self._cancel.is_set():
                        yield AgentEvent(kind=EventKind.ERROR, error="Cancelled by user.")
                        return

                    if event.type == StreamEventType.REASONING_DELTA and event.text:
                        reasoning_buf.append(event.text)

                    elif event.type == StreamEventType.TEXT_DELTA and event.text:
                        text_buf.append(event.text)
                        yield AgentEvent(kind=EventKind.TEXT_DELTA, text=event.text)

                    elif event.type == StreamEventType.TOOL_USE_START:
                        tc_id = event.tool_call_id or ""
                        tool_names[tc_id] = event.tool_name or ""
                        tool_arg_buffers[tc_id] = []
                        yield AgentEvent(
                            kind=EventKind.TOOL_START,
                            tool_call=ToolCall(
                                id=tc_id,
                                name=event.tool_name or "",
                                arguments={},
                            ),
                        )

                    elif event.type == StreamEventType.TOOL_USE_DELTA:
                        tc_id = event.tool_call_id or ""
                        if tc_id in tool_arg_buffers and event.arguments_delta:
                            tool_arg_buffers[tc_id].append(event.arguments_delta)

                    elif event.type == StreamEventType.TOOL_USE_END:
                        tc_id = event.tool_call_id or ""
                        raw_args = "".join(tool_arg_buffers.get(tc_id, []))
                        try:
                            args = json.loads(raw_args) if raw_args else {}
                        except json.JSONDecodeError:
                            args = {}
                        tool_calls.append(
                            ToolCall(
                                id=tc_id,
                                name=tool_names.get(tc_id, ""),
                                arguments=args,
                            )
                        )

                    elif event.type == StreamEventType.USAGE and event.usage:
                        turn_usage = event.usage

                    elif event.type == StreamEventType.DONE:
                        finish_reason = event.finish_reason

                    elif event.type == StreamEventType.ERROR:
                        yield AgentEvent(
                            kind=EventKind.ERROR,
                            error=event.error or "Unknown provider error",
                        )
                        return

            except Exception as e:
                log.error("agent_stream_error", error=str(e), exc_info=True)
                yield AgentEvent(
                    kind=EventKind.ERROR,
                    error=f"Provider error: {type(e).__name__}: {e}",
                )
                return

            # -- record assistant message --
            assistant_text = "".join(text_buf)
            reasoning_text = "".join(reasoning_buf) or None
            self.session.add_assistant(
                assistant_text,
                tool_calls=tool_calls if tool_calls else None,
                reasoning_content=reasoning_text,
            )

            if turn_usage:
                self.session.accumulate_usage(turn_usage)
                yield AgentEvent(kind=EventKind.USAGE, usage=turn_usage)

            # -- no tool calls → done --
            if not tool_calls:
                yield AgentEvent(
                    kind=EventKind.TURN_END, finish_reason=finish_reason or "stop"
                )
                self.session.save()
                return

            # -- execute tool calls --
            results = await execute_tool_calls(
                tool_calls,
                self._ctx,
                confirm=self.confirm,
                parallel=self.config.agent.parallel_tool_calls,
                permission_engine=self._permission_engine,
                audit_log=self._audit_log,
            )
            self.session.add_tool_results(results)

            for r in results:
                yield AgentEvent(kind=EventKind.TOOL_RESULT, tool_result=r)

            self.session.save()
            # → continue loop for next LLM turn

        yield AgentEvent(
            kind=EventKind.ERROR,
            error=f"Reached max iterations ({max_iter}). Stopping.",
        )
        self.session.save()
