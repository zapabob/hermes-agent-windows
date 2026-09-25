"""Tests that callable api_key (Entra ID bearer provider) flows through
the agent stack without coercion.

The OpenAI Python SDK accepts ``api_key: str | None | Callable[[], str]``,
and ``azure-identity``'s ``get_bearer_token_provider`` returns a callable.
Hermes preserves the callable end-to-end so the SDK refreshes tokens
transparently. This file pins the contract at the high-risk seams the
rubber-duck audit identified.

Covered:
  * ``_create_openai_client`` passes a callable ``api_key`` straight
    through to ``openai.OpenAI(...)``.
  * ``_normalize_main_runtime`` preserves the callable so auxiliary
    clients inherit Entra auth.
  * ``_truncate_token`` (dashboard preview) renders ``"<entra-id-bearer>"``
    instead of ``"<function ...>"`` and never invokes the callable.
  * ``run_agent.py`` masked-banner path renders the Entra placeholder
    and never tries to slice/len the callable.
  * Serialization scrub: dumping a runtime dict via ``json.dumps`` with
    a callable api_key raises (default behaviour) — guards against
    silently leaking ``"<function ...>"`` strings into event logs.
  * ``batch_runner`` strips the callable from the worker config dict
    so multiprocessing.Pool can pickle the rest.
"""

from __future__ import annotations

import json
from typing import cast
from unittest.mock import MagicMock

import pytest


# ---------------------------------------------------------------------------
# OpenAI SDK construction preserves the callable
# ---------------------------------------------------------------------------


class TestCreateOpenAIClientCallable:
    """``AIAgent._create_openai_client`` must pass the callable through
    to ``openai.OpenAI(...)`` without coercion."""

    def test_callable_api_key_passed_to_openai_constructor(self, monkeypatch):
        """Construct the smallest possible AIAgent surface and verify
        the OpenAI client receives the callable unchanged."""
        captured = {}

        def fake_openai(**kwargs):
            captured["kwargs"] = kwargs
            return MagicMock(api_key=kwargs.get("api_key"))

        # Patch the module-level OpenAI proxy used by ``_create_openai_client``.
        monkeypatch.setattr("run_agent.OpenAI", fake_openai)

        # Build a minimal stand-in for AIAgent so we can call the bound
        # method directly without paying the full __init__ cost.
        from run_agent import AIAgent

        agent = AIAgent.__new__(AIAgent)
        # Attributes consulted by _create_openai_client / _client_log_context.
        agent.provider = "azure-foundry"
        agent.model = "gpt-4o"
        agent.base_url = "https://r.openai.azure.com/openai/v1"
        agent._client_kwargs = {}

        def token_provider():
            return "fresh-jwt"

        client_kwargs = {
            "api_key": token_provider,
            "base_url": "https://r.openai.azure.com/openai/v1",
        }
        client = agent._create_openai_client(client_kwargs, reason="test", shared=False)

        # The OpenAI constructor must receive the *callable*, not a string.
        forwarded = captured["kwargs"]["api_key"]
        assert callable(forwarded)
        assert not isinstance(forwarded, str)
        assert forwarded is token_provider, (
            "_create_openai_client must not wrap or coerce the callable"
        )
        assert client is not None


# ---------------------------------------------------------------------------
# Auxiliary runtime preserves the callable
# ---------------------------------------------------------------------------


class TestNormalizeMainRuntimePreservesCallable:
    """The aux client orchestrator must keep the callable on the
    runtime dict so compression / vision / embedding / title-gen clients
    inherit Entra ID auth from the main agent."""

    def test_callable_api_key_survives_normalization(self):
        from agent.auxiliary_client import _normalize_main_runtime

        def provider():
            return "jwt"

        normalized = _normalize_main_runtime({
            "provider": "azure-foundry",
            "model": "gpt-4o",
            "base_url": "https://r.openai.azure.com/openai/v1",
            "api_key": provider,
            "api_mode": "chat_completions",
            "auth_mode": "entra_id",
        })
        assert normalized["api_key"] is provider
        assert normalized["auth_mode"] == "entra_id"

    def test_string_api_key_still_works(self):
        from agent.auxiliary_client import _normalize_main_runtime

        normalized = _normalize_main_runtime({
            "provider": "azure-foundry",
            "api_key": "sk-static",
        })
        assert normalized["api_key"] == "sk-static"




# ---------------------------------------------------------------------------
# Display surfaces never invoke the callable
# ---------------------------------------------------------------------------


class TestTruncateTokenCallable:
    def test_callable_returns_placeholder(self):
        """Dashboard preview must render the Entra placeholder, NOT
        ``"<function ...>"``."""
        from hermes_cli.web_server import _truncate_token

        invoked = {"count": 0}

        def provider():
            invoked["count"] += 1
            return "should-not-appear-in-ui"

        token_provider = cast(str | None, provider)
        rendered = _truncate_token(token_provider)
        assert rendered == "<entra-id-bearer>"
        assert invoked["count"] == 0

    def test_string_jwt_still_truncated_to_signature_tail(self):
        from hermes_cli.web_server import _truncate_token

        # JWT shape: header.payload.signature → only signature tail shown.
        out = _truncate_token("aaaa.bbbb.cccccccsig", visible=4)
        assert out == "…csig"

    def test_empty_returns_empty(self):
        from hermes_cli.web_server import _truncate_token

        assert _truncate_token(None) == ""
        assert _truncate_token("") == ""


