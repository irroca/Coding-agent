# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project

A production-grade terminal coding agent (Python ≥ 3.11) inspired by Claude Code. Course project for《人工智能应用开发》, hardened to deployment quality through the iteration logged in `docs/iteration-log.md`. Package: `coding_agent`, installed as the `coding-agent` / `cagent` CLI plus the `coding-agent-mcp` MCP server. Default LLM provider is DeepSeek; OpenAI / Anthropic / Qwen / Moonshot are also supported behind a single `LLMProvider` abstraction.

> Custom agent instructions are loaded from **`AGENTS.md`** (both `~/.coding_agent/AGENTS.md` and `<workspace>/AGENTS.md`) by `agent/prompts.py:_load_custom_instructions`, **not** from `CLAUDE.md`. `CLAUDE.md` is for Claude Code's own use when editing this repo; runtime customisation of the deployed agent belongs in `AGENTS.md`.

## Common commands

Dependency manager is `uv` (preferred). All commands assume the repo root as cwd.

```bash
# Install (with dev extras — gets ruff/mypy/pytest/respx + mcp)
uv sync --all-extras

# Run the REPL
uv run coding-agent
uv run coding-agent chat --provider qwen          # switch provider
uv run coding-agent chat --resume <session-id>    # resume a saved session
uv run coding-agent config-show                   # dump resolved config (keys redacted)
uv run coding-agent sessions                      # list recent sessions
uv run coding-agent sessions --grep "fix bug"     # filter by content
uv run coding-agent --version

# Expose built-in tools as an MCP server (for Claude Code / Cursor to consume)
uv run coding-agent-mcp                           # stdio MCP server
uv run python -m coding_agent.mcp.server --list   # dump JSON schemas for inspection

# Browser UI (needs `web` extra)
uv run coding-agent web                           # http://127.0.0.1:8765, opens browser
uv run coding-agent web --port 9000 --no-open-browser --workspace /path
# Frontend dev (only when editing React code):
#   cd frontend && npm install && npm run dev     # Vite dev server on :5173
#   npm run build                                  # rebuild bundle into src/coding_agent/web/static/

# Tests
uv run pytest tests/ -q                                            # full suite, ~290+ tests, no API key needed
uv run pytest tests/unit/ -v
uv run pytest tests/integration/ -v                                # uses MockProvider
uv run pytest tests/unit/path/to/test_file.py::test_name -v        # single test
uv run pytest tests/ --cov=coding_agent --cov-report=term-missing  # coverage
uv run pytest -m "not requires_api"                                # skip tests gated on real API keys (default)

# Lint / type-check (CI gates on the first two)
uv run ruff check src/ tests/ scripts/
uv run ruff check --fix src/ tests/ scripts/
uv run mypy src/

# Evals — point at any OpenAI-compat or Anthropic-compat endpoint
uv run python -m coding_agent.evals.cli --list
uv run python -m coding_agent.evals.cli \
    --provider openai --base-url http://localhost:23333/api/openai/v1 \
    --api-key sk-local --model claude-haiku-4.5 \
    --report docs/eval-reports/my-run.json
```

Pytest markers (`pyproject.toml`): `requires_api` (skipped by default — gate real-network tests with this), `slow`. `pytest-asyncio` runs in `auto` mode, so `async def` test functions work without decorators.

`tests/conftest.py` auto-strips all provider API keys from the environment and `chdir`s into `tmp_path` for every test (see `_isolated_env`). Don't try to set real API keys for unit tests — use `MockProvider` from `tests/integration/test_agent_loop.py` (or `test_subagent.py`, `test_streaming_dispatch.py`) instead.

## Architecture

Seven layers under `src/coding_agent/`. Each change usually belongs in exactly one layer; the boundaries are real.

```
cli/        TUI: Typer entry, REPL, Rich streaming render, confirm prompts, slash commands
web/        Browser UI: FastAPI + WebSocket runner, React/Vite SPA bundled under web/static/
agent/      Agent loop, tool orchestrator, context/token budget, compaction, prompt assembly
providers/  LLMProvider abstraction + adapters (openai_compat / anthropic / deepseek / qwen / moonshot / openai) + registry
tools/      Tool ABC + auto-registry + 9 built-ins (read/write/edit/ls/glob/grep/bash/todo_write/task)
mcp/        MCP client (ingest external servers) + MCP server (expose built-ins) over stdio
security/   5-layer permission engine, rule DSL, path_guard, command_guard, secrets, hash-chained audit log
core/       Config (pydantic-settings), session persistence, token counting, domain types, error hierarchy
plugins.py  entry_points loader for third-party tools/providers/slash commands
```

