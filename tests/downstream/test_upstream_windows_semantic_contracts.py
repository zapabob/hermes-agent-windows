"""Differential observable contracts for upstream Windows semantic carry.

These tests assert behavior, not source-tree parity with NousResearch/hermes-agent.
See docs/windows/UPSTREAM_SEMANTIC_CARRY_2026-09-08.md.
"""

from __future__ import annotations

import asyncio
import inspect
import types

import pytest

from hermes_cli.main import _fleet_probe_expected_runtimes
from hermes_cli.pty_session import PtySession
from hermes_cli.win_pty_bridge import WinPtyBridge


def _plan(runtimes):
    return types.SimpleNamespace(runtimes=runtimes)


class TestFleetRuntimeKindContract:
    def test_gateway_plan_expects_rows(self):
        assert (
            _fleet_probe_expected_runtimes(
                _plan([types.SimpleNamespace(kind="gateway")]),
                [],
                None,
                [],
                set(),
            )
            is True
        )

    def test_dashboard_and_serve_plans_do_not(self):
        for kind in ("dashboard", "serve"):
            assert (
                _fleet_probe_expected_runtimes(
                    _plan([types.SimpleNamespace(kind=kind)]),
                    [],
                    None,
                    [],
                    set(),
                )
                is False
            )

    def test_windows_resume_token_is_bookkeeping_only(self):
        token = {"resume_needed": True, "profiles": {"default": 1}}
        assert _fleet_probe_expected_runtimes(None, [], token, [], set()) is False


class TestConPtyWriteContract:
    def test_write_is_async_with_timeout(self):
        assert inspect.iscoroutinefunction(WinPtyBridge.write)
        assert "timeout" in inspect.signature(WinPtyBridge.write).parameters


@pytest.mark.asyncio
async def test_pty_session_generation_isolates_superseded_failures():
    class Bridge:
        def __init__(self):
            self.n = 0

        def read(self, timeout):
            return b""

        async def write(self, data, *, timeout: float = 10.0):
            self.n += 1
            return False

        def close(self):
            return None

    class WS:
        async def send_bytes(self, data):
            return None

        async def close(self, code=1000, reason=""):
            return None

    s = PtySession("k", Bridge(), buffer_cap=64, read_timeout=0.01)
    await s.start()
    a, b = WS(), WS()
    assert await s.attach(a) is True
    assert await s.attach(b) is True
    assert await s.write(a, b"old") is True
    assert s.alive is True
    assert await s.write(b, b"cur") is False
    assert s.alive is False
    await s.close()


class TestPtyHostEnvContract:
    def test_win_bridge_dashboard_host_marker(self):
        from hermes_cli.win_pty_bridge import PTY_HOST_DASHBOARD, PTY_HOST_ENV

        assert PTY_HOST_ENV == "HERMES_PTY_HOST"
        assert PTY_HOST_DASHBOARD == "dashboard"

    @pytest.mark.skipif(
        __import__("sys").platform == "win32",
        reason="POSIX PtyBridge imports fcntl; Windows uses WinPtyBridge",
    )
    def test_posix_bridge_shares_dashboard_host_marker(self):
        from hermes_cli import pty_bridge, win_pty_bridge

        assert pty_bridge.PTY_HOST_ENV == win_pty_bridge.PTY_HOST_ENV
        assert pty_bridge.PTY_HOST_DASHBOARD == win_pty_bridge.PTY_HOST_DASHBOARD


class TestFallbackCooldownOwnershipContract:
    def test_rate_limit_cooldown_arms_once_while_skipping_invalid_entries(self, monkeypatch):
        """fc70d05: skip paths must not re-enter cooldown arming."""
        from agent.chat_completion_helpers import FailoverReason, try_activate_fallback
        import agent.chat_completion_helpers as helpers

        class Agent:
            _fallback_chain = [
                {"provider": "", "model": ""},
                {"provider": "openrouter", "model": "x"},
            ]
            _fallback_index = 0
            _fallback_activated = False
            _primary_runtime = {"provider": "openai"}
            provider = "openai"
            model = "gpt"
            base_url = "https://api.openai.com/v1"
            _unavailable_fallback_keys = set()
            _rate_limit_backoff_count = 0
            _rate_limited_until = 0.0

        monkeypatch.setattr(
            helpers,
            "_run_fallback_start_command",
            lambda *args, **kwargs: False,
        )
        agent = Agent()
        assert try_activate_fallback(agent, FailoverReason.rate_limit) is False
        assert agent._rate_limit_backoff_count == 1
        assert agent._fallback_index >= len(agent._fallback_chain)


class TestGeminiGoogleAliasContract:
    def test_create_openai_client_routes_google_aliases_to_native(self, monkeypatch):
        """a745101e5f: google-alias fallback providers must use GeminiNativeClient."""
        from agent import agent_runtime_helpers as helpers

        class Agent:
            def __init__(self, provider: str):
                self.provider = provider

            def _client_log_context(self):
                return ""

            def _build_keepalive_http_client(self, base_url, verify=True):
                return None

        seen: list[str] = []

        class FakeNative:
            def __init__(self, **kwargs):
                seen.append(str(kwargs.get("api_key")))

        monkeypatch.setattr(
            "agent.gemini_native_adapter.is_native_gemini_base_url",
            lambda url: True,
        )
        monkeypatch.setattr(
            "agent.gemini_native_adapter.GeminiNativeClient",
            FakeNative,
        )
        monkeypatch.setattr(
            helpers,
            "_ra",
            lambda: type(
                "L",
                (),
                {
                    "logger": type(
                        "Lg",
                        (),
                        {"info": staticmethod(lambda *a, **k: None)},
                    )()
                },
            )(),
        )
        monkeypatch.setattr(
            "agent.auxiliary_client._validate_base_url", lambda *a, **k: None
        )
        monkeypatch.setattr(
            "agent.auxiliary_client._validate_proxy_env_urls", lambda *a, **k: None
        )

        for provider in ("gemini", "google", "google-gemini", "google-ai-studio"):
            seen.clear()
            client = helpers.create_openai_client(
                Agent(provider),
                {
                    "api_key": f"key-{provider}",
                    "base_url": "https://generativelanguage.googleapis.com",
                },
                reason="test",
                shared=False,
            )
            assert isinstance(client, FakeNative)
            assert seen == [f"key-{provider}"]


class TestProbeCredentialContract:
    def test_materialize_probe_api_key_never_sends_callable_repr(self):
        from agent.command_token_source import materialize_probe_api_key

        assert materialize_probe_api_key(lambda: "minted") == "minted"
        assert materialize_probe_api_key("static") == "static"

        def boom():
            raise RuntimeError("secret")

        assert materialize_probe_api_key(boom) == ""
        assert materialize_probe_api_key(object()) == ""
