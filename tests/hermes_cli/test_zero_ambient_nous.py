"""Zero Ambient Nous runtime enforcement tests.

Enforces that NO ambient, implicit, or unselected Nous network traffic,
routes, credential probes, or startup dependencies occur across:
1. Hermes startup
2. Desktop/model catalog
3. local llama provider
4. OpenAI-compatible provider
5. NVIDIA provider
6. auxiliary task
7. primary provider failure without fallback
8. session resume
9. models.dev new model visibility

Explicit Nous usage (provider="nous" or explicit fallback_providers) remains permitted.
"""

from __future__ import annotations

import contextlib
import json
import urllib.request
from pathlib import Path
from typing import Any, Generator, List
from unittest.mock import MagicMock, patch

import pytest


class NousNetworkAccessViolation(RuntimeError):
    """Raised when an ambient/implicit outbound Nous network request is detected."""


@contextlib.contextmanager
def nous_network_deny(allowed_explicit: bool = False) -> Generator[List[str], None, None]:
    """Intercept and forbid any outbound HTTP/network requests to Nous domains
    across urllib.request, requests, httpx, and socket connections,
    unless explicitly allowed.
    """
    nous_requests: List[str] = []

    def check_url_or_host(target: str) -> None:
        low = target.lower()
        if "nousresearch.com" in low:
            nous_requests.append(target)
            if not allowed_explicit:
                raise NousNetworkAccessViolation(
                    f"Forbidden ambient outbound Nous request intercepted: {target}"
                )

    # 1. urllib.request
    original_urlopen = urllib.request.urlopen

    def intercepted_urlopen(req: Any, *args: Any, **kwargs: Any) -> Any:
        url = req.full_url if hasattr(req, "full_url") else str(req)
        check_url_or_host(url)
        return original_urlopen(req, *args, **kwargs)

    patches = [
        patch("urllib.request.urlopen", side_effect=intercepted_urlopen),
    ]

    # 2. requests (if loaded)
    try:
        import requests.sessions

        original_requests_send = requests.sessions.Session.send

        def intercepted_requests_send(self: Any, request: Any, *args: Any, **kwargs: Any) -> Any:
            url = str(getattr(request, "url", ""))
            check_url_or_host(url)
            return original_requests_send(self, request, *args, **kwargs)

        patches.append(patch("requests.sessions.Session.send", side_effect=intercepted_requests_send))
    except ImportError:
        pass

    # 3. socket
    try:
        import socket

        original_create_connection = socket.create_connection

        def intercepted_create_connection(address: Any, *args: Any, **kwargs: Any) -> Any:
            if isinstance(address, tuple) and len(address) > 0:
                host = str(address[0])
                check_url_or_host(host)
            return original_create_connection(address, *args, **kwargs)

        patches.append(patch("socket.create_connection", side_effect=intercepted_create_connection))
    except ImportError:
        pass

    # 4. httpx (if loaded)
    try:
        import httpx

        original_httpx_send = httpx.Client.send

        def intercepted_httpx_send(self: Any, request: Any, *args: Any, **kwargs: Any) -> Any:
            url = str(getattr(request, "url", ""))
            check_url_or_host(url)
            return original_httpx_send(self, request, *args, **kwargs)

        patches.append(patch.object(httpx.Client, "send", autospec=True, side_effect=intercepted_httpx_send))
    except ImportError:
        pass

    with contextlib.ExitStack() as stack:
        for p in patches:
            stack.enter_context(p)
        yield nous_requests


# ---------------------------------------------------------------------------
# Test Cases
# ---------------------------------------------------------------------------


def test_startup_zero_ambient_nous(monkeypatch: pytest.MonkeyPatch, tmp_path: Any) -> None:
    """1. Hermes startup with non-nous provider must never hit Nous domains."""
    monkeypatch.delenv("NOUS_API_KEY", raising=False)
    monkeypatch.delenv("NOUS_PORTAL_API_KEY", raising=False)
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))

    with nous_network_deny(allowed_explicit=False) as intercepted:
        from hermes_cli.config import load_config
        from hermes_cli.explicit_routing import resolve_selection_intent

        # Exercise real startup config loader
        cfg = load_config()
        assert isinstance(cfg, dict)

        # Exercise intent & policy resolution on startup
        intent, policy = resolve_selection_intent(
            "openrouter",
            "meta-llama/llama-3-8b",
            profile_id="default",
            session_id="startup-test",
            connection_id="desktop-1",
        )
        assert intent.provider == "openrouter"
        assert not policy.allow_cross_provider
        assert len(intercepted) == 0


