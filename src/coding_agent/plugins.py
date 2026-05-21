"""Plugin loader — pull in third-party tools / providers / slash commands.

Plugins are discovered via Python's standard ``importlib.metadata.entry_points``
mechanism. To publish a plugin, add an entry-point group in your own
``pyproject.toml``::

    [project.entry-points."coding_agent.tools"]
    my_tool = "my_package.tools:MyTool"

    [project.entry-points."coding_agent.providers"]
    my_provider = "my_package.providers:MyProvider"

    [project.entry-points."coding_agent.slash_commands"]
    my_command = "my_package.slash:register"  # callable that does the @slash work

Three groups are honoured:

- ``coding_agent.tools`` — each entry must resolve to a ``Tool`` subclass.
  Importing the module is enough for ``__init_subclass__`` to register it.
- ``coding_agent.providers`` — entry resolves to an ``LLMProvider`` subclass;
  loader registers it in the provider registry under its ``name`` attribute.
- ``coding_agent.slash_commands`` — entry resolves to a *callable* that
  performs whatever registration it needs (usually applying ``@slash`` to a
  handler).

Loading is best-effort: a broken plugin logs a warning but does not crash the
host. ``load_plugins()`` is idempotent and safe to call from REPL startup.
"""

from __future__ import annotations

from importlib import metadata
from typing import Any

from coding_agent.core.logging import get_logger

log = get_logger("plugins")

_loaded: bool = False

GROUP_TOOLS = "coding_agent.tools"
GROUP_PROVIDERS = "coding_agent.providers"
GROUP_SLASH = "coding_agent.slash_commands"


def load_plugins() -> dict[str, list[str]]:
    """Discover and load all third-party plugins.

    Returns a dict keyed by group name with the list of entry-point names
    successfully loaded — useful for CLI introspection and tests.
    """
    global _loaded

    summary: dict[str, list[str]] = {
        GROUP_TOOLS: [],
        GROUP_PROVIDERS: [],
        GROUP_SLASH: [],
    }

    if _loaded:
        return summary

    summary[GROUP_TOOLS] = _load_tool_entry_points()
    summary[GROUP_PROVIDERS] = _load_provider_entry_points()
    summary[GROUP_SLASH] = _load_slash_entry_points()

    _loaded = True
    return summary


def _entry_points(group: str) -> Any:
    try:
        return metadata.entry_points(group=group)
    except TypeError:  # Python <3.10 fallback (we require 3.11, but be defensive)
        return metadata.entry_points().get(group, [])  # type: ignore[attr-defined]


def _load_tool_entry_points() -> list[str]:
    """Loading a Tool subclass entry point.

    Importing the module triggers ``Tool.__init_subclass__`` which auto-
    registers. We also defensively insert it into ``_TOOL_REGISTRY`` directly
    so a class that opted out of auto-registration (``register=False``) still
    becomes available — explicit registration via the entry-point is consent.
    """
    from coding_agent.tools.base import _TOOL_REGISTRY, Tool

    loaded: list[str] = []
    for ep in _entry_points(GROUP_TOOLS):
        try:
            tool_cls = ep.load()
        except Exception as e:
            log.warning("plugin_tool_load_failed", entry=ep.name, error=str(e))
            continue
        if not isinstance(tool_cls, type) or not issubclass(tool_cls, Tool):
            log.warning("plugin_tool_not_a_tool", entry=ep.name)
            continue
        name = getattr(tool_cls, "name", None)
        if not name:
            log.warning("plugin_tool_missing_name", entry=ep.name)
            continue
        _TOOL_REGISTRY[name] = tool_cls
        log.info("plugin_tool_loaded", entry=ep.name, cls=name)
        loaded.append(ep.name)
    return loaded


def _load_provider_entry_points() -> list[str]:
    from coding_agent.providers.registry import _REGISTRY

    loaded: list[str] = []
    for ep in _entry_points(GROUP_PROVIDERS):
        try:
            provider_cls = ep.load()
        except Exception as e:
            log.warning("plugin_provider_load_failed", entry=ep.name, error=str(e))
            continue
        name = getattr(provider_cls, "name", None)
        if not name:
            log.warning("plugin_provider_missing_name", entry=ep.name)
            continue
        _REGISTRY[name] = provider_cls
        log.info("plugin_provider_loaded", entry=ep.name, name=name)
        loaded.append(ep.name)
    return loaded


def _load_slash_entry_points() -> list[str]:
    loaded: list[str] = []
    for ep in _entry_points(GROUP_SLASH):
        try:
            register = ep.load()
        except Exception as e:
            log.warning("plugin_slash_load_failed", entry=ep.name, error=str(e))
            continue
        if not callable(register):
            log.warning("plugin_slash_not_callable", entry=ep.name)
            continue
        try:
            register()
        except Exception as e:
            log.warning("plugin_slash_register_failed", entry=ep.name, error=str(e))
            continue
        log.info("plugin_slash_loaded", entry=ep.name)
        loaded.append(ep.name)
    return loaded


def reset_for_tests() -> None:
    """Re-enable load_plugins(); intended only for the test suite."""
    global _loaded
    _loaded = False
