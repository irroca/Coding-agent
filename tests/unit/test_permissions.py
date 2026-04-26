"""Tests for permission engine."""

from __future__ import annotations

from coding_agent.core.config import PermissionsConfig
from coding_agent.security.permissions import PermissionEngine
from coding_agent.security.rules import Decision, Rule, RuleSet
from coding_agent.tools.base import PermissionRequest


def _engine(
    *,
    user_rules: RuleSet | None = None,
    **kwargs,
) -> PermissionEngine:
    config = PermissionsConfig(**kwargs)
    return PermissionEngine(config, user_rules)


def test_config_default_file_read_allow() -> None:
    engine = _engine()
    req = PermissionRequest(tool="read", action="file_read", summary="Read file")
    d = engine.check(req)
    assert d.decision == Decision.ALLOW


def test_config_default_file_write_ask() -> None:
    engine = _engine()
    req = PermissionRequest(tool="write", action="file_write", summary="Write file")
    d = engine.check(req)
    assert d.decision == Decision.ASK


def test_builtin_deny_rm_rf() -> None:
    engine = _engine()
    req = PermissionRequest(
        tool="bash", action="bash", summary="Run: rm -rf /",
        command="rm -rf /",
    )
    d = engine.check(req)
    assert d.decision == Decision.DENY


def test_builtin_deny_env_write() -> None:
    engine = _engine()
    req = PermissionRequest(
        tool="write", action="file_write", summary="Write .env",
        path="project/.env",
    )
    d = engine.check(req)
    assert d.decision == Decision.DENY


def test_builtin_allow_git_status() -> None:
    engine = _engine()
    req = PermissionRequest(
        tool="bash", action="bash", summary="Run: git status",
        command="git status",
    )
    d = engine.check(req)
    assert d.decision == Decision.ALLOW


def test_user_rule_overrides_builtin_allow() -> None:
    user_rules = RuleSet(rules=[
        Rule(tool="bash", match=r"^git\s+status", decision=Decision.ASK),
    ])
    engine = _engine(user_rules=user_rules)
    req = PermissionRequest(
        tool="bash", action="bash", summary="Run: git status",
        command="git status",
    )
    d = engine.check(req)
    assert d.decision == Decision.ASK


def test_user_rule_cannot_override_builtin_deny() -> None:
    user_rules = RuleSet(rules=[
        Rule(tool="bash", match=r"rm\s+-rf\s+/", decision=Decision.ALLOW),
    ])
    engine = _engine(user_rules=user_rules)
    req = PermissionRequest(
        tool="bash", action="bash", summary="Run: rm -rf /",
        command="rm -rf /",
    )
    d = engine.check(req)
    assert d.decision == Decision.DENY


def test_command_guard_safe_command_auto_allow() -> None:
    engine = _engine()
    req = PermissionRequest(
        tool="bash", action="bash", summary="Run: cat file.txt",
        command="cat file.txt",
    )
    d = engine.check(req)
    assert d.decision == Decision.ALLOW


def test_command_guard_dangerous_command_ask() -> None:
    engine = _engine()
    req = PermissionRequest(
        tool="bash", action="bash", summary="Run: sudo apt install",
        command="sudo apt install foo",
    )
    d = engine.check(req)
    assert d.decision == Decision.ASK


def test_config_override_bash_allow() -> None:
    engine = _engine(bash="allow")
    req = PermissionRequest(
        tool="bash", action="bash", summary="Run: npm install",
        command="npm install",
    )
    d = engine.check(req)
    assert d.decision == Decision.ALLOW


def test_config_override_file_write_deny() -> None:
    engine = _engine(file_write="deny")
    req = PermissionRequest(
        tool="write", action="file_write", summary="Write file",
        path="src/main.py",
    )
    d = engine.check(req)
    assert d.decision == Decision.DENY
