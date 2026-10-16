"""Focused Console-key and callable-token auth routing regressions."""

from unittest.mock import patch

import httpx
import pytest

from agent.anthropic_adapter import _OAUTH_ONLY_BETAS, build_anthropic_client


@pytest.mark.parametrize(
    ("family", "is_oauth"),
    [
        ("api03", False),
        ("usr01", False),
        ("svc01", False),
        ("admin01", False),
        ("oat01", True),
    ],
)
def test_static_console_key_families_use_their_expected_auth_style(
    monkeypatch, family, is_oauth
):
    monkeypatch.setattr("agent.anthropic_adapter._claude_code_version_cache", "0.0.0")
    key = f"sk-ant-{family}-" + "X" * 24

    with patch("agent.anthropic_adapter._anthropic_sdk") as mock_sdk:
        build_anthropic_client(key, "https://api.anthropic.com")

    kwargs = mock_sdk.Anthropic.call_args.kwargs
    if is_oauth:
        assert kwargs["auth_token"] == key
        assert "api_key" not in kwargs
        headers = kwargs["default_headers"]
        assert "claude-code-20250219" in headers["anthropic-beta"]
        assert headers["user-agent"].startswith("claude-code/")
        assert headers["x-app"] == "cli"
        assert all(beta in headers["anthropic-beta"] for beta in _OAUTH_ONLY_BETAS)
    else:
        assert kwargs["api_key"] == key
        assert "auth_token" not in kwargs
        headers = kwargs["default_headers"]
        assert not any(beta in headers["anthropic-beta"] for beta in _OAUTH_ONLY_BETAS)
        assert "user-agent" not in headers
        assert "x-app" not in headers


@pytest.mark.parametrize(
    ("base_url", "family", "expected_header"),
    [
        ("https://api.anthropic.com", "api03", "x-api-key"),
        ("https://api.anthropic.com", "usr01", "x-api-key"),
        ("https://api.anthropic.com", "oat01", "authorization"),
        ("https://gateway.invalid/anthropic", "usr01", "authorization"),
        ("https://api.anthropic.com.evil.example", "usr01", "authorization"),
        (None, "svc01", "x-api-key"),
    ],
)
def test_callable_key_uses_route_and_token_family_for_auth_header(
    monkeypatch, base_url, family, expected_header
):
    monkeypatch.setattr("agent.anthropic_adapter._claude_code_version_cache", "0.0.0")
    key = f"sk-ant-{family}-" + "X" * 24

    with patch("agent.anthropic_adapter._anthropic_sdk") as mock_sdk:
        build_anthropic_client(lambda: key, base_url)

    kwargs = mock_sdk.Anthropic.call_args.kwargs
    request_url = (base_url or "https://api.anthropic.com") + "/v1/messages"
    request = httpx.Request(
        "POST",
        request_url,
        headers={"Authorization": "Bearer entra-id-bearer-via-http-hook"},
    )
    kwargs["http_client"].event_hooks["request"][0](request)

    assert request.headers.get("x-api-key") == (key if expected_header == "x-api-key" else None)
    assert request.headers.get("authorization") == (
        f"Bearer {key}" if expected_header == "authorization" else None
    )
