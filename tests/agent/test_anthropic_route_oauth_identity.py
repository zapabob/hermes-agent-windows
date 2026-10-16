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


def test_static_oauth_proxy_requires_explicit_anthropic_provider(monkeypatch):
    monkeypatch.setattr("agent.anthropic_adapter._claude_code_version_cache", "0.0.0")

    with patch("agent.anthropic_adapter._anthropic_sdk") as mock_sdk:
        build_anthropic_client(OAUTH, "https://proxy.example.com/anthropic")
    unbound_kwargs = mock_sdk.Anthropic.call_args.kwargs
    assert unbound_kwargs["api_key"] == OAUTH
    assert "auth_token" not in unbound_kwargs
    assert "user-agent" not in unbound_kwargs["default_headers"]

    with patch("agent.anthropic_adapter._anthropic_sdk") as mock_sdk:
        build_anthropic_client(
            OAUTH,
            "https://proxy.example.com/anthropic",
            provider="anthropic",
        )
    provider_kwargs = mock_sdk.Anthropic.call_args.kwargs
    assert provider_kwargs["auth_token"] == OAUTH
    assert "api_key" not in provider_kwargs
    assert provider_kwargs["default_headers"]["user-agent"].startswith("claude-code/")


def test_explicit_anthropic_provider_proxy_uses_oauth_identity(monkeypatch):
    """The production init path must carry explicit provider identity to the client."""
    monkeypatch.setattr("agent.anthropic_adapter._claude_code_version_cache", "0.0.0")
    from run_agent import AIAgent

    with patch("agent.anthropic_adapter._anthropic_sdk") as mock_sdk:
        agent = AIAgent(
            provider="anthropic",
            base_url="https://proxy.example.com/anthropic",
            api_key=OAUTH,
            model="claude-sonnet-4-5",
            api_mode="anthropic_messages",
            quiet_mode=True,
            skip_context_files=True,
            skip_memory=True,
        )

    kwargs = mock_sdk.Anthropic.call_args.kwargs
    assert agent._is_anthropic_oauth is True
    assert kwargs["auth_token"] == OAUTH
    assert "api_key" not in kwargs
    headers = kwargs["default_headers"]
    assert headers["user-agent"].startswith("claude-code/")
    assert headers["x-app"] == "cli"
    assert all(beta in headers["anthropic-beta"] for beta in _OAUTH_ONLY_BETAS)

    rotated = "sk-ant-oat01-rotated-test-token"
    with patch(
        "agent.anthropic_adapter.resolve_anthropic_token",
        return_value=rotated,
    ), patch("agent.anthropic_adapter._anthropic_sdk") as mock_sdk:
        assert agent._try_refresh_anthropic_client_credentials() is True
    refresh_kwargs = mock_sdk.Anthropic.call_args.kwargs
    assert refresh_kwargs["auth_token"] == rotated
    assert refresh_kwargs["default_headers"]["user-agent"].startswith("claude-code/")

    with patch("agent.anthropic_adapter._anthropic_sdk") as mock_sdk:
        agent._rebuild_anthropic_client()
    rebuild_kwargs = mock_sdk.Anthropic.call_args.kwargs
    assert rebuild_kwargs["auth_token"] == rotated
    assert rebuild_kwargs["default_headers"]["user-agent"].startswith("claude-code/")
