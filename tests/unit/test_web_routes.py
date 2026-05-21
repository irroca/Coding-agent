"""REST route tests via FastAPI TestClient.

Doesn't open a real WebSocket — covered by test_web_e2e.py.
"""

from __future__ import annotations

import pytest

from coding_agent.core.config import (
    AgentConfig,
    Config,
    PermissionsConfig,
    ProviderConfig,
)


@pytest.fixture
def app(tmp_path):
    from fastapi.testclient import TestClient

    from coding_agent.web.server import create_app

    cfg = Config(
        provider="deepseek",
        workspace=tmp_path,
        providers={"deepseek": ProviderConfig(api_key="x", model="m")},
        permissions=PermissionsConfig(
            file_read="allow", file_write="allow", bash="allow",
        ),
        agent=AgentConfig(max_iterations=5),
    )
    app = create_app(cfg)
    with TestClient(app) as client:
        yield client


def test_get_config(app):
    r = app.get("/api/config")
    assert r.status_code == 200
    data = r.json()
    assert data["provider"] == "deepseek"
    assert data["model"] == "m"
    assert "api_key" not in str(data)


def test_get_sessions_empty_or_list(app):
    r = app.get("/api/sessions")
    assert r.status_code == 200
    assert isinstance(r.json(), list)


def test_get_session_404(app):
    r = app.get("/api/sessions/does-not-exist")
    assert r.status_code == 404


def test_delete_session_404(app):
    r = app.delete("/api/sessions/does-not-exist")
    assert r.status_code == 404


def test_list_workspaces_contains_current(app):
    r = app.get("/api/workspaces")
    assert r.status_code == 200
    body = r.json()
    assert "current" in body
    assert isinstance(body["recent"], list)


def test_list_tools(app):
    r = app.get("/api/tools")
    assert r.status_code == 200
    names = {t["name"] for t in r.json()}
    # A few built-ins must be present
    assert "read" in names
    assert "bash" in names
    assert "write" in names
