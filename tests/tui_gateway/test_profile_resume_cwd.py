"""Named-profile resume workspaces must stay within their own profile contract."""

from __future__ import annotations

import itertools
from pathlib import Path
import threading

import pytest

from hermes_state import SessionDB
from tui_gateway import server


class _Agent:
    model = "test-model"
    provider = "test"

    def close(self):
        pass


def _write_profile_config(home: Path, cwd: str | None, backend: str | None = None) -> Path:
    import yaml

    home.mkdir(parents=True, exist_ok=True)
    terminal = {}
    if cwd is not None:
        terminal["cwd"] = cwd
    if backend is not None:
        terminal["backend"] = backend
    (home / "config.yaml").write_text(
        yaml.safe_dump({"terminal": terminal} if terminal else {}), encoding="utf-8"
    )
    return home


def _stub_resume(monkeypatch):
    for name, value in {
        "_resolve_model": lambda: "test-model",
        "_enable_gateway_prompts": lambda: None,
        "_find_live_session_by_key": lambda *_a, **_k: None,
        "_schedule_agent_build": lambda *_a, **_k: None,
        "_schedule_session_cap_enforcement": lambda *_a, **_k: None,
        "_maybe_schedule_auto_continue": lambda *_a, **_k: None,
        "_child_run_active": lambda *_a, **_k: False,
        "_set_session_context": lambda *_a, **_k: [],
        "_clear_session_context": lambda *_a, **_k: None,
        "_make_agent": lambda *_a, **_k: _Agent(),
        "_transfer_db_to_agent": lambda *_a, **_k: None,
        "_wire_callbacks": lambda *_a, **_k: None,
        "_start_notification_poller": lambda *_a, **_k: None,
        "_notify_session_boundary": lambda *_a, **_k: None,
        "_emit": lambda *_a, **_k: None,
        "_schedule_mcp_late_refresh": lambda *_a, **_k: None,
        "_session_info": lambda _agent, session=None: {"cwd": (session or {}).get("cwd", "")},
        "_register_session_cwd": lambda *_a, **_k: None,
        "_schedule_resume_hydration": lambda *_a, **_k: None,
    }.items():
        monkeypatch.setattr(server, name, value)
    monkeypatch.setattr(server.git_probe, "branch", lambda _cwd: None)
    monkeypatch.setattr(server.git_probe, "common_repo_root", lambda _cwd: None)


@pytest.fixture
def resume_env(monkeypatch):
    root = server.get_hermes_home()
    root.mkdir(parents=True, exist_ok=True)
    home = _write_profile_config(root / "profiles" / "austin", ".")
    monkeypatch.setenv("TERMINAL_CWD", str(root))
    monkeypatch.setenv("TERMINAL_ENV", "local")
    monkeypatch.setattr(server, "_profile_home", lambda name: home if name else None)
    _stub_resume(monkeypatch)

    profile_db = SessionDB(db_path=home / "state.db")
    launch_db = SessionDB(db_path=root / "state.db")
    monkeypatch.setattr(server, "_get_db", lambda: launch_db)
    known = set(server._sessions)
    next_key = itertools.count()

    def run(stored: str | None, *, profile: str | None = "austin", **flags):
        key = f"resume-cwd-{next(next_key)}"
        db = profile_db if profile else launch_db
        db.create_session(key, source="desktop", model="test-model", cwd=stored)
        db.append_message(key, "user", "question")
        db.append_message(key, "assistant", "answer", finish_reason="stop")
        params = {"session_id": key, **flags}
        if profile:
            params["profile"] = profile
        response = server.handle_request(
            {"id": key, "method": "session.resume", "params": params}
        )
        assert "error" not in response, response
        live = server._sessions[response["result"]["session_id"]]
        return db, key, response["result"], live

    yield root, home, run

    with server._sessions_lock:
        for sid in [sid for sid in server._sessions if sid not in known]:
            server._sessions.pop(sid, None)
    for db in (profile_db, launch_db):
        try:
            db.close()
        except Exception:
            pass


def _read_cwd(db_path: Path, key: str) -> str | None:
    db = SessionDB(db_path=db_path)
    try:
        row = db.get_session(key)
        return row.get("cwd") if row else None
    finally:
        db.close()


@pytest.mark.parametrize("stored_kind", ["root", "sibling", "install", "missing"])
def test_named_profile_resume_uses_its_workspace_for_foreign_or_missing_cwd(
    resume_env, stored_kind
):
    root, home, run = resume_env
    sibling = root / "profiles" / "jordan"
    sibling.mkdir(parents=True, exist_ok=True)
    install = Path(server.__file__).resolve().parent.parent
    stored = {
        "root": str(root),
        "sibling": str(sibling),
        "install": str(install),
        "missing": str(root / "deleted-workspace"),
    }[stored_kind]

    _db, _key, result, live = run(stored, eager_build=True)

    assert live["cwd"] == str(home)
    assert live["explicit_cwd"] is True
    assert server._terminal_task_cwd(live) == str(home)
    assert result["info"]["cwd"] == str(home)
    assert [(m["role"], m["text"]) for m in result["messages"]] == [
        ("user", "question"),
        ("assistant", "answer"),
    ]


@pytest.mark.parametrize("location", ["profile-child", "outside"])
def test_named_profile_resume_keeps_a_user_selected_workspace(resume_env, tmp_path, location):
    root, home, run = resume_env
    selected = home / "workspace" if location == "profile-child" else tmp_path / "chosen"
    selected.mkdir(parents=True, exist_ok=True)

    _db, _key, _result, live = run(str(selected), eager_build=True)

    assert live["cwd"] == str(selected)
    assert live["explicit_cwd"] is True


def test_named_profile_configured_workspace_wins_over_launch_environment(resume_env, tmp_path):
    root, home, run = resume_env
    configured = tmp_path / "profile-workspace"
    configured.mkdir()
    _write_profile_config(home, str(configured), backend="local")

    _db, _key, _result, live = run(None, eager_build=True)

    assert live["cwd"] == str(configured)
    assert server._terminal_task_cwd(live) == str(configured)


def test_lazy_child_resume_selects_profile_workspace_without_repairing_stored_row(resume_env):
    root, home, run = resume_env

    db, key, _result, live = run(str(root), lazy=True)

    assert live["cwd"] == str(home)
    assert _read_cwd(home / "state.db", key) == str(root)


def test_default_profile_keeps_its_valid_hermes_root_workspace(resume_env):
    root, _home, run = resume_env

    _db, _key, _result, live = run(str(root), profile=None, eager_build=True)

    assert live["cwd"] == str(root)
    assert live.get("profile_home") is None


def test_nonlocal_profile_does_not_receive_local_profile_path_filter(resume_env):
    root, home, run = resume_env
    _write_profile_config(home, ".", backend="ssh")
    launch_cwd = str(root)

    _db, key, _result, live = run(launch_cwd, eager_build=True)

    assert live["cwd"] == launch_cwd
    assert _read_cwd(home / "state.db", key) == launch_cwd
    assert server.os.environ["TERMINAL_CWD"] == launch_cwd
