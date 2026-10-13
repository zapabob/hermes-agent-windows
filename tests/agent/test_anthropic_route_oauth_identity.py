"""OAuth identity applies only when both the route and token represent Anthropic OAuth."""

from unittest.mock import patch

from agent.anthropic_adapter import _OAUTH_ONLY_BETAS, build_anthropic_client
from agent.anthropic_credentials import anthropic_route_is_oauth


OAUTH = "sk-ant-oat01-keycmd-token"
CONSOLE = "sk-ant-api03-console-key"
USER_KEY = "sk-ant-usr01-user-scoped-key"


def test_route_identity_requires_native_host_and_oauth_shape():
    calls = []

    def key_cmd():
        calls.append(1)
        return OAUTH

    assert anthropic_route_is_oauth("https://api.anthropic.com", key_cmd) is True
    assert anthropic_route_is_oauth("https://api.anthropic.com/v1", OAUTH) is True
    assert anthropic_route_is_oauth("", OAUTH) is True
    assert anthropic_route_is_oauth(
        "https://proxy.example.com", OAUTH, provider="anthropic"
    ) is True
    assert anthropic_route_is_oauth("https://api.minimax.io/anthropic", key_cmd) is False
    assert anthropic_route_is_oauth("https://api.anthropic.com", CONSOLE) is False
    assert anthropic_route_is_oauth("https://api.anthropic.com", USER_KEY) is False
    assert anthropic_route_is_oauth(
        "https://notapi.anthropic.com.evil.example", key_cmd
    ) is False
    assert anthropic_route_is_oauth(
        "https://api.anthropic.com", lambda: (_ for _ in ()).throw(RuntimeError("no token"))
    ) is False
    assert len(calls) == 1


def test_callable_oauth_identity_is_added_only_on_native_anthropic_route(monkeypatch):
    monkeypatch.setattr("agent.anthropic_adapter._claude_code_version_cache", "0.0.0")

    with patch("agent.anthropic_adapter._anthropic_sdk") as mock_sdk:
        build_anthropic_client(lambda: OAUTH, "https://api.anthropic.com")
    native_headers = mock_sdk.Anthropic.call_args.kwargs["default_headers"]
    assert native_headers["user-agent"].startswith("claude-code/")
    assert native_headers["x-app"] == "cli"
    assert all(beta in native_headers["anthropic-beta"] for beta in _OAUTH_ONLY_BETAS)

    with patch("agent.anthropic_adapter._anthropic_sdk") as mock_sdk:
        build_anthropic_client(lambda: OAUTH, "https://api.minimax.io/anthropic")
    third_party_headers = mock_sdk.Anthropic.call_args.kwargs["default_headers"]
    assert "user-agent" not in third_party_headers
    assert not any(
        beta in third_party_headers["anthropic-beta"] for beta in _OAUTH_ONLY_BETAS
    )
