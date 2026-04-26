"""Tests for command guard."""

from __future__ import annotations

from coding_agent.security.command_guard import (
    is_dangerous,
    is_safe_readonly,
    parse_command,
)


def test_parse_simple_command() -> None:
    cmd = parse_command("ls -la")
    assert cmd.executable == "ls"
    assert cmd.args == ["-la"]
    assert not cmd.has_pipe
    assert not cmd.has_redirect


def test_parse_piped_command() -> None:
    cmd = parse_command("cat file.txt | grep hello")
    assert cmd.has_pipe
    assert cmd.executable == "cat"


def test_parse_redirect() -> None:
    cmd = parse_command("echo hello > out.txt")
    assert cmd.has_redirect


def test_parse_subshell() -> None:
    cmd = parse_command("echo $(whoami)")
    assert cmd.has_subshell


def test_parse_background() -> None:
    cmd = parse_command("sleep 100 &")
    assert cmd.has_background


def test_parse_chained() -> None:
    cmd = parse_command("git status && git diff")
    assert cmd.chained is not None
    assert len(cmd.chained) == 2


def test_parse_and_not_background() -> None:
    cmd = parse_command("a && b")
    assert not cmd.has_background


def test_is_dangerous_rm() -> None:
    assert is_dangerous(parse_command("rm -rf /tmp/stuff"))


def test_is_dangerous_sudo() -> None:
    assert is_dangerous(parse_command("sudo apt install foo"))


def test_is_dangerous_git_push() -> None:
    assert is_dangerous(parse_command("git push origin main"))


def test_is_dangerous_git_force() -> None:
    assert is_dangerous(parse_command("git push --force"))


def test_is_safe_ls() -> None:
    assert is_safe_readonly(parse_command("ls -la"))


def test_is_safe_git_status() -> None:
    assert is_safe_readonly(parse_command("git status"))


def test_is_safe_git_diff() -> None:
    assert is_safe_readonly(parse_command("git diff"))


def test_not_safe_with_subshell() -> None:
    assert not is_safe_readonly(parse_command("echo $(rm -rf /)"))


def test_not_safe_with_redirect() -> None:
    assert not is_safe_readonly(parse_command("ls > out.txt"))


def test_not_safe_unknown() -> None:
    assert not is_safe_readonly(parse_command("some_custom_binary"))


def test_not_safe_git_push() -> None:
    assert not is_safe_readonly(parse_command("git push"))
