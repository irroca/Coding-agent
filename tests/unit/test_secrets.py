"""Tests for security.secrets — secret detection and redaction.

The detector deliberately favours precision over recall: false positives
inside a coding agent destroy source-code utility. These tests cover both
the known-key shapes we *must* catch and the ordinary-looking strings we
must *not* mangle.
"""

from __future__ import annotations

from coding_agent.security.secrets import find_secrets, redact, redact_iter


def test_detects_openai_key() -> None:
    text = "my key is sk-abcdEFGH12345678ijklMNOP next line"
    matches = find_secrets(text)
    assert any(k == "openai" for k, _ in matches)


def test_detects_openai_proj_key() -> None:
    text = "sk-proj-abcdefghij1234567890ABCDEF and more"
    matches = find_secrets(text)
    assert any(k == "openai" for k, _ in matches)


def test_detects_anthropic_key() -> None:
    text = "header x-api-key: sk-ant-api03-abcdEFGH1234567890ijkl_extra"
    matches = find_secrets(text)
    assert any(k == "anthropic" for k, _ in matches)


def test_detects_github_token() -> None:
    text = "auth: ghp_abcdefghijklmnopqrstuvwxyzABCDEFGHIJ"
    matches = find_secrets(text)
    assert any(k == "github" for k, _ in matches)


def test_detects_aws_access_key() -> None:
    text = "AKIAIOSFODNN7EXAMPLE in env"
    matches = find_secrets(text)
    assert any(k == "aws_access_key" for k, _ in matches)


def test_detects_google_api_key() -> None:
    # AIza prefix + exactly 35 chars from [A-Za-z0-9_-] = 39 chars total.
    text = "AIzaSy" + "b" * 33  # 4 + 35 = 39
    matches = find_secrets(text)
    assert any(k == "google" for k, _ in matches)


def test_does_not_match_git_sha() -> None:
    # 40-char hex (a git SHA) must NOT be flagged as a generic secret.
    sha = "a" * 40
    matches = find_secrets(f"commit {sha} from main")
    assert all(k != "generic_hex" for k, _ in matches)


def test_does_not_match_ordinary_source_code() -> None:
    src = (
        "def hello():\n"
        "    return 'world'\n"
        "# author: alice@example.com\n"
        "x = 42\n"
    )
    assert find_secrets(src) == []


def test_redact_replaces_with_window() -> None:
    text = "key=sk-abcdEFGHij1234567890klMN end"
    out = redact(text)
    assert "sk-abcd" not in out  # raw key gone
    assert "<openai:sk-a" in out  # marker + 4-char prefix
    assert "MN>" in out  # 2-char suffix


def test_redact_empty_string_returns_empty() -> None:
    assert redact("") == ""


def test_redact_keeps_non_secret_text_untouched() -> None:
    text = "the answer is 42 and pi is 3.14159"
    assert redact(text) == text


def test_redact_handles_multiple_kinds_in_one_string() -> None:
    text = (
        "openai: sk-abcdEFGHij1234567890klMN, "
        "github: ghp_abcdefghijklmnopqrstuvwxyzABCDEFGHIJ"
    )
    out = redact(text)
    assert "<openai:" in out
    assert "<github:" in out
    # No raw key prefix should remain.
    assert "sk-abcdEFGHij" not in out
    assert "ghp_abcdefghij" not in out


def test_redact_iter() -> None:
    items = ["safe text", "key sk-abcdEFGHij1234567890klMN"]
    out = redact_iter(items)
    assert out[0] == "safe text"
    assert "<openai:" in out[1]
