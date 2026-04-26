"""Tests for slash commands."""

from __future__ import annotations

from unittest.mock import MagicMock

from rich.console import Console

from coding_agent.cli.slash_commands import COMMANDS, dispatch_slash
from coding_agent.core.session import Session
from coding_agent.core.types import Usage


def _console() -> Console:
    return Console(file=MagicMock(), force_terminal=True)


def _session(tmp_path) -> Session:
    return Session(
        workspace=str(tmp_path),
        provider="mock",
        model="mock-model",
        usage=Usage(prompt_tokens=100, completion_tokens=50),
    )


def test_all_commands_registered() -> None:
    expected = {"help", "clear", "cost", "model", "exit", "compact", "history", "sessions", "permissions", "tools"}
    assert expected.issubset(set(COMMANDS.keys()))


def test_dispatch_help(tmp_path) -> None:
    result = dispatch_slash("/help", console=_console(), session=_session(tmp_path))
    assert result is None


def test_dispatch_exit(tmp_path) -> None:
    result = dispatch_slash("/exit", console=_console(), session=_session(tmp_path))
    assert result is True


def test_dispatch_unknown(tmp_path) -> None:
    result = dispatch_slash("/nonexistent", console=_console(), session=_session(tmp_path))
    assert result is None


def test_dispatch_cost(tmp_path) -> None:
    result = dispatch_slash("/cost", console=_console(), session=_session(tmp_path))
    assert result is None


def test_dispatch_history(tmp_path) -> None:
    s = _session(tmp_path)
    s.add_system("sys")
    s.add_user("hi")
    result = dispatch_slash("/history", console=_console(), session=s)
    assert result is None


def test_dispatch_compact(tmp_path) -> None:
    s = _session(tmp_path)
    s.add_user("hi")
    result = dispatch_slash("/compact", console=_console(), session=s)
    assert result is None


def test_dispatch_permissions(tmp_path) -> None:
    result = dispatch_slash("/permissions", console=_console(), session=_session(tmp_path))
    assert result is None


def test_dispatch_tools(tmp_path) -> None:
    result = dispatch_slash("/tools", console=_console(), session=_session(tmp_path))
    assert result is None
