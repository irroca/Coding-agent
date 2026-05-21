"""End-to-end WebSocket test using FastAPI TestClient.

Drives a real connection through ``create_app``, with the provider monkey-
patched to a MockProvider. Asserts the full submit → text → tool_start →
confirm_request → confirm_response → tool_result → turn_end cycle.
"""

from __future__ import annotations

import json

import pytest

from coding_agent.core.config import (
    AgentConfig,
    Config,
    PermissionsConfig,
    ProviderConfig,
)
from tests.integration.test_agent_loop import MockProvider, _text_turn, _tool_turn


@pytest.fixture
def app_factory(monkeypatch, tmp_path):
    def _make(turns):
        provider = MockProvider(turns=turns)

        def _fake_build(config, override=None):
            return provider

        from coding_agent.providers import registry
        from coding_agent.web import runner as runner_module

        monkeypatch.setattr(registry, "build_provider", _fake_build)
        monkeypatch.setattr(runner_module, "build_provider", _fake_build)

        cfg = Config(
            provider="deepseek",
            workspace=tmp_path,
            providers={"deepseek": ProviderConfig(api_key="x", model="m")},
            permissions=PermissionsConfig(
                file_read="allow", file_write="ask", bash="allow",
            ),
            agent=AgentConfig(max_iterations=5),
        )
        from coding_agent.web.server import create_app
        return create_app(cfg), provider, cfg

    return _make


def _drain_until(ws, predicate, max_messages=80):
    """Pull messages until predicate returns True. Returns list of dicts."""
    seen = []
    for _ in range(max_messages):
        raw = ws.receive_text()
        msg = json.loads(raw)
        seen.append(msg)
        if predicate(msg):
            return seen
    raise AssertionError(
        f"Predicate never matched; saw {[m['type'] for m in seen]}"
    )


def test_ws_text_only_turn(app_factory):
    app, _, _ = app_factory(turns=[_text_turn("Hello!")])
    from fastapi.testclient import TestClient

    with TestClient(app) as client, client.websocket_connect("/ws/tab-test") as ws:
        initial = json.loads(ws.receive_text())
        assert initial["type"] == "session_state"

        ws.send_text(json.dumps({"type": "submit", "text": "hi"}))
        msgs = _drain_until(ws, lambda m: m["type"] == "turn_end")
        kinds = [m["type"] for m in msgs]
        assert "text_delta" in kinds
        assert "usage" in kinds


def test_ws_confirm_round_trip(app_factory, tmp_path):
    app, _, _ = app_factory(
        turns=[
            _tool_turn("write", {"file_path": "made.txt", "content": "abc"}),
            _text_turn("done"),
        ]
    )
    from fastapi.testclient import TestClient

    with TestClient(app) as client, client.websocket_connect("/ws/tab-confirm") as ws:
        initial = json.loads(ws.receive_text())
        assert initial["type"] == "session_state"

        ws.send_text(json.dumps({"type": "submit", "text": "write a file"}))
        seen = _drain_until(ws, lambda m: m["type"] == "confirm_request")
        confirm = seen[-1]

        ws.send_text(
            json.dumps(
                {
                    "type": "confirm_response",
                    "request_id": confirm["request_id"],
                    "approved": True,
                    "always": False,
                }
            )
        )

        seen = _drain_until(ws, lambda m: m["type"] == "tool_result")
        assert seen[-1]["tool_result"]["ok"] is True
        # Drain to end so we exit cleanly
        _drain_until(ws, lambda m: m["type"] == "turn_end")

    assert (tmp_path / "made.txt").read_text() == "abc"


def test_ws_attach_to_existing_session(app_factory, tmp_path):
    app, _, _ = app_factory(turns=[_text_turn("ok")])

    # Pre-seed a saved session on disk
    from coding_agent.core.session import Session
    from coding_agent.core.types import Message, Role

    sess = Session(workspace=str(tmp_path), provider="deepseek", model="m")
    sess.messages.append(Message(role=Role.USER, content="earlier message"))
    sess.save()
    sid = sess.id

    from fastapi.testclient import TestClient

    with TestClient(app) as client, client.websocket_connect("/ws/tab-resume") as ws:
        # Initial attach gives a fresh session
        json.loads(ws.receive_text())

        ws.send_text(
            json.dumps({"type": "attach_session", "session_id": sid})
        )
        state = None
        for _ in range(20):
            m = json.loads(ws.receive_text())
            if m["type"] == "session_state":
                state = m
                break
        assert state is not None
        assert state["session_id"] == sid
        assert any("earlier message" in (msg.get("content") or "") for msg in state["messages"])


def test_ws_bad_message_returns_server_error(app_factory):
    app, _, _ = app_factory(turns=[_text_turn("ok")])
    from fastapi.testclient import TestClient

    with TestClient(app) as client, client.websocket_connect("/ws/tab-bad") as ws:
        json.loads(ws.receive_text())  # initial session_state
        ws.send_text("{ not json")
        # Should not disconnect; we should keep getting messages.
        err = None
        for _ in range(5):
            msg = json.loads(ws.receive_text())
            if msg["type"] == "server_error":
                err = msg
                break
        assert err is not None
        assert "Bad message" in err["message"]


def test_ws_list_sessions(app_factory, tmp_path):
    app, _, _ = app_factory(turns=[_text_turn("ok")])
    from coding_agent.core.session import Session

    s = Session(workspace=str(tmp_path), provider="deepseek", model="m")
    s.save()

    from fastapi.testclient import TestClient

    with TestClient(app) as client, client.websocket_connect("/ws/tab-list") as ws:
        json.loads(ws.receive_text())
        ws.send_text(json.dumps({"type": "list_sessions"}))
        sl = None
        for _ in range(5):
            m = json.loads(ws.receive_text())
            if m["type"] == "session_list":
                sl = m
                break
        assert sl is not None
        assert any(item["id"] == s.id for item in sl["sessions"])