### The canonical types are the contract (`core/types.py`)

`Message`, `ToolCall`, `ToolResult`, `Usage`, `StreamEvent`, `ToolSchema` are vendor-neutral pydantic models. **The agent loop and tools never touch raw provider payloads.** Provider adapters translate to/from these on the boundary. If you add a new field to one of these, expect to update every provider adapter.

- `Message.reasoning_content` carries DeepSeek-style thinking traces; must be round-tripped to the provider on subsequent turns (`openai_compat.messages_to_openai` does it).
- `Usage` carries `cached_prompt_tokens` AND `cache_creation_tokens` (Anthropic-specific, charged 1.25×) plus a `cache_hit_rate` property. The Anthropic adapter normalizes the three disjoint Anthropic counters into `prompt_tokens` so the numbers compare cleanly with OpenAI.

### Agent loop (`agent/loop.py`)

`Agent.run(user_input)` is an async generator yielding `AgentEvent`s the REPL consumes. The cycle:

1. Check `ContextBudget.should_compact(messages)` → if over `compact_threshold` (default 0.85), call `compact_messages()` to LLM-summarize older turns while keeping the last `keep_recent_turns` (default 6) verbatim. Falls back to truncation if the summarisation call fails.
2. Stream one provider turn → buffer `TEXT_DELTA` / `REASONING_DELTA` / tool-call deltas → emit `AgentEvent`s.
3. **Streaming tool dispatch** (default on, `AgentConfig.streaming_tool_dispatch`): on `TOOL_USE_END` immediately `asyncio.create_task(execute_single_call(...))` — tools start running concurrently with the rest of the LLM stream. After the stream ends, results are awaited in model-requested order. See ADR-0007.
4. Record the assistant message (text + `reasoning_content` + tool_calls) on the `Session`.
5. If no tool calls → emit `TURN_END`, save session, return.
6. Else emit `TOOL_RESULT`s, append to session, loop.

A cancel `asyncio.Event` is checked at every stream tick and between iterations; pending tool tasks are cancelled on Ctrl+C or provider error. The REPL wires `KeyboardInterrupt → agent.cancel()`. `max_iterations` (default 50) is the last-resort safety net.

### Sub-agent dispatch (`tools/task.py`)

`task` is a real tool, not a placeholder. It reuses the `Agent` class with two hard constraints (ADR-0005):

- **Read-only tool surface** — locked to `frozenset({"read", "ls", "glob", "grep"})` (`SUBAGENT_TOOLS`). Cannot be widened by config.
- **1-level recursion cap** — `ToolContext.is_subagent=True` propagates into the child; the `task` tool refuses to fire when that flag is set.

The sub-agent runs in an isolated `Session`. The parent only sees the final assistant text as the tool result — tool calls, intermediate text, and reasoning stay inside the sub-agent. `AgentConfig.subagent_max_iterations` (default 15) is independent of the parent's `max_iterations`.

### Stream contract (`providers/base.py`)

Every provider adapter MUST yield `StreamEvent`s in this order for each tool call:

1. `TOOL_USE_START` with both `tool_call_id` and `tool_name`.
2. Zero or more `TOOL_USE_DELTA` with the same `tool_call_id` and `arguments_delta` (a JSON-string fragment).
3. `TOOL_USE_END` with the same `tool_call_id`.

Text and tool events may interleave; order is preserved. One optional `USAGE` event, then `DONE` with `finish_reason ∈ {"stop", "tool_calls", "length", "error"}`. Errors come as `ERROR` events and end the stream. Transient errors should be retried inside the adapter; auth / rate-limit failures map to `ProviderAuthError` / `ProviderRateLimitError`.

### OpenAI-compat adapter (`providers/openai_compat.py`)

DeepSeek, Qwen (DashScope OpenAI mode), Moonshot, and OpenAI all share this implementation. To add a new OpenAI-compatible provider, subclass `OpenAICompatProvider` and override:

