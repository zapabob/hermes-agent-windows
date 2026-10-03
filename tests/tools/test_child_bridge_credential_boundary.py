"""Actual native child probes through the bridge/server spawn owners."""

import json
import subprocess
import sys
import pytest

from gateway.config import PlatformConfig
from hermes_constants import set_hermes_home_override, reset_hermes_home_override

SECRET = "TEST_ONLY_SECRET_DO_NOT_USE"
KEYS = ("OPENAI_API_KEY", "TELEGRAM_WEBHOOK_SECRET", "RAFT_CHANNEL_TOKEN", "BOUNDARY_BENIGN", "RAFT_PROFILE", "HOME")


@pytest.fixture(autouse=True)
def isolated_launch_identity(monkeypatch):
    from hermes_cli import env_loader
    monkeypatch.setattr(env_loader, "_LAUNCH_PROFILE_HOME", None, raising=False)


def native_probe(monkeypatch, module, tmp_path):
    observed_path = tmp_path / "observed.json"
    real_popen = subprocess.Popen
    calls = []
    code = (
        "import json,os,pathlib;pathlib.Path(" + repr(str(observed_path)) + ").write_text("
        "json.dumps({k:os.environ.get(k) for k in " + repr(KEYS) + "}),encoding='utf-8')"
    )

    def launch(argv, **kwargs):
        calls.append(argv)
        process = real_popen([sys.executable, "-I", "-c", code], **kwargs)
        assert process.wait(timeout=15) == 0
        return process

    monkeypatch.setattr(module.subprocess, "Popen", launch)
    return calls, observed_path


def test_raft_bridge_only_receives_its_scoped_authority(monkeypatch, tmp_path):
    from agent.secret_scope import set_secret_scope, reset_secret_scope
    from plugins.platforms.raft import adapter as raft

    monkeypatch.setenv("RAFT_PROFILE", "launch-profile")
    monkeypatch.setenv("OPENAI_API_KEY", SECRET)
    monkeypatch.setenv("TELEGRAM_WEBHOOK_SECRET", SECRET)
    monkeypatch.setenv("BOUNDARY_BENIGN", "present")
    (tmp_path / "home").mkdir()
    (tmp_path / "real-home").mkdir()
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    monkeypatch.setenv("HERMES_REAL_HOME", str(tmp_path / "real-home"))
    monkeypatch.setenv("TERMINAL_HOME_MODE", "profile")
    real_which = raft.shutil.which
    monkeypatch.setattr(raft.shutil, "which", lambda name: sys.executable if name == "raft" else real_which(name))
    calls, output = native_probe(monkeypatch, raft, tmp_path)
    adapter = raft.RaftAdapter(PlatformConfig(enabled=True, extra={"bridge_token": "TEST_ONLY_BRIDGE"}))
    token = set_secret_scope({"RAFT_PROFILE": "served-profile"})
    try:
        adapter._spawn_bridge(18765)
    finally:
        reset_secret_scope(token)
    assert len(calls) == 1
    assert calls[0][calls[0].index("--profile") + 1] == "served-profile"
    observed = json.loads(output.read_text(encoding="utf-8"))
    assert observed == {
        "OPENAI_API_KEY": None, "TELEGRAM_WEBHOOK_SECRET": None,
        "RAFT_CHANNEL_TOKEN": "TEST_ONLY_BRIDGE", "BOUNDARY_BENIGN": "present",
        "RAFT_PROFILE": "served-profile", "HOME": str(tmp_path / "real-home"),
    }


def test_openviking_server_receives_served_provider_without_launch_secrets(monkeypatch, tmp_path):
    from plugins.memory import openviking

    launch, served = tmp_path / "launch", tmp_path / "served"
    launch.mkdir()
    served.mkdir()
    (served / "home").mkdir()
    (tmp_path / "real-home").mkdir()
    (launch / ".env").write_text(f"OPENAI_API_KEY={SECRET}\n", encoding="utf-8")
    (served / ".env").write_text("OPENAI_API_KEY=TEST_ONLY_SERVED\n", encoding="utf-8")
    monkeypatch.setenv("HERMES_HOME", str(launch))
    monkeypatch.setenv("OPENAI_API_KEY", SECRET)
    monkeypatch.setenv("TELEGRAM_WEBHOOK_SECRET", SECRET)
    monkeypatch.setenv("BOUNDARY_BENIGN", "present")
    monkeypatch.setenv("HERMES_REAL_HOME", str(tmp_path / "real-home"))
    monkeypatch.setenv("TERMINAL_HOME_MODE", "profile")
    monkeypatch.setattr(openviking, "_local_openviking_port_is_open", lambda *_: False)
    real_which = openviking.shutil.which
    monkeypatch.setattr(openviking.shutil, "which", lambda name: sys.executable if name == "openviking-server" else real_which(name))
    monkeypatch.setattr(openviking, "_openviking_server_log_path", lambda: tmp_path / "server.log")
    calls, output = native_probe(monkeypatch, openviking, tmp_path)
    token = set_hermes_home_override(served)
    try:
        status, message = openviking._start_local_openviking_server("http://127.0.0.1:18765")
    finally:
        reset_hermes_home_override(token)
    assert status == openviking._LOCAL_SERVER_STARTED, message
    assert len(calls) == 1
    observed = json.loads(output.read_text(encoding="utf-8"))
    assert observed["OPENAI_API_KEY"] == "TEST_ONLY_SERVED"
    assert observed["TELEGRAM_WEBHOOK_SECRET"] is None
    assert observed["BOUNDARY_BENIGN"] == "present"
    assert observed["HOME"] == str(tmp_path / "real-home")
