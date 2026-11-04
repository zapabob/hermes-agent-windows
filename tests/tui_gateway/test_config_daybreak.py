"""The Desktop Daybreak RPC persists one profile's key and refreshes its next turn."""
from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest
import yaml

from hermes_constants import get_hermes_home_override, set_hermes_home_override, reset_hermes_home_override
from tui_gateway import server


@pytest.fixture
def homes(tmp_path, monkeypatch):
    launch = tmp_path / ".hermes"
    worker = launch / "profiles" / "work"
    worker.mkdir(parents=True)
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    monkeypatch.setenv("HERMES_HOME", str(launch))
    monkeypatch.delenv("HERMES_DEFAULT_HOME", raising=False)
    monkeypatch.setattr(server, "_hermes_home", launch)
    monkeypatch.setattr(server, "_sessions", {})
    for name in ("_cfg_cache", "_cfg_mtime", "_cfg_path"):
        monkeypatch.setattr(server, name, None)
    return launch, worker


def call(method, **params):
    return server.handle_request({"jsonrpc": "2.0", "id": "daybreak", "method": method, "params": params})


def saved(home):
    return yaml.safe_load((home / "config.yaml").read_text(encoding="utf-8"))


def test_daybreak_round_trips_as_an_explicit_boolean(homes):
    launch, _ = homes
    assert call("config.get", key="daybreak")["result"] == {"value": False}
    assert call("config.set", key="daybreak", value=True)["result"] == {"key": "daybreak", "value": True}
    assert saved(launch)["agent"]["daybreak"] is True
    assert call("config.get", key="daybreak")["result"] == {"value": True}
    assert call("config.set", key="daybreak", value="false")["result"] == {"key": "daybreak", "value": False}
    assert call("config.get", key="daybreak")["result"] == {"value": False}


@pytest.mark.parametrize("value", ["sometimes", "", None, [], {}, 2])
def test_invalid_values_are_refused_without_creating_config(homes, value):
    launch, _ = homes
    assert call("config.set", key="daybreak", value=value)["error"]["code"] == 4002
    assert not (launch / "config.yaml").exists()


def test_named_profile_save_never_overwrites_launch_config(homes):
    launch, worker = homes
    initial = "# keep this comment\nagent:\n  daybreak: false\n  reasoning_effort: high\n  service_tier: priority\n"
    (launch / "config.yaml").write_text(initial, encoding="utf-8")
    (worker / "config.yaml").write_text("agent:\n  daybreak: false\n  reasoning_effort: low\n", encoding="utf-8")
    assert call("config.set", key="daybreak", value=True, profile="work")["result"]["value"] is True
    assert (launch / "config.yaml").read_text(encoding="utf-8") == initial
    assert saved(worker)["agent"] == {"daybreak": True, "reasoning_effort": "low"}
    assert call("config.get", key="daybreak", profile="work")["result"]["value"] is True
    assert call("config.get", key="daybreak", profile="default")["result"]["value"] is False
    assert get_hermes_home_override() is None


def test_blank_profile_is_the_launch_home_while_default_is_explicit(homes, monkeypatch):
    launch, worker = homes
    monkeypatch.setattr(server, "_hermes_home", worker)
    monkeypatch.setenv("HERMES_HOME", str(worker))
    assert call("config.set", key="daybreak", value=True)["result"]["value"] is True
    assert saved(worker)["agent"]["daybreak"] is True
    assert not (launch / "config.yaml").exists()
    assert call("config.set", key="daybreak", value=False, profile="default")["result"]["value"] is False
    assert saved(launch)["agent"]["daybreak"] is False
    assert call("config.get", key="daybreak")["result"]["value"] is True


def test_missing_profile_never_falls_back_to_launch(homes):
    launch, _ = homes
    with pytest.raises(FileNotFoundError):
        call("config.set", key="daybreak", value=True, profile="missing")
    assert not (launch / "config.yaml").exists()


def test_saved_key_preserves_concurrent_fast_and_reasoning_edits(homes):
    launch, _ = homes
    config = launch / "config.yaml"
    config.write_text("agent:\n  daybreak: false\n  reasoning_effort: low\n", encoding="utf-8")
    call("config.get", key="daybreak")  # prime the old whole-document reader cache
    config.write_text("# another writer\nagent:\n  daybreak: false\n  reasoning_effort: high\n  service_tier: priority\n", encoding="utf-8")
    assert call("config.set", key="daybreak", value=True)["result"]["value"] is True
    assert saved(launch)["agent"] == {"daybreak": True, "reasoning_effort": "high", "service_tier": "priority"}
    assert "# another writer" in config.read_text(encoding="utf-8")


