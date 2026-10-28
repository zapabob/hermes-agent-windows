"""``/delegation`` slash — ask_choice path + deferred / --now apply."""

from __future__ import annotations

from dataclasses import dataclass
from unittest.mock import MagicMock

import pytest

from agent.delegation_command import handle_delegation_slash


@dataclass
class _Info:
    name: str
    label: str
    description: str
    available: bool = True


@pytest.fixture(autouse=True)
def _isolate(tmp_path, monkeypatch):
    home = tmp_path / ".hermes"
    home.mkdir()
    (home / "config.yaml").write_text("delegation:\n  backend: default\n", encoding="utf-8")
    monkeypatch.setenv("HERMES_HOME", str(home))
    monkeypatch.setattr("pathlib.Path.home", lambda: tmp_path)
    yield home


def test_ask_choice_sets_backend_deferred(monkeypatch):
    calls: dict[str, object] = {}

    def fake_set(name, *, session_key="", apply_now=False):
        calls["name"] = name
        calls["session_key"] = session_key
        calls["apply_now"] = apply_now

    monkeypatch.setattr(
        "agent.delegation_command.list_backends",
        lambda: [
            _Info("default", "Default", "d"),
            _Info("model_map", "Model map", "m"),
        ],
    )
    monkeypatch.setattr("agent.delegation_command.saved_backend", lambda: "default")
    monkeypatch.setattr("agent.delegation_command.set_global_backend", fake_set)

    msg = handle_delegation_slash(
        "",
        ask_choice=lambda question, choices: "model_map",
    )
    assert calls == {"name": "model_map", "session_key": "", "apply_now": False}
    assert "model_map" in msg
    assert "next session" in msg.lower() or "Takes effect" in msg


def test_direct_arg_and_now_requires_session(monkeypatch):
    calls: dict[str, object] = {}

    def fake_set(name, *, session_key="", apply_now=False):
        if apply_now and not session_key:
            raise ValueError("No session to apply the switch to")
        calls.update(name=name, session_key=session_key, apply_now=apply_now)

    monkeypatch.setattr("agent.delegation_command.saved_backend", lambda: "default")
    monkeypatch.setattr("agent.delegation_command.set_global_backend", fake_set)
    monkeypatch.setattr("agent.delegation_command._session_key", lambda: "")

    msg = handle_delegation_slash("model_map --now", ask_choice=lambda *_: None)
    assert "No session" in msg
    assert calls == {}

    monkeypatch.setattr("agent.delegation_command._session_key", lambda: "sess-1")
    msg2 = handle_delegation_slash("model_map --now", ask_choice=lambda *_: None)
    assert calls == {"name": "model_map", "session_key": "sess-1", "apply_now": True}
    assert "rebuild" in msg2.lower() or "queued" in msg2.lower()


def test_cancel_ask_choice_keeps_current(monkeypatch):
    monkeypatch.setattr(
        "agent.delegation_command.list_backends",
        lambda: [_Info("default", "Default", "")],
    )
    monkeypatch.setattr("agent.delegation_command.saved_backend", lambda: "default")
    set_mock = MagicMock()
    monkeypatch.setattr("agent.delegation_command.set_global_backend", set_mock)

    msg = handle_delegation_slash("", ask_choice=lambda *_: None)
    set_mock.assert_not_called()
    assert "Current delegation backend: default" in msg