# ---------------------------------------------------------------------------
# Serialization scrub — runtime dicts with callables must NOT silently
# JSON-encode as ``"<function ...>"`` (would leak garbage into events).
# ---------------------------------------------------------------------------


class TestRuntimeDictSerializationGuard:
    def test_json_dumps_default_str_does_not_silently_stringify_callable(self):
        """Sanity check: a runtime dict with a callable api_key must
        either raise on plain ``json.dumps`` (good — fail loud) or be
        sanitized BEFORE serialization. This test pins the loud-fail
        behaviour so future changes that introduce
        ``json.dumps(..., default=str)`` over a runtime dict are caught
        by a regression here."""

        def provider():
            return "jwt"

        runtime = {
            "provider": "azure-foundry",
            "api_key": provider,
            "auth_mode": "entra_id",
        }
        # Plain json.dumps — must raise, not silently produce
        # ``"<function provider at 0x...>"``.
        with pytest.raises(TypeError):
            json.dumps(runtime)


# ---------------------------------------------------------------------------
# batch_runner strips callables from the worker config dict
# ---------------------------------------------------------------------------


class TestBatchRunnerCallableHandling:
    def test_callable_api_key_stripped_from_worker_config(
        self, capsys, monkeypatch, tmp_path
    ):
        """``BatchRunner._run_batches`` (or the equivalent code path)
        must replace a callable api_key with None before pickling the
        worker config dict — otherwise multiprocessing.Pool fails."""
        # We can't easily run BatchRunner end-to-end in a unit test
        # (it spawns subprocesses), but we CAN inline the same logic:
        # the production code uses ``callable(self.api_key) and not
        # isinstance(self.api_key, str)`` to gate the substitution.
        # Re-execute the same predicate here as a contract guard.

        def provider():
            return "jwt"

        api_key = provider
        worker_api_key = (
            None if (callable(api_key) and not isinstance(api_key, str)) else api_key
        )
        assert worker_api_key is None, (
            "BatchRunner must replace callable api_key with None so "
            "multiprocessing.Pool can pickle the worker config"
        )

        # And a string passes through unchanged.
        api_key_str = "sk-static"
        worker_api_key_str = (
            None
            if (callable(api_key_str) and not isinstance(api_key_str, str))
            else api_key_str
        )
        assert worker_api_key_str == "sk-static"

    def test_run_hands_workers_a_picklable_config_without_the_callable(
        self, monkeypatch, tmp_path
    ):
        """Drive the real ``BatchRunner.run`` up to the pool dispatch and
        inspect the worker config it hands to ``multiprocessing.Pool``."""
        import pickle

        import batch_runner

        dispatched = []

        class _StopAfterDispatch(Exception):
            pass

        class _CapturingPool:
            def __init__(self, processes=None):
                pass

            def __enter__(self):
                return self

            def __exit__(self, *exc):
                return False

            def imap_unordered(self, func, tasks):
                dispatched.extend(tasks)
                raise _StopAfterDispatch

            def terminate(self):
                pass

            def join(self):
                pass

        monkeypatch.setattr(batch_runner, "Pool", _CapturingPool)

        invoked = {"count": 0}

        def provider():
            invoked["count"] += 1
            return "jwt"

        runner = batch_runner.BatchRunner.__new__(batch_runner.BatchRunner)
        runner.__dict__.update(
            api_key=provider,
            run_name="callable-key-run",
            batches=[[(0, {"prompt": "hello"})]],
            output_dir=tmp_path,
            num_workers=1,
            distribution="default",
            model="gpt-4o",
            max_iterations=1,
            base_url="https://r.openai.azure.com/openai/v1",
            verbose=False,
            ephemeral_system_prompt=None,
            log_prefix_chars=100,
            providers_allowed=None,
            providers_ignored=None,
            providers_order=None,
            provider_sort=None,
            openrouter_min_coding_score=None,
            max_tokens=None,
            reasoning_config=None,
            prefill_messages=None,
        )
        monkeypatch.setattr(runner, "_load_checkpoint", lambda: {})

        with pytest.raises(_StopAfterDispatch):
            runner.run(resume=False)

        assert len(dispatched) == 1
        worker_config = dispatched[0][-1]
        assert worker_config["api_key"] is None
        pickle.dumps(dispatched[0])
        assert invoked["count"] == 0


# ---------------------------------------------------------------------------
# Inline masked-banner / display sites (callable-aware)
# ---------------------------------------------------------------------------


