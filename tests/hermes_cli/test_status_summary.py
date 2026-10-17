"""The default status is useful, bounded and observational."""

import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
from types import SimpleNamespace

import pytest

from hermes_cli import status
from hermes_cli.subcommands.status import build_status_parser


def test_status_parser_accepts_short_and_full_modes():
    parser = argparse.ArgumentParser()
    build_status_parser(parser.add_subparsers(), cmd_status=lambda args: None)
    assert parser.parse_args(["status", "--full"]).full
    assert parser.parse_args(["status", "--short"]).short
    with pytest.raises(SystemExit):
        parser.parse_args(["status", "--full", "--short"])


def test_default_summary_has_core_facts_without_detailed_key_inventory(tmp_path, monkeypatch, capsys):
    from gateway import config as gateway_config
    from hermes_cli import gateway

    monkeypatch.setattr(status, "load_config", lambda: {"model": {"default": "owned-local-model"}})
    monkeypatch.setattr(status, "get_hermes_home", lambda: tmp_path)
    monkeypatch.setattr(status, "_effective_provider_label", lambda: "Custom")
    monkeypatch.setattr(status, "_estop_status_line", lambda: None)
    monkeypatch.setattr(gateway, "get_gateway_runtime_snapshot", lambda: SimpleNamespace(running=True, manager="owned"))
    monkeypatch.setattr(gateway_config, "load_gateway_config", lambda: SimpleNamespace(get_connected_platforms=lambda: []))
    (tmp_path / "cron").mkdir()
    (tmp_path / "cron" / "jobs.json").write_text(json.dumps({"jobs": [{"enabled": True}, {"enabled": False}]}), encoding="utf-8")
    status.show_status(SimpleNamespace())
    output = capsys.readouterr().out
    assert "owned-local-model" in output
    assert "Custom" in output
    assert "Gateway:" in output and "running" in output
    assert "Platforms:" in output
    assert "1 active, 2 total" in output
    assert "--full" in output
    assert "◆ API Keys" not in output
    assert len(output.splitlines()) <= 15


def test_summary_probe_failure_is_unknown_and_keeps_other_rows(tmp_path, monkeypatch, capsys):
    from hermes_cli import gateway

    def failed():
        raise RuntimeError("synthetic observation failure")

    monkeypatch.setattr(status, "load_config", lambda: {"model": "owned-model"})
    monkeypatch.setattr(status, "get_hermes_home", lambda: tmp_path)
    monkeypatch.setattr(status, "_effective_provider_label", lambda: "Custom")
    monkeypatch.setattr(status, "_estop_status_line", lambda: None)
    monkeypatch.setattr(gateway, "get_gateway_runtime_snapshot", failed)
    status.show_status(SimpleNamespace())
    output = capsys.readouterr().out
    assert "owned-model" in output
    assert "Gateway:" in output and "unknown" in output.lower()
    assert "Jobs:" in output


def test_summary_does_not_create_home_or_probe_remote_endpoints(tmp_path, monkeypatch, capsys):
    import socket
    from gateway import config as gateway_config
    from hermes_cli import gateway

    home = tmp_path / "not-created"
    monkeypatch.setattr(status, "get_hermes_home", lambda: home)
    monkeypatch.setattr(status, "load_config", lambda: {"model": {"default": "local", "provider": "custom"}})
    monkeypatch.setattr(status, "_effective_provider_label", lambda: "Custom")
    monkeypatch.setattr(status, "_estop_status_line", lambda: None)
    monkeypatch.setattr(gateway, "get_gateway_runtime_snapshot", lambda: SimpleNamespace(running=False, manager="manual"))
    monkeypatch.setattr(gateway_config, "load_gateway_config", lambda: SimpleNamespace(get_connected_platforms=lambda: []))

    def forbidden(*args, **kwargs):
        pytest.fail("summary must not contact a remote endpoint")

    monkeypatch.setattr(socket, "create_connection", forbidden)
    status.show_status(SimpleNamespace())
    assert not home.exists()
    assert "stopped" in capsys.readouterr().out


def test_public_short_status_in_fresh_process_is_observational(tmp_path):
    home = tmp_path / "cli-home"
    home.mkdir()
    configuration = "model:\n  provider: custom\n  default: owned-local-model\n  base_url: http://127.0.0.1:9/v1\n"
    (home / "config.yaml").write_text(configuration, encoding="utf-8")
    environment = dict(os.environ, HERMES_HOME=str(home), HERMES_TEST_ISOLATION=str(home),
                       PYTHONUTF8="1", PYTHONDONTWRITEBYTECODE="1")
    program = """
import sys
attempts = []
def audit(event, args):
    if event in {'socket.connect', 'socket.getaddrinfo'}:
        attempts.append(event)
        raise RuntimeError('status must not access a network endpoint')
sys.addaudithook(audit)
from hermes_cli.main import main
sys.argv = ['hermes', 'status', '--short']
try:
    main()
except SystemExit as exc:
    if exc.code not in (None, 0):
        raise
assert not attempts, attempts
"""
    result = subprocess.run([sys.executable, "-B", "-c", program],
                            cwd=Path(__file__).resolve().parents[2], env=environment,
                            capture_output=True, text=True, encoding="utf-8", timeout=60)
    assert result.returncode == 0, result.stderr
    assert "owned-local-model" in result.stdout
    assert "Gateway:" in result.stdout
    assert "◆ API Keys" not in result.stdout
    assert (home / "config.yaml").read_text(encoding="utf-8") == configuration
    assert not (home / "cron" / "jobs.json").exists()
