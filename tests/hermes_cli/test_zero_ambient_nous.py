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

Explicit Nous usage (provider="nous" or explicit fallback_providers) remains permitted.
"""

from __future__ import annotations

import contextlib
import urllib.request
from typing import Any, Generator, List
from unittest.mock import MagicMock, patch

import pytest


class NousNetworkAccessViolation(RuntimeError):
    """Raised when an ambient/implicit outbound Nous network request is detected."""


@contextlib.contextmanager
def nous_network_deny(allowed_explicit: bool = False) -> Generator[List[str], None, None]:
    """Intercept and forbid any outbound HTTP/network requests to Nous domains

    unless explicitly allowed.
    """
    nous_requests: List[str] = []
    original_urlopen = urllib.request.urlopen

    def intercepted_urlopen(req: Any, *args: Any, **kwargs: Any) -> Any:
        url = req.full_url if hasattr(req, "full_url") else str(req)
        if "nousresearch.com" in url.lower():
            nous_requests.append(url)
            if not allowed_explicit:
                raise NousNetworkAccessViolation(
                    f"Forbidden ambient outbound Nous request intercepted: {url}"
                )
        return original_urlopen(req, *args, **kwargs)

    with patch("urllib.request.urlopen", side_effect=intercepted_urlopen):
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
        from hermes_cli.config import DEFAULT_CONFIG
        from hermes_cli.explicit_routing import resolve_selection_intent

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

        # Catalog lookup without network should return cleanly or fallback to offline
        cached = model_catalog.get_default_model_from_cache("openrouter")
        # Ensure zero outbound calls
        assert len(intercepted) == 0

        # In zero-ambient Nous, default catalog URL must NOT target nousresearch.com
        assert "nousresearch.com" not in model_catalog.DEFAULT_CATALOG_URL.lower()


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
    # CONTRACT: In zero-ambient Nous, if fallback_providers is empty,
    # it must NOT inject nous auto-free!
    nous_entries = [e for e in resolved if e.get("provider") == "nous"]
    assert len(nous_entries) == 0, f"Implicit Nous fallback detected: {nous_entries}"


def test_auxiliary_task_zero_ambient_nous() -> None:
    """6. Auxiliary task routing must not select or contact Nous when unconfigured."""
    with nous_network_deny(allowed_explicit=False) as intercepted:
        from hermes_cli.explicit_routing import check_fallback_allowed, FallbackPolicy, ModelSelectionIntent

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
    # Verify it does not silently switch to nous
    assert err.get("fallback_provider") != "nous"


def test_session_resume_zero_ambient_nous() -> None:
    """8. Session resume of non-Nous session must not trigger Nous routing."""
    with nous_network_deny(allowed_explicit=False) as intercepted:
        from hermes_cli.explicit_routing import resolve_selection_intent

        intent, policy = resolve_selection_intent(
            "openrouter",
            "anthropic/claude-3-5-sonnet",
            profile_id="resumed-profile",
            session_id="resumed-session",
            connection_id="resumed-conn",
        )
        assert intent.provider == "openrouter"
        assert len(intercepted) == 0


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
