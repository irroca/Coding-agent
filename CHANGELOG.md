# Changelog

All notable changes to this project are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and the project
adheres to [Semantic Versioning](https://semver.org/).

## [Unreleased]

### Added

- **Real sub-agent dispatch** (`task` tool). A sub-agent runs in an isolated
  `Session`, has a read-only tool surface (`read` / `ls` / `glob` / `grep`),
  and cannot recursively dispatch itself. Only the final assistant text is
  returned to the parent — intermediate tool traffic stays in the sub-session.
- **Prompt caching** is now opt-in per provider via
  `ProviderConfig.supports_prompt_cache` (on by default for Anthropic, OpenAI,
  DeepSeek). Anthropic gets explicit `cache_control` on the system prompt and
  on the last tool. `Usage` exposes `cached_prompt_tokens`,
  `cache_creation_tokens`, and a `cache_hit_rate` property; `/cost` shows it.
- **Streaming tool dispatch** (`AgentConfig.streaming_tool_dispatch`, default
  on). Tools fire the moment `TOOL_USE_END` arrives instead of waiting for the
  LLM stream to finish, letting tools run concurrently with model output.
- **MCP integration**: `coding-agent-mcp` console script exposes our built-in
  tools as an MCP server. `Config.mcp_servers` connects to external MCP
  servers at startup and injects their tools as `mcp__<server>__<tool>`.
- **Docker sandbox driver** for the bash tool
  (`AgentConfig.bash_driver = "docker"`). Each command runs in a throwaway
  container with `--rm --network none --cpus 2 --memory 1g --security-opt
  no-new-privileges` and the workspace mounted at `/workspace`.
- **Eval framework** got real-endpoint support: `--base-url`, `--model`, and
  `--report` flags; `TaskMetrics` captures iteration count, tool-call
  histogram, prompt/completion/cached tokens, and cache hit rate. Baselines
  for claude-haiku-4.5 and gpt-5-mini live in `docs/eval-reports/`.
- **UX commands**: `/diff` shows cumulative per-file diffs for the session,
  `/undo` reverts the last write or edit, `coding-agent sessions --grep`
  filters historical sessions by message content.
- **CI/CD**: GitHub Actions matrix (Ubuntu × macOS, Python 3.11/3.12),
  release workflow that publishes to PyPI on `v*.*.*` tags via trusted
  publishing and pushes a Docker image to GHCR.
- Optional extras: `[mcp]`, `[docker]`, `[all]`.

### Changed

- **Removed `network` permission category.** No tool ever used it. The
  configuration field is gone; rules referencing it should switch to `bash`.
- **`PermissionRequest.action`** is now one of `file_read | file_write |
  bash`. The remote MCP tools default to `bash` because we cannot statically
  characterise their side effects.
- **Anthropic usage normalisation**: `prompt_tokens` now includes
  `cache_read_input_tokens + cache_creation_input_tokens` so it stays
  comparable to OpenAI's semantics.

### Fixed

- `evals/runner.py` no longer references the non-existent `create_provider`
  symbol (was a `NameError` at task-run time).
- `test_allow_outside_flag` now works on macOS where `/etc → /private/etc`
  is a symlink.

## [0.1.0] - 2026-05-19

Initial scaffold: tools, providers, REPL, permission engine, eval framework.
