"""Windows local-background persistence is an explicit process choice."""

from __future__ import annotations

import json
import sys
from types import SimpleNamespace

import pytest

from tools import process_registry as registry_module
from tools import terminal_tool as terminal_module


def test_terminal_requires_background_and_forwards_explicit_persistence(monkeypatch):
    calls = []
    monkeypatch.setattr(terminal_module, "terminal_tool", lambda **kwargs: calls.append(kwargs) or "{}")

    refused = json.loads(terminal_module._handle_terminal({
        "command": "echo safe", "persist_on_release": True,
    }))
    assert "error" in refused
    assert calls == []

    terminal_module._handle_terminal({
        "command": "echo safe", "background": True, "persist_on_release": True,
    })
    assert calls[0]["persist_on_release"] is True
    assert terminal_module.TERMINAL_SCHEMA["parameters"]["properties"]["persist_on_release"]["default"] is False
    invalid = json.loads(terminal_module._handle_terminal({
        "command": "echo safe", "background": True, "persist_on_release": "true",
    }))
    assert "error" in invalid
    assert len(calls) == 1


def test_terminal_refuses_nonlocal_persistence_before_spawning(monkeypatch):
    monkeypatch.setattr(terminal_module, "_get_env_config", lambda: {"env_type": "docker"})
    refused = json.loads(terminal_module.terminal_tool(
        "echo safe", background=True, persist_on_release=True,
    ))
    assert "local terminal backend" in refused["error"]


def test_registered_terminal_path_stamps_local_background_session(tmp_path, monkeypatch):
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    monkeypatch.setenv("TERMINAL_ENV", "local")
    monkeypatch.setenv("TERMINAL_CWD", str(tmp_path))
    calls = []

    def fake_spawn_local(**kwargs):
        calls.append(kwargs)
        return SimpleNamespace(id="proc_n28", pid=12345)

    monkeypatch.setattr(registry_module.process_registry, "spawn_local", fake_spawn_local)
    result = json.loads(terminal_module._handle_terminal({
        "command": "echo N28", "background": True, "persist_on_release": True,
    }, task_id="n28-caller"))
    assert result["session_id"] == "proc_n28", result
    assert result["persist_on_release"] is True
    assert calls[0]["persist_on_release"] is True


def test_lifecycle_sweeps_skip_only_explicitly_persisted_sessions(monkeypatch):
    registry = registry_module.ProcessRegistry()
    persisted = registry_module.ProcessSession(
        id="proc_persisted", command="fixture", task_id="session-a", persist_on_release=True,
    )
    ordinary = registry_module.ProcessSession(
        id="proc_ordinary", command="fixture", task_id="session-a",
    )
    registry._running.update({persisted.id: persisted, ordinary.id: ordinary})
    killed = []

    def fake_kill(session_id, **kwargs):
        killed.append((session_id, kwargs["source"]))
        return {"status": "killed"}

    monkeypatch.setattr(registry, "kill_process", fake_kill)
    listed = {item["session_id"]: item for item in registry.list_sessions()}
    assert listed[persisted.id]["persist_on_release"] is True
    assert "persist_on_release" not in listed[ordinary.id]
    for source in ("kill_all", "gateway_turn_timeout", "agent_close"):
        assert registry.kill_all("session-a", source=source) == 1
        assert killed.pop() == (ordinary.id, source)
    assert registry.kill_started_since(
        "session-a", frozenset(), source="gateway_turn_timeout",
    ) == 1
    assert killed.pop() == (ordinary.id, "gateway_turn_timeout")
    assert registry.kill_all("session-a", source="cli.stop") == 2
    assert sorted(killed) == [(ordinary.id, "cli.stop"), (persisted.id, "cli.stop")]
    killed.clear()
    assert registry.kill_all("session-a", source="gateway_shutdown") == 2
    assert sorted(killed) == [(ordinary.id, "gateway_shutdown"), (persisted.id, "gateway_shutdown")]


@pytest.mark.skipif(sys.platform != "win32", reason="N28 native Windows local-process contract")
def test_native_local_spawn_survives_lifecycle_sweep_and_can_be_stopped(tmp_path, monkeypatch):
    monkeypatch.setattr(registry_module, "CHECKPOINT_PATH", tmp_path / "processes.json")
    registry = registry_module.ProcessRegistry()
    command = f'"{sys.executable}" -c "import time; time.sleep(20)"'
    session = registry.spawn_local(
        command, cwd=str(tmp_path), task_id="session-a", persist_on_release=True,
    )
    try:
        assert session.persist_on_release is True
        assert registry.kill_all("session-a", source="kill_all") == 0
        assert session.process is not None and session.process.poll() is None
        assert registry.kill_all("session-a", source="cli.stop") == 1
        assert session.process.wait(timeout=5) is not None
    finally:
        registry.kill_process(session.id, source="n28_test_cleanup")


def test_checkpoint_recovery_preserves_persistence_flag(tmp_path, monkeypatch):
    checkpoint = tmp_path / "processes.json"
    monkeypatch.setattr(registry_module, "CHECKPOINT_PATH", checkpoint)
    registry = registry_module.ProcessRegistry()
    session = registry_module.ProcessSession(
        id="proc_recover", command="fixture", pid=12345, task_id="session-a",
        host_start_time=6789, persist_on_release=True,
    )
    registry._running[session.id] = session
    registry._write_checkpoint()
    assert json.loads(checkpoint.read_text(encoding="utf-8"))[0]["persist_on_release"] is True

    successor = registry_module.ProcessRegistry()
    monkeypatch.setattr(successor, "_host_pid_is_ours", lambda *_args: True)
    assert successor.recover_from_checkpoint() == 1
    assert successor.get(session.id).persist_on_release is True
