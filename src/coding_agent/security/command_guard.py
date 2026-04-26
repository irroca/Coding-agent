"""Command guard — parse and classify shell commands for safety."""

from __future__ import annotations

import re
import shlex
from dataclasses import dataclass

from coding_agent.core.logging import get_logger

log = get_logger("security.command_guard")


@dataclass
class ParsedCommand:
    raw: str
    executable: str
    args: list[str]
    has_pipe: bool = False
    has_redirect: bool = False
    has_subshell: bool = False
    has_background: bool = False
    chained: list[str] | None = None


def parse_command(raw: str) -> ParsedCommand:
    """Parse a shell command string into structured components."""
    stripped = raw.strip()

    has_pipe = bool(re.search(r"(?<![|])\|(?![|])", stripped))
    has_redirect = bool(re.search(r"[<>]|>>", stripped))
    has_subshell = bool(re.search(r"\$\(|`", stripped))
    has_background = stripped.endswith("&") and not stripped.endswith("&&")

    chain_parts = re.split(r"\s*(?:&&|\|\|?|;)\s*", stripped)
    chain_parts = [p.strip() for p in chain_parts if p.strip()]

    first = chain_parts[0] if chain_parts else stripped

    try:
        tokens = shlex.split(first)
    except ValueError:
        tokens = first.split()

    executable = tokens[0] if tokens else ""
    args = tokens[1:] if len(tokens) > 1 else []

    return ParsedCommand(
        raw=stripped,
        executable=executable,
        args=args,
        has_pipe=has_pipe,
        has_redirect=has_redirect,
        has_subshell=has_subshell,
        has_background=has_background,
        chained=chain_parts if len(chain_parts) > 1 else None,
    )


DANGEROUS_EXECUTABLES = frozenset({
    "rm", "rmdir", "mkfs", "dd", "fdisk",
    "shutdown", "reboot", "halt", "poweroff",
    "kill", "killall", "pkill",
    "chmod", "chown", "chgrp",
    "mount", "umount",
    "iptables", "ip6tables", "nft",
    "useradd", "userdel", "usermod", "groupadd",
    "passwd", "su", "sudo",
    "curl", "wget",
})

SAFE_EXECUTABLES = frozenset({
    "ls", "cat", "head", "tail", "wc", "sort", "uniq",
    "find", "which", "echo", "printf", "pwd", "date",
    "git", "python", "python3", "pip", "node", "npm", "npx",
    "rg", "grep", "sed", "awk", "tr", "cut",
    "diff", "file", "stat", "du", "df",
    "uname", "whoami", "id", "env", "printenv",
    "true", "false", "test",
    "ruff", "mypy", "pytest", "cargo", "go", "make",
})


def is_dangerous(cmd: ParsedCommand) -> bool:
    """Quick heuristic: is this command potentially destructive?"""
    if cmd.executable in DANGEROUS_EXECUTABLES:
        return True
    if cmd.executable == "git" and cmd.args:
        dangerous_git = {"push", "reset", "clean", "rebase", "force-push"}
        if cmd.args[0] in dangerous_git:
            return True
        if "--force" in cmd.args or "-f" in cmd.args:
            return True
    return False


def is_safe_readonly(cmd: ParsedCommand) -> bool:
    """Is this command clearly read-only and safe to auto-allow?"""
    if cmd.has_subshell:
        return False
    if cmd.has_redirect:
        return False
    if cmd.executable not in SAFE_EXECUTABLES:
        return False
    if cmd.executable == "git" and cmd.args:
        safe_git = {"status", "diff", "log", "show", "branch", "tag", "remote", "rev-parse", "ls-files"}
        if cmd.args[0] not in safe_git:
            return False
    return True
