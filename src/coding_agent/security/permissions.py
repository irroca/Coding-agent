"""Permission engine — combines config defaults, rules, and command analysis.

This is the single entry point the orchestrator calls. It returns a Decision
(allow / ask / deny) plus a reason string for audit and UI.
"""

from __future__ import annotations

from dataclasses import dataclass

from coding_agent.core.config import PermissionsConfig
from coding_agent.core.logging import get_logger
from coding_agent.security.command_guard import is_dangerous, is_safe_readonly, parse_command
from coding_agent.security.rules import (
    BUILTIN_ALLOW_RULES,
    BUILTIN_DENY_RULES,
    Decision,
    RuleSet,
)
from coding_agent.tools.base import PermissionRequest

log = get_logger("security.permissions")


@dataclass
class PermissionDecision:
    decision: Decision
    reason: str


class PermissionEngine:
    """Evaluates permission requests against layered rules.

    Evaluation order:
      1. Built-in deny rules (non-overridable safety nets)
      2. User-defined rules (from config / YAML)
      3. Built-in allow rules (convenience auto-approvals)
      4. Command guard heuristics (for bash)
      5. Config defaults (file_read=allow, file_write=ask, bash=ask, network=ask)
    """

    def __init__(
        self,
        config: PermissionsConfig,
        user_rules: RuleSet | None = None,
    ) -> None:
        self.config = config
        self.user_rules = user_rules or RuleSet()

    def check(self, req: PermissionRequest) -> PermissionDecision:
        tool_name = req.tool
        action = req.action
        command = req.command
        path = req.path

        # 1. Built-in deny rules
        result = BUILTIN_DENY_RULES.evaluate(
            tool_name=tool_name, action=action,
            command=command, path=path,
        )
        if result == Decision.DENY:
            return PermissionDecision(Decision.DENY, "Blocked by built-in safety rule")

        # 2. User-defined rules
        result = self.user_rules.evaluate(
            tool_name=tool_name, action=action,
            command=command, path=path,
        )
        if result is not None:
            return PermissionDecision(result, "Matched user-defined rule")

        # 3. Built-in allow rules
        result = BUILTIN_ALLOW_RULES.evaluate(
            tool_name=tool_name, action=action,
            command=command, path=path,
        )
        if result == Decision.ALLOW:
            return PermissionDecision(Decision.ALLOW, "Matched built-in allow rule")

        # 4. Command guard heuristics for bash
        if action == "bash" and command:
            parsed = parse_command(command)
            if is_dangerous(parsed):
                return PermissionDecision(Decision.ASK, f"Potentially dangerous command: {parsed.executable}")
            if is_safe_readonly(parsed):
                return PermissionDecision(Decision.ALLOW, f"Safe read-only command: {parsed.executable}")

        # 5. Config defaults
        default = self._config_default(action)
        return PermissionDecision(default, "Config default")

    def _config_default(self, action: str) -> Decision:
        mapping = {
            "file_read": self.config.file_read,
            "file_write": self.config.file_write,
            "bash": self.config.bash,
            "network": self.config.network,
        }
        val = mapping.get(action, "ask")
        return Decision(val)
