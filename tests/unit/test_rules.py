"""Tests for security rules DSL."""

from __future__ import annotations

from coding_agent.security.rules import (
    BUILTIN_ALLOW_RULES,
    BUILTIN_DENY_RULES,
    Decision,
    Rule,
    RuleSet,
)


def test_rule_matches_tool_name() -> None:
    rule = Rule(tool="bash", decision=Decision.ALLOW)
    assert rule.matches(tool_name="bash", action="bash")
    assert not rule.matches(tool_name="write", action="file_write")


def test_rule_matches_command_regex() -> None:
    rule = Rule(tool="bash", match=r"^git\s+status", decision=Decision.ALLOW)
    assert rule.matches(tool_name="bash", action="bash", command="git status")
    assert not rule.matches(tool_name="bash", action="bash", command="git push")


def test_rule_matches_path_glob() -> None:
    rule = Rule(tool="write", path="**/.env*", decision=Decision.DENY)
    assert rule.matches(tool_name="write", action="file_write", path="src/.env")
    assert rule.matches(tool_name="write", action="file_write", path="config/.env.local")
    assert not rule.matches(tool_name="write", action="file_write", path="src/main.py")


def test_rule_matches_action() -> None:
    rule = Rule(action="file_write", decision=Decision.ASK)
    assert rule.matches(tool_name="write", action="file_write")
    assert rule.matches(tool_name="edit", action="file_write")
    assert not rule.matches(tool_name="read", action="file_read")


def test_ruleset_first_match_wins() -> None:
    rs = RuleSet(rules=[
        Rule(tool="bash", match=r"^git\s+status", decision=Decision.ALLOW),
        Rule(tool="bash", decision=Decision.DENY),
    ])
    assert rs.evaluate(tool_name="bash", action="bash", command="git status") == Decision.ALLOW
    assert rs.evaluate(tool_name="bash", action="bash", command="rm -rf /") == Decision.DENY


def test_ruleset_no_match_returns_none() -> None:
    rs = RuleSet(rules=[Rule(tool="bash", decision=Decision.ALLOW)])
    assert rs.evaluate(tool_name="write", action="file_write") is None


def test_ruleset_from_list() -> None:
    rs = RuleSet.from_list([
        {"tool": "bash", "match": "^echo", "decision": "allow"},
        {"tool": "write", "path": "*.py", "decision": "ask"},
    ])
    assert len(rs.rules) == 2
    assert rs.rules[0].decision == Decision.ALLOW


def test_ruleset_from_list_skips_invalid() -> None:
    rs = RuleSet.from_list([
        {"tool": "bash", "decision": "not_a_decision"},
        {"tool": "write", "decision": "allow"},
    ])
    assert len(rs.rules) == 1


def test_builtin_deny_blocks_rm_rf() -> None:
    result = BUILTIN_DENY_RULES.evaluate(
        tool_name="bash", action="bash", command="rm -rf /",
    )
    assert result == Decision.DENY


def test_builtin_deny_blocks_env_write() -> None:
    result = BUILTIN_DENY_RULES.evaluate(
        tool_name="write", action="file_write", path="config/.env",
    )
    assert result == Decision.DENY


def test_builtin_allow_git_status() -> None:
    result = BUILTIN_ALLOW_RULES.evaluate(
        tool_name="bash", action="bash", command="git status",
    )
    assert result == Decision.ALLOW


def test_builtin_allow_pytest() -> None:
    result = BUILTIN_ALLOW_RULES.evaluate(
        tool_name="bash", action="bash", command="python -m pytest tests/",
    )
    assert result == Decision.ALLOW


def test_invalid_regex_doesnt_crash() -> None:
    rule = Rule(tool="bash", match="[invalid", decision=Decision.ALLOW)
    assert not rule.matches(tool_name="bash", action="bash", command="anything")
