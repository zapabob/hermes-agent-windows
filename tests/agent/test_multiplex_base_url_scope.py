"""Multiplex invariant: aux / proxy / browser base URLs stay inside the routed profile.

Under multiplexing ``os.environ`` holds the DEFAULT profile's endpoints. A secondary
profile's scoped API key must not be sent to the default profile's proxy or host.

Downstream COMPOSE of upstream a9838c (SR-20260913-004c). xAI video plugin
fallback-after-miss is tracked separately if present on this fork.
"""

from __future__ import annotations

import pytest

from agent import secret_scope


@pytest.fixture
def secondary_scope(monkeypatch):
    secret_scope.set_multiplex_active(True)
    token = secret_scope.set_secret_scope({})
    try:
        monkeypatch.setenv("OPENAI_BASE_URL", "https://openai.default.example/v1")
        monkeypatch.setenv("NOUS_INFERENCE_BASE_URL", "https://nous.default.example/v1/")
        monkeypatch.setenv("HERMES_XAI_BASE_URL", "https://xai.default.example/v1")
        monkeypatch.setenv("XAI_BASE_URL", "https://xai-alt.default.example/v1")
        monkeypatch.setenv("GATEWAY_PROXY_URL", "https://proxy.default.example/")
        monkeypatch.setenv("BROWSERBASE_BASE_URL", "https://bb.default.example")
        monkeypatch.setenv("FIRECRAWL_API_URL", "https://fc.default.example")
        yield
    finally:
        secret_scope.reset_secret_scope(token)
        secret_scope.set_multiplex_active(False)


def test_scoped_base_urls_ignore_default_profile_environ(monkeypatch, secondary_scope):
    from agent import auxiliary_client as aux
    from gateway.run import GatewayRunner
    from hermes_cli import auth
    from plugins.browser import browserbase, firecrawl

    monkeypatch.setattr(
        "hermes_cli.runtime_provider._get_named_custom_provider",
        lambda name: None,
        raising=False,
    )

    _, base = aux._expand_direct_api_alias("openai", None)
    assert "default.example" not in (base or "")
    assert aux._scoped_key_env("OPENAI_BASE_URL") == ""
    assert auth._nous_inference_env_override() is None
    monkeypatch.setattr("gateway.run._load_gateway_config", lambda: {})
    assert GatewayRunner._get_proxy_url(GatewayRunner.__new__(GatewayRunner)) is None
    assert "default.example" not in firecrawl.FirecrawlBrowserProvider()._api_url()

    # Browserbase only returns a config when keys are present; install keys
    # without a scoped BASE_URL so the default endpoint is used, not environ.
    token = secret_scope.set_secret_scope(
        {"BROWSERBASE_API_KEY": "bb-key", "BROWSERBASE_PROJECT_ID": "bb-proj"}
    )
    try:
        cfg = browserbase.BrowserbaseBrowserProvider()._get_config_or_none()
        assert cfg is not None
        assert "default.example" not in cfg["base_url"]
    finally:
        secret_scope.reset_secret_scope(token)


def test_unscoped_single_profile_reads_keep_environ(monkeypatch):
    """Multiplex OFF: environ IS the profile's own value — behaviour unchanged."""
    from gateway.run import GatewayRunner
    from hermes_cli import auth

    secret_scope.set_multiplex_active(False)
    token = secret_scope.set_secret_scope(None)
    try:
        monkeypatch.setenv("GATEWAY_PROXY_URL", "https://proxy.mine.example/")
        monkeypatch.setenv("NOUS_INFERENCE_BASE_URL", "https://nous.mine.example/v1/")
        monkeypatch.setattr("gateway.run._load_gateway_config", lambda: {})
        assert (
            GatewayRunner._get_proxy_url(GatewayRunner.__new__(GatewayRunner))
            == "https://proxy.mine.example"
        )
        assert auth._nous_inference_env_override() == "https://nous.mine.example/v1"
    finally:
        secret_scope.reset_secret_scope(token)