- `name`, `default_base_url`, `default_model`
- `supports_stream_usage` (whether the vendor honours `stream_options={"include_usage": True}`)
- `extra_headers` (vendor-specific auth headers, if any)

Then register the class in `providers/registry.py:_REGISTRY` and add an env-var entry in `core/config.py:_hydrate_providers_from_env`.

Critical streaming quirks (see B7 adversarial tests):

- Vendors deliver `tool_calls` deltas **indexed by position**, not id. Vendor sends `id` and `function.name` only on the first chunk for that index; later chunks are pure `function.arguments` fragments. `_ToolCallAccumulator` maintains the `index → (id, name, args_buffer)` map and synthesizes canonical START/DELTA/END events.
- DeepSeek emits "empty" leading deltas which are silently dropped.
- DeepSeek reports cache hits as `prompt_cache_hit_tokens`; OpenAI as `prompt_tokens_details.cached_tokens`; both feed `Usage.cached_prompt_tokens`.
- Usage chunks may arrive **after** `[DONE]`; we keep reading.

### Anthropic adapter + prompt cache (`providers/anthropic.py`)

Native Messages API (event-typed SSE, not OpenAI-compat). When `ProviderConfig.supports_prompt_cache=True` (ADR-0006):

- The system prompt is wrapped as a single `text` block with `cache_control={"type":"ephemeral"}`.
- The **last** tool in `tools[]` also gets a `cache_control` marker — Anthropic caches in declaration order, so this one breakpoint covers system + every tool.
- `_merge_anthropic_usage` normalizes `input_tokens` + `cache_read_input_tokens` + `cache_creation_input_tokens` into `Usage.prompt_tokens` so `cache_hit_rate` is meaningful and OpenAI-comparable.

### Tool system (`tools/base.py`)

Each tool subclasses `Tool` with:

- `name: ClassVar[str]` and `description: ClassVar[str]`
- `Params: ClassVar[type[BaseModel]]` — a pydantic model; its `model_json_schema()` is sent to the LLM
- `async def run(self, params, ctx: ToolContext) -> ToolResult`
- Optional `permission_request(params) -> PermissionRequest` (default returns `action="ask"`)
- Optional `generate_diff(params, ctx) -> str | None` — duck-typed, picked up by the orchestrator to render a diff preview in the confirm prompt (see `write.py` / `edit.py`).

Registration happens via `__init_subclass__` — importing the module is enough. `tools/__init__.py` imports every built-in to trigger registration. To opt out of auto-registration (used by `mcp.client._RemoteTool`), declare with `class MyTool(Tool, register=False)`.

`ToolContext` carries `workspace`, `session_id`, plus `provider`/`config` (needed by tools that spawn sub-agents) and `is_subagent` (the recursion guard).

`PermissionRequest.action` is one of three strings: `file_read | file_write | bash`. (The `network` category was deleted in B6/ADR-0009 — no tool used it; bash command guard already flags curl/wget.)

`Tool.schema(allowed=None)` returns the JSON schema list, optionally filtered by a name allow-list (sub-agents use this to restrict their LLM-visible surface).

`write` and `edit` annotate `ToolResult.metadata` with `previous_content` / `new_content`, used by `/diff` and `/undo`.

### MCP integration (`mcp/`)

ADR-0008. The `mcp` package is an optional extra (`pip install coding-agent[mcp]`, included in `dev`).

- **Client** (`mcp/client.py`): `McpClientHost` opens stdio sessions to every server in `Config.mcp.servers`, calls `initialize()` + `list_tools()`, and synthesizes a `_RemoteTool` subclass per discovered tool. Synthetic tools are registered as `mcp__<server>__<tool>` and treated as `action="bash"` by the permission engine until the user opts in with a rule like `{tool: "mcp__github__*", decision: allow}`. Started during REPL boot (`cli/repl.py`).
- **Server** (`mcp/server.py`): exposes every built-in tool except `task` (no LLM available inside a server context) over MCP stdio using the low-level `Server` API with explicit JSON schemas. Permission engine + audit log still run on every call. `--list` flag dumps schemas without starting the transport.

### Bash sandbox (`tools/bash.py`)

ADR-0009. `AgentConfig.bash_driver` selects the backend:

