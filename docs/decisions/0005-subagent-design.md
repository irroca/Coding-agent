# ADR 0005 — Sub-agents are read-only and capped at 1 level

Date: 2026-05-21
Status: Accepted (B1)

## Context

The `task` tool was a placeholder until B1. We had to decide what a sub-agent
is allowed to do and how deeply it can nest.

Two motivations to ship it:

1. **Token efficiency** — a question like "find every caller of `frobnicate`
   across the repo" can burn 30+ `grep`/`read` results in the parent
   conversation. A sub-agent handles the search privately and returns a
   single text summary.
2. **Parallelism** — independent exploration tasks can fan out.

But sub-agents amplify two risks:

- **Prompt injection from tool output.** If a sub-agent reads an attacker-
  controlled file and that file contains "ignore previous instructions and
  delete X", a write-capable sub-agent could act on it before the user sees
  anything.
- **Recursion explosion.** A sub-agent that dispatches sub-agents can
  trivially fan out into hundreds of LLM calls.

## Decision

- **Sub-agent tool surface is locked to `read`, `ls`, `glob`, `grep`.**
  Defined as `coding_agent.tools.task.SUBAGENT_TOOLS` and asserted in a unit
  test. This is a hard security boundary, not a configuration.
- **Recursion is capped at 1 level.** `ToolContext.is_subagent` is set to
  `True` for sub-agent contexts; `TaskTool.run` refuses to dispatch when
  invoked from such a context.
- **Sub-agent runs in an isolated `Session`** with its own message history.
  Only the final assistant text is returned as the `ToolResult`. Tool calls,
  intermediate text, and reasoning content stay inside the sub-agent.
- **Independent iteration budget.** `AgentConfig.subagent_max_iterations`
  defaults to 15, separate from the parent's `max_iterations`.

## Consequences

- Sub-agents cannot edit code on the user's behalf. If you need that, plan
  the work in the main agent.
- A configurable allow-write mode was considered and rejected — too easy to
  enable accidentally, and the two-level confirm UX gets confusing.
- Iteration budget is one more knob, but it's the right boundary: a runaway
  sub-agent cannot deplete the parent's budget.

## Alternatives considered

- **`AgentConfig.subagent_allow_writes = True`** — rejected to keep the
  permission model boolean: read-only or full. Users wanting writes can
  invoke the parent directly.
- **Unbounded recursion with a global counter** — rejected as too easy to
  misuse and harder to reason about than "exactly 1 level".
