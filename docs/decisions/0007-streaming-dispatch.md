# ADR 0007 — Streaming tool dispatch

Date: 2026-05-21
Status: Accepted (B3)

## Context

The original agent loop buffered the entire LLM stream — text deltas,
tool-call deltas — then ran tools only after `StreamEventType.DONE`. When
the model emits "Let me check that file for you..." (text) and then a
`read` tool call, the user waited for the model to stop talking before the
tool started running. With slow models or chatty completions this added
multiple seconds of dead air per turn.

## Decision

- Add `AgentConfig.streaming_tool_dispatch: bool = True`.
- When enabled, on `TOOL_USE_END` immediately launch
  `asyncio.create_task(execute_single_call(...))` and stash the future in an
  ordered `inflight` dict.
- After the stream ends (or errors), `await` each `inflight` task in the
  order the model requested them, then emit `TOOL_RESULT` events.
- Cancel / provider-error paths cancel pending tasks before returning.

## Consequences

- The user sees the tool start the moment its arguments parse, often while
  the LLM is still streaming the next paragraph.
- Parallelism is automatic: two tool calls in the same turn run concurrently
  with each other *and* with the rest of the stream.
- Trade-off: we give up the "see full assistant message before any side
  effect" property. This matches what every production agent (Claude Code,
  Cursor, Aider) already does.

## Alternatives considered

- **Run tools only after `DONE`** (the previous behaviour) — kept available
  via `streaming_tool_dispatch=False`. Useful for deterministic test traces
  and for users who want strict turn boundaries.
- **Run tools but block further LLM tokens until each finishes** — would
  defeat the point; we'd serialize at the per-tool level for no gain.

## Validation

`tests/integration/test_streaming_dispatch.py` includes a `SlowProvider`
that sleeps for 300 ms after the `TOOL_USE_END` before yielding `DONE`. The
test asserts the whole run finishes in less than 2× the sleep — proving the
tool ran concurrently with the stream tail.
