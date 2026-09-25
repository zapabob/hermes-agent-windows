"""auto_encode_turns must not store cron-session prompts, but must keep encoding user turns."""

from __future__ import annotations

import json

import pytest

from plugins.memory.ebbinghaus import EbbinghausMemoryProvider

PREFERENCE_TURN = "Please remember that I prefer concise status reports."


def _provider(tmp_path, name: str) -> tuple[EbbinghausMemoryProvider, object]:
    home = tmp_path / name
    home.mkdir()
    return EbbinghausMemoryProvider(
        {"db_path": str(home / "ebbinghaus_memory.db"), "auto_encode_turns": True}
    ), home


def _count(provider: EbbinghausMemoryProvider) -> int:
    stats = json.loads(provider.handle_tool_call("ebbinghaus_memory", {"action": "stats"}))
    return int(stats["count"])


@pytest.mark.parametrize(
    "init_kwargs",
    [
        {"platform": "cron"},
        {"platform": "cli", "agent_context": "cron"},
        {"platform": "telegram", "agent_context": "flush"},
    ],
)
def test_cron_and_flush_sessions_are_not_auto_encoded(tmp_path, init_kwargs):
    provider, home = _provider(tmp_path, "cron")
    provider.initialize("cron_job_20260926_000000", hermes_home=str(home), **init_kwargs)
    try:
        provider.sync_turn(PREFERENCE_TURN, "ok", session_id="cron_job_20260926_000000")
        provider.on_session_end([{"role": "user", "content": PREFERENCE_TURN}])
        assert _count(provider) == 0
    finally:
        provider.shutdown()


@pytest.mark.parametrize("platform", ["cli", "telegram", "desktop"])
def test_user_sessions_are_still_auto_encoded(tmp_path, platform):
    provider, home = _provider(tmp_path, platform)
    provider.initialize("user-session", hermes_home=str(home), platform=platform, agent_context="primary")
    try:
        provider.sync_turn(PREFERENCE_TURN, "ok", session_id="user-session")
        assert _count(provider) == 1
    finally:
        provider.shutdown()


def test_explicit_remember_still_works_in_cron_sessions(tmp_path):
    provider, home = _provider(tmp_path, "cron-explicit")
    provider.initialize("cron_job_20260926_000001", hermes_home=str(home), platform="cron")
    try:
        result = json.loads(
            provider.handle_tool_call(
                "ebbinghaus_memory",
                {"action": "remember", "content": "Daily social summary ran.", "salience": 0.4},
            )
        )
        assert result.get("status") == "remembered"
        assert _count(provider) == 1
    finally:
        provider.shutdown()
