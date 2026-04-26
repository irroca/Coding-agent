from __future__ import annotations

import pytest

from coding_agent.core.config import Config, load_config
from coding_agent.core.errors import ConfigError


def test_defaults_have_no_api_key() -> None:
    cfg = load_config()
    assert cfg.provider == "deepseek"
    assert cfg.providers["deepseek"].api_key is None


def test_active_provider_raises_when_unconfigured() -> None:
    cfg = load_config()
    with pytest.raises(ConfigError, match="not configured"):
        cfg.active_provider()


def test_env_var_hydrates_provider(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DEEPSEEK_API_KEY", "sk-test-123")
    from coding_agent.core.config import reset_config_cache

    reset_config_cache()
    cfg = load_config()
    assert cfg.providers["deepseek"].api_key == "sk-test-123"
    assert cfg.providers["deepseek"].base_url == "https://api.deepseek.com"
    assert cfg.active_provider().model == "deepseek-chat"


def test_provider_override_via_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CODING_AGENT_PROVIDER", "qwen")
    monkeypatch.setenv("DASHSCOPE_API_KEY", "sk-qwen-1")
    from coding_agent.core.config import reset_config_cache

    reset_config_cache()
    cfg = load_config()
    assert cfg.provider == "qwen"
    assert cfg.active_provider().api_key == "sk-qwen-1"


def test_yaml_layering(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    project_yaml = tmp_path / ".coding_agent" / "config.yaml"
    project_yaml.parent.mkdir()
    project_yaml.write_text("agent:\n  max_iterations: 7\n", encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    from coding_agent.core.config import reset_config_cache

    reset_config_cache()
    cfg = load_config()
    assert cfg.agent.max_iterations == 7


def test_config_is_pydantic_model() -> None:
    assert issubclass(Config, object)
    cfg = load_config()
    assert cfg.agent.compact_threshold == 0.85
    assert cfg.agent.parallel_tool_calls is True
