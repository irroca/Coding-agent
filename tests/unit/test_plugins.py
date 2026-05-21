"""Tests for the entry-point-based plugin loader.

We don't install a real plugin package — instead we forge synthetic entry
points and feed them through ``load_plugins`` to verify each group's loading
contract.
"""

from __future__ import annotations

from typing import ClassVar

from pydantic import BaseModel

import coding_agent.plugins as plugins
from coding_agent.core.types import ToolResult
from coding_agent.providers.base import LLMProvider
from coding_agent.tools.base import _TOOL_REGISTRY, Tool, ToolContext


# A throwaway third-party-style Tool that's NOT in the built-in registry on import.
class _PluginParams(BaseModel):
    message: str = "hello"


class _PluginTool(Tool, register=False):
    name: ClassVar[str] = "plugin_demo_tool"
    description: ClassVar[str] = "Demo tool loaded via entry point."
    Params: ClassVar[type[BaseModel]] = _PluginParams

    async def run(self, params: BaseModel, ctx: ToolContext) -> ToolResult:
        assert isinstance(params, _PluginParams)
        return ToolResult(call_id="", tool=self.name, ok=True, content=params.message)


# Resolving the entry point yields a Tool subclass that **does** auto-register.
# So we make the EP point at a class created on demand that re-enables registration.
def _build_registering_tool_cls() -> type[Tool]:
    class _Registering(Tool):
        name: ClassVar[str] = "plugin_demo_tool"
        description: ClassVar[str] = "Demo tool loaded via entry point."
        Params: ClassVar[type[BaseModel]] = _PluginParams

        async def run(self, params: BaseModel, ctx: ToolContext) -> ToolResult:
            return ToolResult(call_id="", tool=self.name, ok=True, content="hi")

    return _Registering


# Synthetic provider for the provider entry-point group.
class _PluginProvider(LLMProvider):
    name = "plugin_demo_provider"

    def __init__(self, config=None) -> None:  # type: ignore[no-untyped-def]
        from coding_agent.core.config import ProviderConfig

        self.config = config or ProviderConfig(api_key="x", model="m")

    @property
    def model(self) -> str:
        return "plugin-model"

    async def stream(self, messages, tools, *, temperature=None, max_tokens=None):  # type: ignore[override]
        if False:
            yield  # pragma: no cover — never iterated in this test


_SLASH_REGISTERED: list[str] = []


def _plugin_slash_register() -> None:
    """Mimic what a real plugin would do — apply @slash to its handler."""
    from coding_agent.cli.slash_commands import slash

    @slash("plugin_demo_cmd", "A slash command from a plugin")
    def _handler(**_) -> None:
        _SLASH_REGISTERED.append("called")


class _FakeEntryPoint:
    """Stand-in for importlib.metadata.EntryPoint that returns a preset object."""

    def __init__(self, name: str, value: object) -> None:
        self.name = name
        self._value = value

    def load(self) -> object:
        return self._value


def _patch_entry_points(monkeypatch, **groups: list[_FakeEntryPoint]) -> None:
    def _fake(group: str):
        return groups.get(group, [])

    monkeypatch.setattr(plugins, "_entry_points", _fake)
    plugins.reset_for_tests()


def test_tool_plugin_auto_registers(monkeypatch) -> None:
    tool_cls = _build_registering_tool_cls()
    # importing the class above already triggered __init_subclass__ → registry.
    # Drop it so we can prove load_plugins() re-asserts registration.
    _TOOL_REGISTRY.pop(tool_cls.name, None)

    _patch_entry_points(
        monkeypatch,
        **{
            plugins.GROUP_TOOLS: [_FakeEntryPoint("demo", tool_cls)],
        },
    )

    summary = plugins.load_plugins()
    assert summary[plugins.GROUP_TOOLS] == ["demo"]
    # Re-instantiate (or just re-import side effect) — the class is already
    # in the registry because resolving the EP imports it and triggers
    # __init_subclass__.
    assert "plugin_demo_tool" in _TOOL_REGISTRY

    # cleanup
    _TOOL_REGISTRY.pop(tool_cls.name, None)


def test_provider_plugin_registers_under_name(monkeypatch) -> None:
    from coding_agent.providers.registry import _REGISTRY

    _REGISTRY.pop("plugin_demo_provider", None)
    _patch_entry_points(
        monkeypatch,
        **{plugins.GROUP_PROVIDERS: [_FakeEntryPoint("demo_provider", _PluginProvider)]},
    )

    summary = plugins.load_plugins()
    assert summary[plugins.GROUP_PROVIDERS] == ["demo_provider"]
    assert _REGISTRY.get("plugin_demo_provider") is _PluginProvider

    _REGISTRY.pop("plugin_demo_provider", None)


def test_slash_plugin_invokes_register_callable(monkeypatch) -> None:
    from coding_agent.cli.slash_commands import COMMANDS

    COMMANDS.pop("plugin_demo_cmd", None)
    _patch_entry_points(
        monkeypatch,
        **{plugins.GROUP_SLASH: [_FakeEntryPoint("demo_cmd", _plugin_slash_register)]},
    )

    summary = plugins.load_plugins()
    assert summary[plugins.GROUP_SLASH] == ["demo_cmd"]
    assert "plugin_demo_cmd" in COMMANDS

    COMMANDS.pop("plugin_demo_cmd", None)


def test_broken_plugin_does_not_crash_host(monkeypatch) -> None:
    """If a plugin raises on import, we log and keep going."""

    class _BrokenEP:
        name = "broken"

        def load(self):
            raise RuntimeError("kaboom")

    _patch_entry_points(monkeypatch, **{plugins.GROUP_TOOLS: [_BrokenEP()]})
    summary = plugins.load_plugins()  # must not raise
    assert summary[plugins.GROUP_TOOLS] == []


def test_load_plugins_is_idempotent(monkeypatch) -> None:
    """Calling load_plugins twice should not re-trigger loading."""

    calls = {"tools": 0}

    class _CountingEP:
        name = "demo"

        def load(self):
            calls["tools"] += 1

            class _T(Tool, register=False):
                name = "noop"
                description = "noop"
                Params = _PluginParams

                async def run(self, params, ctx):
                    return ToolResult(call_id="", tool="noop", ok=True, content="")

            return _T

    _patch_entry_points(monkeypatch, **{plugins.GROUP_TOOLS: [_CountingEP()]})
    plugins.load_plugins()
    plugins.load_plugins()
    assert calls["tools"] == 1
