# Iteration Log

This document tracks the multi-phase iteration plan started 2026-05-21. It records
phase status, key decisions, and validation results so a future Claude session can
continue from where the previous one left off.

> **Read me first when resuming**: scan the "Phase status" table to see what's
> done, then check "Open decisions" for anything that requires user input.

---

## Goal

Take the project from "working prototype" to **production-grade**. The user
explicitly asked for 8 substantive directions plus continuous iteration, with
permission to refactor freely.

## Constraints agreed up front

| Decision | Value | Rationale |
|---|---|---|
| Language | Python (unchanged) | Existing code is mature; rewriting would burn 10+ days for zero functional gain |
| Refactor scope | Free to delete/restructure | User said "可以大改" |
| Validation | `pytest`, `ruff`, `mypy`, `uv sync` allowed | Authorized in advance |
| Eval models | `claude-haiku-4.5` AND `gpt-5-mini` via local endpoint | Both validate two cache mechanisms |
| Sub-agent tools | Read-only only (read/ls/glob/grep) | Safer default; write tools stay in main agent |
| Sub-agent recursion | 1 level only | Prevent fan-out explosion |
| Docker sandbox | Yes, as optional bash backend | Real production isolation need |
| MCP scope | Both client and server | User wants ecosystem interop |
| Hardening | CI/CD + PyPI + plugins + security | Full production push |

## Local LLM endpoint

All evals and live tests go through Agent Maestro on `localhost:23333`:

- OpenAI-compat: `http://localhost:23333/api/openai/v1`
- Anthropic-compat: `http://localhost:23333/api/anthropic/v1`
- Any non-empty `Authorization: Bearer …` is accepted
- Verified working with `claude-haiku-4.5` (see below)

---

## Phase status

