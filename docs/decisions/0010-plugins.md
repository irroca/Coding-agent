# ADR 0010 — Plugin system via entry_points

Date: 2026-05-21
Status: Accepted (C3)

## Context

Users want to extend Coding Agent with custom tools (their company's
internal API), custom providers (their on-prem LLM), and custom slash
commands — without forking the codebase.

Three viable mechanisms in Python:

1. **`importlib.metadata.entry_points`** — declarative, packaged via
   `pyproject.toml`, no import-time hooks on the host side.
2. **Folder scanning** (`~/.coding_agent/plugins/*.py`) — easy to
   prototype, hard to version.
3. **Explicit imports in user YAML config** — needs `exec` or `importlib`
   inside config loading, fragile.

## Decision

- Use `entry_points`. Three groups:
  - `coding_agent.tools` — values are `Tool` subclasses or modules whose
    import auto-registers tools.
  - `coding_agent.providers` — values are `LLMProvider` subclasses;
    registered into `providers.registry._REGISTRY` under the entry-point
    name.
  - `coding_agent.slash_commands` — values are functions decorated with
    `@slash(...)` or modules whose import registers commands.
- `coding_agent.plugins.load_plugins()` is called once at REPL startup,
  *before* the provider is built, so plugin providers are available to
  `--provider <name>`.
- Loader is **defensive**: any plugin that raises during load is logged
  with a warning and skipped. A bad third-party plugin must not crash
  the host.
- Loader is **idempotent**: calling it twice is a no-op; covered by a unit
  test.

## Consequences

- Third parties can `pip install coding-agent-plugin-foo` and have it
  appear in `/tools` without code changes here.
- The `Tool` ABC's `__init_subclass__` auto-registration means plugin
  modules don't need explicit `register()` calls — importing them is
  enough.
- Adds zero runtime overhead when no plugins are installed.

## Alternatives considered

- **Folder scanning** — rejected; entry_points has the same UX with
  installer-driven version pinning for free.
- **Allow plugins via YAML `plugins:` list** — rejected; would re-create
  PYTHONPATH problems that pip already solves.