def test_model_catalog_zero_ambient_nous(tmp_path: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    """2. Model catalog resolution must not probe Nous URL unless provider=nous is chosen."""
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))

    with nous_network_deny(allowed_explicit=False) as intercepted:
        from hermes_cli import model_catalog

        model_catalog.reset_cache()

        # Catalog lookup without network should return cleanly or fallback to offline
        cached = model_catalog.get_default_model_from_cache("openrouter")
        assert len(intercepted) == 0

        # In zero-ambient Nous, default catalog URL must NOT target nousresearch.com
        assert "nousresearch.com" not in model_catalog.DEFAULT_CATALOG_URL.lower()
        for u in model_catalog.DEFAULT_CATALOG_FALLBACK_URLS:
            assert "nousresearch.com" not in u.lower()

        # Neutral catalog refresh through models.dev mock
        mock_resp = MagicMock()
        mock_resp.__enter__.return_value = mock_resp
        mock_resp.read.return_value = json.dumps({
            "openrouter": {
                "id": "openrouter",
                "name": "OpenRouter",
                "models": {
                    "anthropic/claude-sonnet-4-6": {
                        "id": "anthropic/claude-sonnet-4-6",
                        "name": "Claude Sonnet 4.6",
                        "default": True,
                    }
                }
            }
        }).encode()
        with patch("urllib.request.urlopen", return_value=mock_resp):
            cat = model_catalog.get_catalog(force_refresh=True)
            assert "providers" in cat

        assert len(intercepted) == 0


def test_local_llama_provider_zero_ambient_nous(tmp_path: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    """3. Local Llama provider must have zero Nous route or outbound request."""
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))

    with nous_network_deny(allowed_explicit=False) as intercepted:
        from hermes_cli.explicit_routing import resolve_selection_intent

        intent, policy = resolve_selection_intent(
            "local",
            "huihui-gemma",
            profile_id="default",
            session_id="local-sess",
            connection_id="conn-local",
        )
        assert intent.provider == "local"
        assert len(intercepted) == 0


def test_openai_compatible_provider_zero_ambient_nous(tmp_path: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    """4. OpenAI-compatible provider must have zero Nous dependency or route."""
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))

    with nous_network_deny(allowed_explicit=False) as intercepted:
        from hermes_cli.explicit_routing import resolve_selection_intent

        intent, policy = resolve_selection_intent(
            "openai",
            "gpt-4o",
            profile_id="default",
            session_id="openai-sess",
            connection_id="conn-openai",
        )
        assert intent.provider == "openrouter"  # normalized alias
        assert len(intercepted) == 0


def test_nvidia_provider_fallback_zero_ambient_nous() -> None:
    """5. NVIDIA provider without explicit fallback must NOT implicitly inject Nous auto-free."""
    from hermes_cli.fallback_config import resolve_fallback_chain

    config = {
        "model": {
            "provider": "nvidia",
            "default": "nvidia/nemotron-3-super-120b-a12b",
        },
        "fallback_providers": [],
    }

    resolved = resolve_fallback_chain(config)
    nous_entries = [e for e in resolved if e.get("provider") == "nous"]
    assert len(nous_entries) == 0, f"Implicit Nous fallback detected: {nous_entries}"


