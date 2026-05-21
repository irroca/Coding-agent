"""Round-trip parsing of every protocol message variant."""

from __future__ import annotations

import json
from datetime import UTC, datetime

import pytest

from coding_agent.core.types import Role, ToolCall, ToolResult, Usage
from coding_agent.web.protocol import (
    Ack,
    AttachSession,
    Cancel,
    ConfirmRequest,
    ConfirmResponse,
    DeleteSession,
    ErrorEvent,
    ListSessions,
    ListWorkspaces,
    ServerError,
    SessionList,
    SessionMessageSnapshot,
    SessionState,
    SessionSummary,
    Submit,
    TextDeltaEvent,
    ToolResultEvent,
    ToolStartEvent,
    TurnEndEvent,
    UsageEvent,
    WorkspaceInfo,
    WorkspaceList,
    parse_client_message,
)


def _roundtrip(obj):
    """Dump → reload via JSON to prove wire format is stable."""
    raw = obj.model_dump(mode="json")
    json_blob = json.dumps(raw, default=str)
    return json.loads(json_blob)


def test_text_delta_event() -> None:
    e = TextDeltaEvent(text="hello")
    d = _roundtrip(e)
    assert d == {"type": "text_delta", "text": "hello"}


def test_tool_start_carries_full_call() -> None:
    e = ToolStartEvent(tool_call=ToolCall(id="tc-1", name="bash", arguments={"command": "ls"}))
    d = _roundtrip(e)
    assert d["type"] == "tool_start"
    assert d["tool_call"]["name"] == "bash"
    assert d["tool_call"]["arguments"] == {"command": "ls"}


def test_tool_result_carries_metadata() -> None:
    tr = ToolResult(
        call_id="tc-1",
        tool="bash",
        ok=True,
        content="output",
        metadata={"exit_code": 0},
    )
    e = ToolResultEvent(tool_result=tr)
    d = _roundtrip(e)
    assert d["tool_result"]["ok"] is True
    assert d["tool_result"]["metadata"] == {"exit_code": 0}


def test_usage_event_with_cache_fields() -> None:
    e = UsageEvent(
        usage=Usage(
            prompt_tokens=1000,
            completion_tokens=200,
            cached_prompt_tokens=800,
            cache_creation_tokens=50,
        )
    )
    d = _roundtrip(e)
    assert d["usage"]["cached_prompt_tokens"] == 800
    assert d["usage"]["cache_creation_tokens"] == 50


def test_turn_end_optional_reason() -> None:
    assert _roundtrip(TurnEndEvent())["finish_reason"] is None
    assert _roundtrip(TurnEndEvent(finish_reason="stop"))["finish_reason"] == "stop"


def test_error_event_required() -> None:
    d = _roundtrip(ErrorEvent(error="boom"))
    assert d == {"type": "error", "error": "boom"}


def test_confirm_request_with_diff() -> None:
    e = ConfirmRequest(
        request_id="abc12345",
        tool_name="write",
        summary="Write file: x.py",
        diff_preview="@@ -1 +1 @@\n-old\n+new",
    )
    d = _roundtrip(e)
    assert d["request_id"] == "abc12345"
    assert "diff_preview" in d


def test_session_state_serializes_messages() -> None:
    msgs = [
        SessionMessageSnapshot(role=Role.USER, content="hi", created_at=datetime.now(UTC)),
        SessionMessageSnapshot(
            role=Role.ASSISTANT,
            content="hello",
            tool_calls=[ToolCall(id="t", name="ls", arguments={})],
            created_at=datetime.now(UTC),
        ),
    ]
    s = SessionState(
        session_id="s1",
        workspace="/tmp",
        provider="deepseek",
        model="m",
        messages=msgs,
        usage=Usage(prompt_tokens=10, completion_tokens=5),
        created_at=datetime.now(UTC),
        auto_approved=["bash"],
    )
    d = _roundtrip(s)
    assert d["session_id"] == "s1"
    assert len(d["messages"]) == 2
    assert d["messages"][1]["tool_calls"][0]["name"] == "ls"
    assert d["auto_approved"] == ["bash"]


def test_session_list_with_summaries() -> None:
    sl = SessionList(
        sessions=[
            SessionSummary(
                id="s1",
                created_at=datetime.now(UTC),
                title="fix bug",
                message_count=5,
            )
        ]
    )
    d = _roundtrip(sl)
    assert d["sessions"][0]["title"] == "fix bug"


def test_workspace_list() -> None:
    wl = WorkspaceList(
        current="/a",
        recent=[
            WorkspaceInfo(path="/a", last_used=datetime.now(UTC)),
            WorkspaceInfo(path="/b"),
        ],
    )
    d = _roundtrip(wl)
    assert d["current"] == "/a"
    assert d["recent"][1]["last_used"] is None


def test_ack_with_detail() -> None:
    d = _roundtrip(Ack(of="submit", detail={"queue_size": 1}))
    assert d == {"type": "ack", "of": "submit", "detail": {"queue_size": 1}}


def test_server_error() -> None:
    d = _roundtrip(ServerError(message="boom", recoverable=False))
    assert d["recoverable"] is False


# ─── client → server discrimination ─────────────────────────────────


def test_parse_submit() -> None:
    msg = parse_client_message({"type": "submit", "text": "hi"})
    assert isinstance(msg, Submit)
    assert msg.text == "hi"


def test_parse_cancel() -> None:
    msg = parse_client_message({"type": "cancel"})
    assert isinstance(msg, Cancel)


def test_parse_confirm_response_with_always() -> None:
    msg = parse_client_message(
        {"type": "confirm_response", "request_id": "x", "approved": True, "always": True}
    )
    assert isinstance(msg, ConfirmResponse)
    assert msg.always is True


def test_parse_attach_session_with_none_id() -> None:
    msg = parse_client_message({"type": "attach_session"})
    assert isinstance(msg, AttachSession)
    assert msg.session_id is None
    assert msg.workspace is None


def test_parse_attach_session_with_workspace() -> None:
    msg = parse_client_message(
        {"type": "attach_session", "session_id": "s1", "workspace": "/tmp"}
    )
    assert isinstance(msg, AttachSession)
    assert msg.workspace == "/tmp"


def test_parse_delete_session() -> None:
    msg = parse_client_message({"type": "delete_session", "session_id": "s1"})
    assert isinstance(msg, DeleteSession)


def test_parse_list_sessions() -> None:
    assert isinstance(parse_client_message({"type": "list_sessions"}), ListSessions)


def test_parse_list_workspaces() -> None:
    assert isinstance(parse_client_message({"type": "list_workspaces"}), ListWorkspaces)


def test_parse_unknown_type_rejected() -> None:
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        parse_client_message({"type": "nope"})


def test_parse_extra_field_rejected() -> None:
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        parse_client_message({"type": "submit", "text": "x", "rogue": 1})