- `"subprocess"` (default): runs in the host's process namespace.
- `"docker"`: `docker run --rm --network none --cpus 2 --memory 1g --security-opt no-new-privileges` with the workspace bind-mounted at `/workspace`. Image is `AgentConfig.bash_docker_image` (default `python:3.12-slim`). Refuses if `working_directory` resolves outside the workspace. Falls back with a clear error if the `docker` binary isn't present.

### Permission engine (`security/permissions.py`)

Every tool call passes through 5 layers, in order — first match wins:

1. **Built-in deny rules** (`security/rules.py:BUILTIN_DENY_RULES`, unbypassable): `rm -rf /`, `mkfs.*`, `dd if=… of=/dev/…`, fork bomb, writes to `.env*`, `id_rsa*`, `*.pem`.
2. **User-defined rules** from `permissions.rules_file` (YAML, parsed by `RuleSet.from_yaml_file`). Format: list of `{tool, action?, match?, path?, decision: allow|ask|deny}`. `match` is a regex against the command; `path` is fnmatch against the path.
3. **Built-in allow rules**: `git status|diff|log|show|branch`, basic read-only shell, `python -m pytest|ruff|mypy`.
4. **Command guard heuristics** (bash only, `security/command_guard.py`): shlex-parses the command, flags executables in `DANGEROUS_EXECUTABLES` (curl/wget/rm/chmod/sudo/…), auto-allows `SAFE_EXECUTABLES` when there's no subshell/redirect.
5. **Config defaults**: `file_read=allow`, `file_write=ask`, `bash=ask`.

Every decision is appended as a JSON line to `<user_data_dir>/coding_agent/audit.log`.

### Security hardening (`security/secrets.py`, `security/audit.py`)

ADR-C4 work (no separate ADR — the design is contained in those modules):

- **Secret detection** — `find_secrets(text)` returns `(kind, value)` matches for openai / anthropic / github / aws / google / slack / generic-hex. Patterns are deliberately narrow (false positives in a coding agent context destroy source utility). `redact(text)` replaces matches with `<kind:abcd…xy>` keeping a 4+2 window.
- **Pre-commit hook** — `scripts/secret_scan.py` is wired in `.pre-commit-config.yaml` and aborts commits that contain detected secrets.
- **Hash-chained audit log** — every entry carries `prev_hash` + `hash` (SHA-256 over the canonical JSON of the entry, chained with the previous hash). `AuditLog.verify_chain()` returns the line index of the first broken entry. Secrets in `summary`/`reason`/`command` are redacted **before** hashing, so a leaked key cannot be reconstructed from the audit log.

**Do not bypass `path_guard.resolve_and_validate`** in any file-touching tool — it's the only defence against path traversal, symlink escape, absolute-path injection, and null bytes.

### Config layering (`core/config.py`)

Sources merge in this order (later wins):

1. Built-in defaults in `Config` / `ProviderConfig` / `PermissionsConfig` / `AgentConfig` / `UIConfig`.
2. `~/.config/coding_agent/config.yaml` (user, resolved via `platformdirs.user_config_dir`).
3. `<workspace>/.coding_agent/config.yaml` (project).
4. `.env` (loaded into `os.environ` via `python-dotenv`) plus env vars prefixed `CODING_AGENT_` (pydantic-settings, `env_nested_delimiter="__"`).
5. CLI flags (`--provider`, `--log-level`).

Provider credentials use the **non-prefixed** vendor names — `DEEPSEEK_API_KEY`, `DASHSCOPE_API_KEY`, `MOONSHOT_API_KEY`, `OPENAI_API_KEY`, `ANTHROPIC_API_KEY` — backfilled into `ProviderConfig` by `_hydrate_providers_from_env` after pydantic-settings runs. The same hook backfills `supports_prompt_cache` to a sensible per-vendor default (True for openai/anthropic/deepseek, False for qwen/moonshot). `load_config` is `lru_cache`'d; call `reset_config_cache()` after env mutations (tests do this automatically).

### Sessions (`core/session.py`)

Every REPL run owns a `Session` saved to `<user_data_dir>/coding_agent/sessions/<id>.json` after every turn (so `--resume` works even after a crash). The session id is `YYYYMMDD-HHMMSS-<uuid8>`. `Session.list_recent` powers both the CLI `sessions` command and `/sessions`; `Session.list_matching(query)` powers `coding-agent sessions --grep`.

