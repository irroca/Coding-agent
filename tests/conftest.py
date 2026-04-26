"""Test fixtures and helpers shared across the test suite."""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest

from coding_agent.core.config import reset_config_cache


@pytest.fixture(autouse=True)
def _isolated_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """Each test runs against a clean cwd, no inherited API-key env vars, fresh config cache."""
    for var in [
        "DEEPSEEK_API_KEY",
        "DASHSCOPE_API_KEY",
        "MOONSHOT_API_KEY",
        "OPENAI_API_KEY",
        "ANTHROPIC_API_KEY",
        "CODING_AGENT_PROVIDER",
        "CODING_AGENT_LOG_LEVEL",
    ]:
        monkeypatch.delenv(var, raising=False)
    monkeypatch.chdir(tmp_path)
    reset_config_cache()
    yield
    reset_config_cache()


@pytest.fixture
def workspace(tmp_path: Path) -> Path:
    return tmp_path