| ID | Phase | Subject | Status | Notes |
|---|---|---|---|---|
| A0 | A | Fix macOS path test | ✅ done | `/etc` → `/private/etc` symlink — used `.resolve()` |
| A1 | A | Fix evals/runner.py + local endpoint adapter | ✅ done | `create_provider` → `build_provider`; added `base_url`/`model` overrides, TaskMetrics with token/iteration counts, JSON report export, `--base-url`/`--model`/`--report` CLI flags |
| A2 | A | This iteration log | ✅ done | Will be kept updated through the rest of the iteration |
| A3 | A | Baseline eval (haiku + gpt-5-mini) | ✅ done | claude-haiku-4.5: 10/10 pass, 116k tokens, 0% cache. gpt-5-mini: 10/10 pass, 174k tokens, 0% cache. Reports in `docs/eval-reports/baseline-*.json` |
| B1 | B | Sub-agent (`task` tool) | ✅ done | Real implementation: read-only tool subset, 1-level recursion cap, isolated Session, only final text returned. 3 integration + 4 unit tests added |
| B2 | B | Prompt cache | ✅ done | Anthropic: cache_control on system + last tool. OpenAI/DeepSeek: report cached_tokens. `/cost` shows hit rate. **See ADR-006 for proxy caveat — Agent Maestro doesn't forward cache state, but unit tests prove the wire format is correct.** |
| B3 | B | Streaming tool dispatch | ✅ done | `AgentConfig.streaming_tool_dispatch` (default true) kicks off tools at `TOOL_USE_END` via `asyncio.create_task`, runs them concurrently with the LLM stream. Test asserts wall-clock < 2× sleep. Falls back to batch dispatch when disabled. Cancel/error paths cancel pending tasks. |
| B4 | B | MCP client | ✅ done | `McpClientHost` spawns stdio sessions to external MCP servers, discovers their tools, synthesizes `Tool` subclasses with `register=False`, registers them as `mcp__<server>__<tool>` in `_TOOL_REGISTRY`. Hooked into REPL boot. End-to-end test connects to our own MCP server and calls `ls` through the synthetic tool. |
| B5 | B | MCP server | ✅ done | `coding-agent-mcp` console script + `python -m coding_agent.mcp.server`. Uses low-level `Server` API with explicit JSON schemas (not FastMCP type inference). All non-`task` tools exposed; permission engine and audit log still enforced. `--list` debug mode prints JSON schema dump. |
| B6 | B | Docker bash sandbox + delete `network` | ✅ done | `BashTool` got `AgentConfig.bash_driver = subprocess\|docker` and `bash_docker_image`. Docker runs each command in throwaway container with `--rm --network none --cpus 2 --memory 1g --security-opt no-new-privileges`, workspace mounted at `/workspace`. Refuses cwd outside workspace. Friendly fallback when docker binary missing. `PermissionsConfig.network` removed (no tool used it). 5 new tests including command-line safety-flag inspection. |
| B7 | B | Provider conformance + compaction E2E | ✅ done | 6 new SSE adversarial tests (leading empty deltas, usage after `[DONE]`, DeepSeek `prompt_cache_hit_tokens`, interleaved text/tool/text, two parallel tool_calls indexed correctly, synthetic empty usage when vendor omits). 1 compaction E2E test confirms system prompt preserved + recent turns kept + summary marker inserted after threshold crossed. |
| B8 | B | `/diff` `/undo` `sessions --grep` | ✅ done | `write`/`edit` metadata now carries `previous_content`/`new_content`. `/diff` reconstructs cumulative per-file unified diffs from session history (collapses repeated writes). `/undo` restores the last write (or deletes the file if it was originally created). `coding-agent sessions --grep <substring>` walks saved sessions and filters by message content. 6 unit tests. |
| C1 | C | GitHub Actions CI | ✅ done | `.github/workflows/ci.yml`: matrix (Ubuntu × macOS, Python 3.11/3.12) running ruff + pytest + coverage upload; sdist/wheel build job gated on test success |
| C2 | C | PyPI + Dockerfile | ✅ done | `.github/workflows/release.yml`: tag-triggered PyPI trusted publishing + Docker image to GHCR. `Dockerfile` (python:3.12-slim + git + tini, non-root, `coding-agent chat` entrypoint). `.dockerignore`. Project URLs and `CHANGELOG.md` added. `uv build` verified locally. |
| C3 | C | Plugin system | ✅ done | `coding_agent.plugins.load_plugins()` uses `importlib.metadata.entry_points` with three groups: `coding_agent.tools` / `.providers` / `.slash_commands`. Loaded automatically on REPL startup, before provider is built. Defensive: broken plugin logs warning, doesn't crash host. Idempotent. 5 unit tests covering each group and error paths. |
| C4 | C | Security hardening | ✅ done | `security/secrets.py` (precise patterns for openai/anthropic/github/aws/google/slack + generic-hex; 4+2 redaction window). `scripts/secret_scan.py` pre-commit hook (skips eval reports, binaries, test fixtures). Audit log `audit.py` rewritten with SHA-256 prev_hash chain + secret redaction *before* hashing. `AuditLog.verify_chain()` returns first broken line index. 13 secret tests + 8 chain tests, all pass. |
| C5 | C | Doc sync (CLAUDE.md / README / AGENTS / ADRs) | ✅ done | CLAUDE.md rewritten (architecture + conventions + adding-things). README rewritten (MCP / Docker / plugins / 安全 sections + 10 ADRs linked + 294-test note + iteration-log link). New project-level `AGENTS.md` at workspace root (referenced by `agent/prompts.py:_load_custom_instructions`). `docs/architecture.md` refreshed for MCP / plugin layer + 294 tests. `docs/agent-loop.md` got a streaming-dispatch section. `docs/evaluation.md` updated to TaskMetrics + JSON-report flow + 294 tests. |
| D1 | D | Final eval + diff report | ✅ done | claude-haiku-4.5: 10/10 (baseline 10/10), tokens −1.1% prompt / −1.4% completion. gpt-5-mini: 9/10 (one proxy-layer SSE flake on task 03; targeted retry passed), tokens −2.4% / −2.0%. Full diff in `docs/eval-reports/final-report.md`; raw JSON in `docs/eval-reports/final-*.json`. |
| E1 | E | Browser UI (FastAPI + React) | ✅ done | New optional `coding_agent.web` package + `coding-agent web` Typer subcommand. FastAPI WebSocket at `/ws/{tab_id}`; per-tab `SessionRunner` wraps `Agent` + `Session` and resolves permission prompts via WS round-trip. React 18 + TS + Tailwind + Radix SPA in `frontend/`, build output committed to `src/coding_agent/web/static/` and shipped in the wheel (no Node needed at install time). 44 new tests (protocol, runner, REST routes, full WebSocket e2e); total **338 pass**. See ADR-0011 and `docs/web-ui.md`. |

Legend: ✅ done · 🔄 in progress · 🔲 todo · ⚠️ blocked

---

## Key architectural decisions made during this iteration

(Will be filled in as decisions are made. Each entry: date, context, choice, why.)

