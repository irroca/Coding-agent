# ADR 0006 — Prompt cache strategy

Date: 2026-05-21
Status: Accepted (B2)

## Context

A typical agent turn re-sends 4-8K tokens of system prompt and tool schemas
that haven't changed since the previous turn. Both Anthropic and OpenAI
support prompt caching, but the wire-level mechanics differ:

- **Anthropic** requires explicit `cache_control={"type":"ephemeral"}` markers
  on cacheable blocks. The cache covers everything *up to and including* the
  marker, in declaration order.
- **OpenAI / DeepSeek** auto-cache prompts > 1024 tokens; clients only need
  to read `prompt_tokens_details.cached_tokens` (OpenAI) or
  `prompt_cache_hit_tokens` (DeepSeek) back.

## Decision

- **Anthropic provider sends two cache markers**: one on the system prompt
  (wrapped as a single `text` block), and one on the *last* tool. Because
  Anthropic caches in declaration order, a marker on the final tool covers
  system + every tool in one go.
- **OpenAI-compat providers stay marker-less**; we just parse cached_tokens
  from the response.
- Provider config gains `supports_prompt_cache: bool`; default-true for
  anthropic/openai/deepseek, default-false for qwen/moonshot until the
  vendor confirms behaviour.
- **`Usage` gains `cache_creation_tokens`** (Anthropic-specific, charges 1.25x
  for first write) and a `cache_hit_rate` property.
- **`/cost` displays hit rate** so users can see the win in real time.
- **`_merge_anthropic_usage` normalizes** the three disjoint counters
  Anthropic reports (`input_tokens`, `cache_read_input_tokens`,
  `cache_creation_input_tokens`) so `Usage.prompt_tokens` semantics match
  OpenAI's "total prompt size including cache reads".

## Consequences

- 4-8K tokens stop being re-billed each turn on long conversations.
  Anthropic's documented savings: 10x cheaper reads on cached input.
- The wire format diverges only at the boundary; nothing above
  `LLMProvider.stream()` changes.

## Validation caveat

When tested through Agent Maestro's local proxy
(`localhost:23333/api/anthropic/v1`), `cache_read_input_tokens` always came
back as 0 across 10 task runs. Unit tests confirm we send `cache_control`
correctly and parse the response correctly when present. The local proxy
appears not to forward cache state; production deployments against
`api.anthropic.com` directly should observe real savings.