### CLI / REPL (`cli/`)

- `cli/app.py` — Typer entry. The default command (no subcommand) is `chat`. Subcommands: `chat`, `sessions [--grep <q>]`, `config-show`.
- `cli/repl.py` — `_async_repl` runs `plugins.load_plugins()`, boots the provider, starts the `McpClientHost` if any external servers are configured, loads/creates a `Session`, wires the confirm callback (with per-session auto-approve set), and runs `prompt_toolkit` in a thread. Streams agent events through `Renderer`. `KeyboardInterrupt` → `agent.cancel()`; `EOFError` (Ctrl+D) → exit.
- `cli/slash_commands.py` — `@slash("name", "description")` decorator-based registry. Commands: `/help /clear /cost /model /exit /compact /history /sessions /permissions /tools /diff /undo`. Handlers receive `console`, `session`, `provider_name`, `model_name` by name. `/diff` reconstructs cumulative per-file diffs from session history; `/undo` restores the last write (or deletes the file if it was originally created).

### Plugin system (`plugins.py`)

ADR-0010. `load_plugins()` is called once at REPL startup. It walks three `importlib.metadata.entry_points` groups:

- `coding_agent.tools` — values resolve to `Tool` subclasses or modules that auto-register via `__init_subclass__`.
- `coding_agent.providers` — values resolve to `LLMProvider` subclasses; registered into `providers.registry._REGISTRY` under the entry-point name.
- `coding_agent.slash_commands` — values resolve to `@slash`-decorated functions or modules that register on import.

Defensive: a plugin that raises on load is logged with `WARNING` and skipped — host never crashes. Idempotent: calling `load_plugins()` twice is a no-op.

### Browser UI (`web/`)

ADR-0011. Optional layer (`pip install coding-agent[web]`) that exposes the existing `Agent` over a WebSocket plus a React SPA. Entirely additive — agent / provider / tool / TUI code is unchanged.

- `web/protocol.py` — pydantic message types, `Field(discriminator="type")` unions for both server→client and client→server.
- `web/runner.py` — `SessionRunner`, one per browser tab. Owns one `Agent` + `Session`, drains a submit queue, pumps `AgentEvent`s into an outbound `asyncio.Queue`, resolves permission prompts via a `request_id → asyncio.Future` map.
- `web/server.py` — FastAPI app factory + `/ws/{tab_id}` handler + uvicorn `run()`. **Deliberately omits `from __future__ import annotations`** because FastAPI's `WebSocket` parameter detection uses runtime `get_type_hints()`, which breaks under PEP-563 string annotations.
- `web/routes.py` — REST: `/api/sessions[/{id}]` (list / load / delete), `/api/workspaces`, `/api/tools`, `/api/config`. Recent-workspaces state lives at `<user_config_dir>/coding_agent/web-state.json`.
- `frontend/` — Vite + React 18 + TS + Tailwind + Radix Dialog. Build output `frontend/dist/` is configured to land in `src/coding_agent/web/static/` (committed and shipped in the wheel via the `[tool.hatch.build.targets.wheel.force-include]` rule).

Permission confirmation reuses the existing `ConfirmCallback = Callable[[str, str, str|None], Awaitable[bool]]` contract from `agent/orchestrator.py`. The "Always allow this session" checkbox feeds into the per-runner `_auto_approve: set[str]` mirroring `cli/repl.py:auto_approve`.

`coding-agent web` is a Typer subcommand. Defaults: `127.0.0.1:8765`, no auth, opens system browser. **Do not bind to non-loopback unless you understand there is no authentication layer.**

## Eval framework (`evals/`)

The runner spins up a real `Agent` in a throwaway tmpdir, replays the task prompt, and asserts on workspace state. Beyond pass/fail it captures `TaskMetrics`: iterations, tool-call count + per-tool histogram, prompt/completion/cached tokens, wall-clock duration. `--report path.json` writes a machine-readable report for cross-run comparison (see `docs/eval-reports/` for baselines).

10 built-in tasks live in `evals/tasks/*.json`. Each task is `{id, name, prompt, assertions: [{type, …}]}` where `type` is one of `file_exists | file_contains | file_not_contains | file_equals | command_output`.

## Conventions and gotchas