def test_auxiliary_task_zero_ambient_nous() -> None:
    """6. Auxiliary task routing must not select or contact Nous when unconfigured."""
    with nous_network_deny(allowed_explicit=False) as intercepted:
        from hermes_cli.explicit_routing import check_fallback_allowed, FallbackPolicy, ModelSelectionIntent
        from agent.auxiliary_client import _resolve_auto

        # 1. Policy check
        intent = ModelSelectionIntent(
            provider="openai",
            model="gpt-4o",
            profile_id="p1",
            session_id="s1",
            connection_id="c1",
        )
        policy = FallbackPolicy(allow_cross_provider=False, explicit_routes=())
        allowed = check_fallback_allowed(
            intent,
            policy,
            effective_provider="nous",
            effective_model="auto-free",
        )
        assert allowed is False

        # 2. Real auxiliary routing resolution does not contact Nous
        client, model = _resolve_auto("text")
        if client is not None:
            assert "nous" not in str(type(client)).lower()

        assert len(intercepted) == 0


def test_primary_failure_without_fallback_visible_failure() -> None:
    """7. Primary failure with no explicit fallback must report visible failure, NOT Nous fallback."""
    from hermes_cli.explicit_routing import model_unavailable_error, ModelSelectionIntent

    intent = ModelSelectionIntent(
        provider="anthropic",
        model="claude-3-5-sonnet",
        profile_id="p1",
        session_id="s1",
        connection_id="c1",
    )
    err = model_unavailable_error(intent, reason="rate_limited")
    assert err["selected_provider"] == "anthropic"
    assert "Selected model unavailable" in err["error"]
    assert err.get("fallback_provider") != "nous"


def test_session_resume_zero_ambient_nous(tmp_path: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    """8. Session resume of non-Nous session must not trigger Nous routing."""
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))

    with nous_network_deny(allowed_explicit=False) as intercepted:
        from hermes_state import SessionDB
        from hermes_cli.explicit_routing import resolve_selection_intent

        db = SessionDB(tmp_path / "sessions.db")
        sid = db.create_session("Resumed Session", source="cli", model="openrouter/anthropic/claude-3-5-sonnet")
        sess = db.get_session(sid)
        assert sess is not None

        intent, policy = resolve_selection_intent(
            "openrouter",
            "anthropic/claude-3-5-sonnet",
            profile_id="resumed-profile",
            session_id=sid,
            connection_id="resumed-conn",
        )
        assert intent.provider == "openrouter"
        assert len(intercepted) == 0


def test_models_dev_new_model_visible(tmp_path: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    """9. Models newly exposed in models.dev become visible to consumers after normalization."""
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    from hermes_cli import model_catalog

    model_catalog.reset_cache()
    payload = {
        "anthropic": {
            "id": "anthropic",
            "name": "Anthropic",
            "models": {
                "claude-opus-4-6": {
                    "id": "claude-opus-4-6",
                    "name": "Claude Opus 4.6",
                    "reasoning": True,
                    "tool_call": True,
                }
            }
        }
    }
    norm = model_catalog.parse_models_dev(payload)
    assert norm is not None
    model_catalog._write_disk_cache(norm.to_dict())

    cat = model_catalog.get_catalog()
    models = cat.get("providers", {}).get("anthropic", {}).get("models", [])
    mids = [m["id"] for m in models]
    assert "claude-opus-4-6" in mids


def test_explicit_nous_allowed() -> None:
    """Explicit provider=nous must be allowed and not blocked."""
    with nous_network_deny(allowed_explicit=True) as intercepted:
        from hermes_cli.explicit_routing import resolve_selection_intent

        intent, policy = resolve_selection_intent(
            "nous",
            "hermes-3-llama-3.1-405b",
            profile_id="nous-profile",
            session_id="nous-session",
            connection_id="nous-conn",
            explicit_provider="nous",
        )
        assert intent.provider == "nous"


def test_explicit_nous_fallback_allowed() -> None:
    """Explicit fallback_providers entry for nous must be honored."""
    from hermes_cli.explicit_routing import check_fallback_allowed, FallbackPolicy, ModelSelectionIntent

    intent = ModelSelectionIntent(
        provider="openai",
        model="gpt-4o",
        profile_id="p1",
        session_id="s1",
        connection_id="c1",
    )
    policy = FallbackPolicy(
        allow_cross_provider=False,
        explicit_routes=(("nous", "auto-free"),),
    )
    assert check_fallback_allowed(
        intent,
        policy,
        effective_provider="nous",
        effective_model="auto-free",
    )
