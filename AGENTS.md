# AGENTS.md

Custom instructions for **runtime** agent behavior — loaded by
`agent/prompts.py:_load_custom_instructions` and appended to the system prompt
when the Coding Agent runs in this workspace. Two files are read, in order:

1. `~/.coding_agent/AGENTS.md` — user-level (applies in every workspace)
2. `<workspace>/AGENTS.md` — project-level (this file)

`CLAUDE.md` is **not** consulted at runtime; it's only for Claude Code when it
edits this repo. Keep project-runtime guidance here.

---

## Project shape

This repository **is** the Coding Agent. When you're invoked inside it you're
working on your own implementation — be conservative:

- The 5-layer permission engine is the security boundary. Don't widen
  `BUILTIN_DENY_RULES` or change `path_guard.resolve_and_validate` without an
  ADR and a test.
- `core/types.py` is the vendor-neutral contract. Adding a field there means
  updating every provider adapter; don't do it casually.
- Sub-agent tool surface is `frozenset({"read", "ls", "glob", "grep"})` —
  hard-coded by design. Don't widen it from a feature branch.
- The MCP server (`coding-agent-mcp`) deliberately omits the `task` tool — it
  has no LLM context. Don't expose it.

## Working style

- Read `docs/iteration-log.md` first when continuing prior work; it's the
  authoritative cross-session checkpoint.
- Use `uv run pytest tests/ -q` after non-trivial changes — the suite is
  fast (~9s) and gates on real bugs.
- Default to **edit** over **write** for existing files; the diff preview in
  the confirm prompt depends on it.
- Don't add `print()` to library code — use `core.logging.get_logger(...)`.
  Only `cli/` writes to stdout.
- Tests must not require live API keys; reuse `MockProvider` from
  `tests/integration/test_agent_loop.py`.

## Local LLM endpoint

If a local Agent-Maestro-style proxy is available at
`http://localhost:23333`, evals can target it:

```bash
uv run python -m coding_agent.evals.cli \
    --provider openai --base-url http://localhost:23333/api/openai/v1 \
    --api-key sk-local --model claude-haiku-4.5 \
    --report docs/eval-reports/my-run.json
```

Known limitation: this proxy doesn't forward Anthropic `cache_read_input_tokens`,
so the `/cost` cache hit rate will read 0% even when the wire format is
correct. Production deployments against `api.anthropic.com` work as expected.

## Don't

- Don't commit unless explicitly asked.
- Don't push to the published endpoint.
- Don't disable pre-commit hooks (`--no-verify`); fix the underlying issue.
- Don't `git reset --hard` or `git push --force` without explicit user OK.