- **Ruff**: `E,W,F,I,B,UP,N,SIM,RUF`. `E501` off (formatter handles width). Tests are exempt from `N802/N803`. CI gates on `ruff check`.
- **mypy**: strict mode is configured but several pre-existing pre-iteration files still emit errors (~42 across `cli/prompt.py`, `cli/repl.py`, `cli/slash_commands.py`, `providers/openai_compat.py`, etc.). They are not gated in CI yet (set `mypy.ini_options.strict_for_changed_only=true` once cleanup lands). Don't add new untyped code.
- **No `print()`** in library code — use the `structlog`-based logger from `core.logging.get_logger("module.name")`. The REPL is the only thing that writes to stdout (via Rich `Console`).
- **System prompt** is always at `messages[0]`; `Agent.__init__` inserts it if missing. Compaction preserves it.
- **`reasoning_content`** on assistant messages is non-optional state for DeepSeek thinking mode — don't drop it when constructing messages.
- **Tool output truncation** happens at two places: `BashTool.OUTPUT_LIMIT` (hard-coded 30 000 chars, head+tail) inside the tool, and `AgentConfig.tool_output_max_chars` (also 30 000) intended for the orchestrator. Tools should keep their content moderate.
- **Sub-agent leakage**: never serialize a sub-agent's intermediate messages into the parent's `Session`. The parent only sees the final summary; verified by `tests/integration/test_subagent.py::test_subagent_session_is_isolated`.
- **Audit log integrity**: if you add a new field to an `AuditLog.record(...)` entry, make sure `_hash_entry` covers it (it covers everything except `hash` itself).

## Adding things

- **A new tool**: subclass `Tool` in `tools/<name>.py`, define `Params` (pydantic), implement `async run` and `permission_request`. Add the import to `tools/__init__.py`. Add a unit test under `tests/unit/test_tools_*.py` covering happy path + permission/path-guard rejections.
- **A new OpenAI-compat provider**: subclass `OpenAICompatProvider`, set the four class vars, register in `providers/registry.py`, add the env-var mapping + cache-default in `core/config.py:_hydrate_providers_from_env`. Add a unit test patterned after `tests/unit/test_provider_openai_compat.py`.
- **A new slash command**: decorate a function with `@slash("name", "description")` in `cli/slash_commands.py`; the handler may accept any of `console`, `session`, `provider_name`, `model_name` by keyword.
- **A new permission rule type**: extend `Rule` in `security/rules.py` and `Rule.matches`; remember to wire it through `RuleSet.from_list`.
- **A new secret detector pattern**: append to `_PATTERNS` in `security/secrets.py`. Add both a positive test in `tests/unit/test_secrets.py` AND a negative test against a near-miss string — false positives destroy source code utility.
- **An end-to-end test**: copy the `MockProvider` pattern from `tests/integration/test_agent_loop.py` (or `test_subagent.py` for sub-agent flows, `test_streaming_dispatch.py` for timing-sensitive ones). The fixture in `conftest.py` already isolates env/cwd.
- **A plugin** (out-of-tree): in your `pyproject.toml` add `[project.entry-points."coding_agent.tools"]` (or `.providers` / `.slash_commands`) mapping a name to your `Tool` subclass or module dotted-path.

## Design docs

`docs/` carries the deeper rationale — read before non-trivial work on the matching layer.

- `docs/architecture.md` — layer overview
- `docs/agent-loop.md` — event-driven run loop
- `docs/tool-system.md` — Tool ABC, registration, JSON Schema contract
- `docs/permission-model.md` — 5-layer engine, rule DSL, audit log
- `docs/provider-abstraction.md` — stream event normalization, protocol adapters
- `docs/prompt-design.md` — modular system-prompt assembly
- `docs/evaluation.md` — eval framework and task set
- `docs/iteration-log.md` — every phase of the production-grade push (this is the **most current** snapshot — read it first when resuming work)
- `docs/decisions/` — ADRs:
  - 0001 language and runtime
  - 0002 LLM backend
  - 0003 tool protocol
  - 0004 permission model
  - 0005 sub-agent design
  - 0006 prompt cache strategy
  - 0007 streaming tool dispatch
  - 0008 MCP client + server
  - 0009 bash sandbox driver
  - 0010 plugin system
  - 0011 browser UI
