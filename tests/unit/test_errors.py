from __future__ import annotations

import pytest

from coding_agent.core.errors import (
    CodingAgentError,
    ConfigError,
    PermissionDenied,
    ProviderError,
    ProviderRateLimitError,
    ToolError,
    UserAborted,
)


def test_error_hierarchy() -> None:
    assert issubclass(ConfigError, CodingAgentError)
    assert issubclass(ProviderRateLimitError, ProviderError)
    assert issubclass(ProviderError, CodingAgentError)
    assert issubclass(ToolError, CodingAgentError)
    assert issubclass(PermissionDenied, CodingAgentError)
    assert issubclass(UserAborted, CodingAgentError)


def test_permission_denied_carries_tool_name() -> None:
    with pytest.raises(PermissionDenied) as ex:
        raise PermissionDenied("disallowed", tool="bash")
    assert ex.value.tool == "bash"
    assert ex.value.reason == "disallowed"
    assert "disallowed" in str(ex.value)