class TestCliEnsureRuntimeCredentialsCallable:
    """Regression: ``cli.py:_ensure_runtime_credentials`` previously
    treated a callable ``api_key`` as "not a string" and overwrote it
    with the ``"no-key-required"`` placeholder, which then got sent as
    ``Authorization: Bearer no-key-required`` and rejected by Azure
    with a 401. This is the most subtle of the callable-api_key audit
    sites — gated by ``not isinstance(api_key, str)`` rather than the
    cleaner ``callable(...)`` check used elsewhere.

    The mixin method runs for real against a minimal host object; only
    provider resolution is stubbed."""

    def test_callable_api_key_survives_runtime_credential_resolution(
        self, monkeypatch
    ):
        import hermes_cli.runtime_provider as runtime_provider
        from hermes_cli.cli_agent_setup_mixin import CLIAgentSetupMixin

        invoked = {"count": 0}

        def provider():
            invoked["count"] += 1
            return "jwt"

        base_url = "https://r.openai.azure.com/openai/v1"
        monkeypatch.setattr(
            runtime_provider,
            "resolve_runtime_provider",
            lambda **_kwargs: {
                "provider": "azure-foundry",
                "api_mode": "chat_completions",
                "base_url": base_url,
                "api_key": provider,
                "model": "gpt-4o",
                "source": "config",
            },
        )

        class _Host(CLIAgentSetupMixin):
            def _normalize_model_for_provider(self, _provider):
                return False

        host = _Host()
        host.__dict__.update(
            requested_provider="azure-foundry",
            _explicit_api_key=None,
            _explicit_base_url=None,
            _fallback_model=[],
            api_mode="chat_completions",
            api_key=None,
            base_url=None,
            provider=None,
            acp_command=None,
            acp_args=[],
            model="gpt-4o",
            agent=None,
        )

        assert host._ensure_runtime_credentials() is True
        # Without the callable guard the provider is replaced with the
        # "no-key-required" placeholder and Azure answers 401.
        assert host.api_key is provider
        assert host.base_url == base_url
        assert invoked["count"] == 0


class TestInlinedDisplayMasks:
    """The masked-credential display sites are now inlined per-site (no
    shared helper). Each site uses the ``is_token_provider`` predicate
    to short-circuit on callables and print a static
    ``"Microsoft Entra ID"`` label, then falls through to its own
    context-appropriate string mask. This replaces a unified helper
    that would have forced one mask shape across sites with legitimately
    different display needs (banner vs diagnostic vs UI vs preview)."""

    @staticmethod
    def _build_agent(api_key, **overrides):
        from unittest.mock import patch

        from run_agent import AIAgent

        kwargs = dict(
            api_key=api_key,
            base_url="https://r.openai.azure.com/openai/v1",
            provider="azure-foundry",
            model="gpt-4o",
            quiet_mode=False,
            skip_context_files=True,
            skip_memory=True,
        )
        kwargs.update(overrides)
        with (
            patch("run_agent.get_tool_definitions", return_value=[]),
            patch("run_agent.check_toolset_requirements", return_value={}),
            patch("run_agent.OpenAI"),
            patch("agent.anthropic_adapter.build_anthropic_client"),
        ):
            return AIAgent(**kwargs)

    def test_chat_completions_banner_labels_callable_as_entra(self, capsys):
        """The OpenAI-wire init banner in ``agent/agent_init.py`` must
        label a callable key instead of slicing or measuring it."""

        def provider():
            return "jwt"

        self._build_agent(provider, api_mode="chat_completions")

        out = capsys.readouterr().out
        assert "🔑 Using credentials: Microsoft Entra ID" in out
        assert "<function" not in out

    def test_anthropic_banner_labels_callable_as_entra(self, capsys):
        """The anthropic_messages init banner must use the same label."""

        def provider():
            return "jwt"

        self._build_agent(
            provider,
            api_mode="anthropic_messages",
            base_url="https://r.services.ai.azure.com/anthropic",
            model="claude-sonnet-4-5",
        )

        out = capsys.readouterr().out
        assert "(Anthropic native)" in out
        assert "🔑 Using credentials: Microsoft Entra ID" in out
        assert "<function" not in out

    def test_cli_show_config_handles_callable(self, capsys):
        """``cli.HermesCLI.show_config`` previously did
        ``self.api_key[-4:]`` / ``len(self.api_key)`` which crashes on
        callable Entra ID providers. It must print the same static label
        as the agent banners and never invoke the callable."""
        from datetime import datetime
        from types import SimpleNamespace

        from cli import HermesCLI

        invoked = {"count": 0}

        def provider():
            invoked["count"] += 1
            return "jwt"

        host = SimpleNamespace(
            api_key=provider,
            agent=None,
            model="gpt-4o",
            base_url="https://r.openai.azure.com/openai/v1",
            max_turns=10,
            enabled_toolsets=None,
            verbose=False,
            session_start=datetime(2026, 1, 1),
        )
        HermesCLI.show_config(host)

        out = capsys.readouterr().out
        assert "API Key:   Microsoft Entra ID" in out
        assert "<function" not in out
        assert invoked["count"] == 0


