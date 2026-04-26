"""Permission rules DSL — allow / ask / deny with pattern matching.

Rules are evaluated top-to-bottom; first match wins. If no rule matches,
the default for that action category (from PermissionsConfig) applies.

Rule format (YAML):
  - tool: bash
    match: "^git (status|diff|log|show)\\b"
    decision: allow
  - tool: write
    path: "**/.env*"
    decision: deny
"""

from __future__ import annotations

import fnmatch
import re
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

from coding_agent.core.logging import get_logger

log = get_logger("security.rules")


class Decision(StrEnum):
    ALLOW = "allow"
    ASK = "ask"
    DENY = "deny"


@dataclass
class Rule:
    tool: str | None = None
    action: str | None = None
    match: str | None = None
    path: str | None = None
    decision: Decision = Decision.ASK

    _compiled_match: re.Pattern[str] | None = field(
        default=None, repr=False, init=False,
    )

    def __post_init__(self) -> None:
        if self.match:
            try:
                self._compiled_match = re.compile(self.match)
            except re.error as e:
                log.warning("invalid_rule_regex", pattern=self.match, error=str(e))
                self._compiled_match = None

    def matches(
        self,
        *,
        tool_name: str,
        action: str,
        command: str | None = None,
        path: str | None = None,
    ) -> bool:
        if self.tool and self.tool != tool_name:
            return False
        if self.action and self.action != action:
            return False
        if self.match:
            target = command or ""
            if not self._compiled_match:
                return False
            if not self._compiled_match.search(target):
                return False
        if self.path:
            target_path = path or ""
            if not fnmatch.fnmatch(target_path, self.path):
                return False
        return True


@dataclass
class RuleSet:
    rules: list[Rule] = field(default_factory=list)

    def evaluate(
        self,
        *,
        tool_name: str,
        action: str,
        command: str | None = None,
        path: str | None = None,
    ) -> Decision | None:
        for rule in self.rules:
            if rule.matches(
                tool_name=tool_name, action=action,
                command=command, path=path,
            ):
                return rule.decision
        return None

    @classmethod
    def from_list(cls, raw: list[dict[str, Any]]) -> RuleSet:
        rules: list[Rule] = []
        for entry in raw:
            try:
                rules.append(Rule(
                    tool=entry.get("tool"),
                    action=entry.get("action"),
                    match=entry.get("match"),
                    path=entry.get("path"),
                    decision=Decision(entry.get("decision", "ask")),
                ))
            except (ValueError, TypeError) as e:
                log.warning("skipping_invalid_rule", entry=entry, error=str(e))
        return cls(rules=rules)

    @classmethod
    def from_yaml_file(cls, path: str) -> RuleSet:
        from pathlib import Path

        import yaml

        p = Path(path)
        if not p.is_file():
            return cls()
        try:
            data = yaml.safe_load(p.read_text(encoding="utf-8"))
        except Exception as e:
            log.warning("failed_to_load_rules", path=path, error=str(e))
            return cls()
        if not isinstance(data, list):
            data = data.get("rules", []) if isinstance(data, dict) else []
        return cls.from_list(data)


# Built-in safety rules that are always prepended.
BUILTIN_DENY_RULES = RuleSet(rules=[
    Rule(tool="bash", match=r"rm\s+-rf\s+/\s*$", decision=Decision.DENY),
    Rule(tool="bash", match=r"mkfs\.", decision=Decision.DENY),
    Rule(tool="bash", match=r"dd\s+if=.+of=/dev/", decision=Decision.DENY),
    Rule(tool="bash", match=r":(){ :\|:& };:", decision=Decision.DENY),
    Rule(tool="write", path="**/.env", decision=Decision.DENY),
    Rule(tool="write", path="**/.env.*", decision=Decision.DENY),
    Rule(tool="write", path="**/id_rsa*", decision=Decision.DENY),
    Rule(tool="write", path="**/*.pem", decision=Decision.DENY),
])

BUILTIN_ALLOW_RULES = RuleSet(rules=[
    Rule(tool="bash", match=r"^git\s+(status|diff|log|show|branch)\b", decision=Decision.ALLOW),
    Rule(tool="bash", match=r"^(ls|cat|head|tail|wc|find|which|echo|pwd|date)\b", decision=Decision.ALLOW),
    Rule(tool="bash", match=r"^python\s+-m\s+(pytest|ruff|mypy)\b", decision=Decision.ALLOW),
])
