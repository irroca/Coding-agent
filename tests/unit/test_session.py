from __future__ import annotations

from coding_agent.core.session import Session
from coding_agent.core.types import ToolCall, ToolResult, Usage


def _make() -> Session:
    return Session(workspace="/tmp/ws", provider="deepseek", model="deepseek-chat")


def test_session_id_is_timestamped() -> None:
    s = _make()
    assert len(s.id) > 16
    assert "-" in s.id


def test_add_user_then_assistant_then_tools() -> None:
    s = _make()
    s.add_user("do X")
    s.add_assistant("ok", tool_calls=[ToolCall(name="bash", arguments={"command": "ls"})])
    s.add_tool_results(
        [ToolResult(call_id="abc", tool="bash", ok=True, content="file1\nfile2")]
    )
    assert [m.role.value for m in s.messages] == ["user", "assistant", "tool"]
    assert s.messages[1].tool_calls[0].name == "bash"


def test_accumulate_usage() -> None:
    s = _make()
    s.accumulate_usage(Usage(prompt_tokens=10, completion_tokens=3))
    s.accumulate_usage(Usage(prompt_tokens=5, completion_tokens=7, cached_prompt_tokens=2))
    assert s.usage.prompt_tokens == 15
    assert s.usage.completion_tokens == 10
    assert s.usage.cached_prompt_tokens == 2


def test_save_and_load_round_trip() -> None:
    s = _make()
    s.add_user("hello")
    path = s.save()
    assert path.is_file()
    loaded = Session.load(s.id)
    assert loaded.id == s.id
    assert loaded.messages[0].content == "hello"


def test_list_recent_returns_saved() -> None:
    s = _make()
    s.add_user("hi")
    s.save()
    rows = Session.list_recent(limit=5)
    ids = [sid for sid, _ in rows]
    assert s.id in ids
    for _, ts in rows:
        assert ts.tzinfo is not None