### ADR-005: Sub-agent tool set (to be made)
Planned: read-only tools only. Justification: a sub-agent that can `write`/`edit`
amplifies any prompt-injection from tool output, and the killer use-case for
sub-agents is **scoped exploration** (e.g. "find all callers of X across the
repo"), not parallel writes.

### ADR-006: Prompt cache strategy ✅ done

- Anthropic: explicit `cache_control={"type":"ephemeral"}` on system text block
  and on the **last** tool in the tools list. Anthropic caches in declaration
  order, so one marker on the last tool covers system + all tools.
- OpenAI: auto-cache when `prompt_tokens > 1024`, no request-side marker needed.
  We just report `prompt_tokens_details.cached_tokens` in `Usage.cached_prompt_tokens`.
- DeepSeek: same as OpenAI; uses `prompt_cache_hit_tokens` field instead.
- `Usage` gained `cache_creation_tokens` (Anthropic-specific, costs 1.25×).
- `Usage.cache_hit_rate` property added; `/cost` slash command shows it.
- `_merge_anthropic_usage` normalizes the disjoint Anthropic counters
  (input/cache_read/cache_creation) so `prompt_tokens` is comparable to OpenAI.

**Validation caveat**: when tested through Agent Maestro's local proxy
(`localhost:23333/api/anthropic/v1`), `cache_read_input_tokens` always came
back as 0 across 10 task runs. Single-unit tests confirm we send
`cache_control` correctly and parse `cache_read_input_tokens` correctly when
the server returns it. We conclude the local proxy is not forwarding cache
state — production deployments against `api.anthropic.com` directly should
work. Documented as a known limitation; OpenAI auto-cache would be similarly
unobservable through this proxy.

### ADR-007: Streaming tool dispatch (to be made)
Planned: dispatch on `TOOL_USE_END`, not after `DONE`. Trade-off: gives up the
"see full assistant message before any side effect" property, but matches what
all production agents do.

### ADR-008: MCP integration (to be made)
Planned: use `mcp` Python SDK (official). Client: ingest external server's tools
into `_TOOL_REGISTRY` at startup. Server: wrap built-in tools as MCP via stdio
transport.

### ADR-009: Bash sandbox driver (to be made)
Planned: `BashTool.driver = "subprocess" | "docker"`. Docker driver mounts
workspace read-write, no network by default, auto-removed container per call.
Falls back to subprocess if docker unavailable.

### ADR-010: Plugin system (to be made)
Planned: `entry_points` groups `coding_agent.tools`, `coding_agent.providers`,
`coding_agent.slash_commands`. Loader runs after built-in registration.

---

## Open decisions / questions for the user

(None right now — all four clarifying questions were answered before iteration started.)

---

## Validation log

| When | What | Result |
|---|---|---|
| 2026-05-21 | `uv sync --all-extras` | OK, 0.11.15 installed |
| 2026-05-21 | `uv run pytest tests/ -q` (initial) | 229 pass / 1 fail (macOS path) |
| 2026-05-21 | A0 fix + A1 eval refactor → pytest | 230 pass |
| 2026-05-21 | Eval smoke test (claude-haiku-4.5, 01-create-file) | PASS, 6.2s, 5905 tokens |
| 2026-05-21 | `uv run ruff check src/ tests/` | clean (1 fixed: unused asyncio import) |
| 2026-05-21 | `uv run mypy src/` | 42 pre-existing errors in 12 files |
| 2026-05-21 | Baseline eval claude-haiku-4.5 (10 tasks) | 10/10 PASS, 116,304 tokens, 0% cache |
| 2026-05-21 | Baseline eval gpt-5-mini (10 tasks) | 10/10 PASS, 174,222 tokens, 0% cache |
| 2026-05-21 | B1 sub-agent: pytest tests/ | 235 pass (+5 from A1 baseline) |
| 2026-05-21 | Full suite after C4 | 294 pass / 0 fail |
| 2026-05-21 | Final eval claude-haiku-4.5 (10 tasks) | 10/10 PASS, 114,959 tokens, 0% cache (proxy limitation), iters 34, tools 30 |
| 2026-05-21 | Final eval gpt-5-mini (10 tasks) | 9/10 PASS (task 03 hit a proxy-side `Malformed SSE payload`; targeted retry of task 03 in isolation passed), 170,229 tokens |

## Known issues to clean up later

- **mypy 42 pre-existing errors** across `cli/prompt.py`, `cli/repl.py`,
  `cli/slash_commands.py`, `providers/openai_compat.py`, `providers/anthropic.py`,
  etc. Most are missing type annotations on internal helpers and
  `dict[str, Any]` vs `dict` widening. Plan: clean up in C5 right before
  flipping mypy to strict-gating in CI. Don't add new untyped code in the
  meantime.

---

## How to resume in a new session

1. Re-read this file's "Phase status" table — pick the first 🔲 task.
2. Check `tests/conftest.py` is still stripping env vars (must be true for tests).
3. Verify the local endpoint is up: `curl http://localhost:23333/api/openai/v1/chat/completions -d '…'`.
4. Run `uv run pytest tests/ -q` to confirm the suite is still green before changing anything.
5. Continue with the chosen task. Update its status row when done.
