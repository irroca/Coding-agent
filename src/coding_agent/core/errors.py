"""Custom exception hierarchy for the coding agent.

A flat-ish hierarchy keeps `except` blocks readable while still letting callers
distinguish recoverable user-facing errors from internal bugs.
"""

from __future__ import annotations


class CodingAgentError(Exception):
    """Base class for all errors raised by the coding agent."""


class ConfigError(CodingAgentError):
    """Configuration is missing or invalid."""


class ProviderError(CodingAgentError):
    """An LLM provider call failed."""


class ProviderRateLimitError(ProviderError):
    """The provider returned a rate-limit response."""


class ProviderAuthError(ProviderError):
    """The provider rejected the API key."""


class ProviderProtocolError(ProviderError):
    """The provider returned a payload we cannot parse."""


class ToolError(CodingAgentError):
    """Base class for errors raised while running a tool."""


class ToolValidationError(ToolError):
    """Tool input failed schema validation."""


class ToolExecutionError(ToolError):
    """Tool execution failed at runtime."""


class PermissionDenied(CodingAgentError):  # noqa: N818 - intentional name without Error suffix
    """A permission rule denied the requested action."""

    def __init__(self, reason: str, *, tool: str | None = None) -> None:
        super().__init__(reason)
        self.reason = reason
        self.tool = tool


class UserAborted(CodingAgentError):  # noqa: N818 - intentional name without Error suffix
    """The user cancelled an operation (e.g. declined a permission prompt)."""


class ContextOverflowError(CodingAgentError):
    """Context window cannot be reduced enough to continue."""
