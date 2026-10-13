"""Every non-watch resume path repairs a named profile's saved workspace."""

from __future__ import annotations

import itertools

import pytest

from hermes_state import SessionDB
from tui_gateway import server


class _Agent:
    model = "test-model"
    provider = "test"

    def close(self):
        pass


def _write_profile_config(home, cwd: str | None) -> None:
    import yaml

    home.mkdir(parents=True, exist_ok=True)
    (home / "config.yaml").write_text(
        yaml.safe_dump({"terminal": {"cwd": cwd}}), encoding="utf-8"
    )


@pytest.fixture
def resume_paths(monkeypatch):
    root = server.get_hermes_home()
    root.mkdir(parents=True, exist_ok=True)
    home = root / "profiles" / "austin"
    _write_profile_config(home, ".")
    monkeypatch.setenv("TERMINAL_CWD", str(root))
    monkeypatch.setenv("TERMINAL_ENV", "local")
    monkeypatch.setattr(server, "_profile_home", lambda name: home if name else None)
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

    db = SessionDB(db_path=home / "state.db")
    known = set(server._sessions)
    next_key = itertools.count()

    def run(flags: dict):
        key = f"resume-persist-{next(next_key)}"
        db.create_session(key, source="desktop", model="test-model", cwd=str(root))
        db.append_message(key, "user", "question")
        db.append_message(key, "assistant", "answer", finish_reason="stop")
        params = {"session_id": key, "profile": "austin", **flags}
        result = server.handle_request(
            {"id": key, "method": "session.resume", "params": params}
        )
        assert "error" not in result, result
        live = server._sessions[result["result"]["session_id"]]
        return key, result["result"], live

    yield root, home, db, run

    with server._sessions_lock:
        for sid in [sid for sid in server._sessions if sid not in known]:
            server._sessions.pop(sid, None)
    db.close()


@pytest.mark.parametrize(
    ("flags", "response_messages"),
    [
        pytest.param({}, [("user", "question"), ("assistant", "answer")], id="cold"),
        pytest.param({"defer_history": True}, [], id="deferred"),
        pytest.param(
            {"eager_build": True}, [("user", "question"), ("assistant", "answer")], id="eager"
        ),
    ],
)
def test_each_resume_path_repairs_the_saved_workspace_without_changing_transcript(
    resume_paths, flags, response_messages
):
    root, home, db, run = resume_paths

    key, result, live = run(flags)

    assert live["cwd"] == str(home)
    if flags.get("defer_history"):
        assert result["messages"] == []
        assert result["hydrating"] is True
        assert result["message_count"] == 2
    else:
        assert [(m["role"], m["text"]) for m in result["messages"]] == response_messages
    assert db.get_session(key)["cwd"] == str(home)