def test_failed_save_leaves_disk_and_live_session_unchanged(homes, monkeypatch):
    from hermes_cli import config_backend

    launch, _ = homes
    initial = "agent:\n  daybreak: false\n  reasoning_effort: high\n"
    (launch / "config.yaml").write_text(initial, encoding="utf-8")
    live = SimpleNamespace(daybreak=False, service_tier="priority", reasoning_config={"effort": "high"})
    server._sessions["chat"] = {"agent": live, "session_key": "chat-key"}

    def refuse(*args, **kwargs):
        raise PermissionError("config is read-only")

    monkeypatch.setattr(config_backend, "write_config_key", refuse)
    result = call("config.set", key="daybreak", value=True, session_id="chat")
    assert "error" in result
    assert (launch / "config.yaml").read_text(encoding="utf-8") == initial
    assert live.daybreak is False
    assert live.service_tier == "priority"
    assert live.reasoning_config == {"effort": "high"}
    assert call("config.get", key="daybreak")["result"]["value"] is False


def test_managed_daybreak_is_refused_without_a_misleading_saved_value(homes, tmp_path, monkeypatch):
    launch, _ = homes
    managed = tmp_path / "managed"
    managed.mkdir()
    (managed / "config.yaml").write_text("agent:\n  daybreak: true\n", encoding="utf-8")
    monkeypatch.setenv("HERMES_MANAGED_DIR", str(managed))
    assert call("config.get", key="daybreak")["result"]["value"] is True
    assert "error" in call("config.set", key="daybreak", value=False)
    assert not (launch / "config.yaml").exists()
    assert call("config.get", key="daybreak")["result"]["value"] is True


@pytest.mark.parametrize(("platform", "expected"), [
    ("desktop", True), ("tui", True), ("cli", True),
    ("telegram", False), ("acp", False), ("subagent", False), (None, False),
])
def test_next_turn_reads_only_its_profile_switch_for_local_owner_surfaces(homes, platform, expected):
    launch, worker = homes
    (launch / "config.yaml").write_text("agent:\n  daybreak: false\n", encoding="utf-8")
    (worker / "config.yaml").write_text("agent:\n  daybreak: true\n", encoding="utf-8")
    instance = SimpleNamespace(platform=platform, daybreak=not expected)
    scope = set_hermes_home_override(worker)
    try:
        server._sync_agent_daybreak(instance)
        assert instance.daybreak is expected
        call("config.set", key="daybreak", value=False, profile="work")
        server._sync_agent_daybreak(instance)
        assert instance.daybreak is False
    finally:
        reset_hermes_home_override(scope)


@pytest.mark.parametrize("value", ['"true"', '"yes"', "1", "null"])
def test_hand_edited_truthy_values_do_not_enable_daybreak(homes, value):
    launch, _ = homes
    (launch / "config.yaml").write_text(f"agent:\n  daybreak: {value}\n", encoding="utf-8")
    assert call("config.get", key="daybreak")["result"]["value"] is False


def test_real_turn_admission_syncs_the_final_agent_inside_its_profile(homes, monkeypatch):
    import threading

    launch, worker = homes
    (launch / "config.yaml").write_text("agent:\n  daybreak: false\n", encoding="utf-8")
    (worker / "config.yaml").write_text("agent:\n  daybreak: true\n", encoding="utf-8")
    original = SimpleNamespace(platform="desktop", daybreak=False)
    replacement = SimpleNamespace(platform="desktop", daybreak=False)
    session = {"agent": original, "session_key": "admission-key", "profile_home": str(worker),
               "history": [], "history_lock": threading.Lock()}

    class StopAdmission(BaseException):
        pass

    class InlineThread:
        def __init__(self, target, **kwargs):
            self.target = target

        def start(self):
            self.target()

    seen = []

    def after_sync(current):
        seen.append((current["agent"].daybreak, get_hermes_home_override()))
        raise StopAdmission()

    monkeypatch.setattr(server.threading, "Thread", InlineThread)
    monkeypatch.setattr(server, "_set_session_context", lambda *a, **kw: [])
    for name in ("_wire_callbacks", "_apply_pending_model_switch", "_sync_agent_model_with_config",
                 "_sync_agent_compression_with_config", "record_turn_start", "_emit",
                 "_settle_session_turn", "_retire_turn_marker", "_emit_settled_session_info"):
        monkeypatch.setattr(server, name, lambda *a, **kw: None)
    monkeypatch.setattr(server, "_sync_bot_capabilities", lambda sid, current: current.update(agent=replacement))
    monkeypatch.setattr(server, "_session_cwd", after_sync)
    monkeypatch.setattr("hermes_cli.mem_trim.trim_memory", lambda **kw: None)
    with pytest.raises(StopAdmission):
        server._run_prompt_submit("rid", "sid", session, "hello")
    assert seen == [(True, str(worker))]
    assert original.daybreak is False  # a rebuild's replaced agent is not the one used by the turn
    assert replacement.daybreak is True
    assert get_hermes_home_override() is None
