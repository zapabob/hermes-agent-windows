"""An unavailable explicit target must never become the launch profile."""

from pathlib import Path

import pytest


def test_explicit_profile_target_never_falls_back(tmp_path, monkeypatch):
    from hermes_state import SessionDB
    from tui_gateway import server

    home = tmp_path / ".hermes"
    worker = home / "profiles" / "worker"
    worker.mkdir(parents=True)
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    monkeypatch.setenv("HERMES_HOME", str(home))
    monkeypatch.setattr(server, "_hermes_home", home)
    for path, marker in ((home, "launch"), (worker, "worker")):
        (path / "config.yaml").write_text(
            f"terminal:\n  cwd: /{marker}\n", encoding="utf-8"
        )
        with SessionDB(db_path=path / "state.db") as db:
            db.create_session(marker, "tui")
    for name, marker in (
        (None, "launch"),
        ("default", "launch"),
        ("DEFAULT", "launch"),
        ("worker", "worker"),
    ):
        with server._profile_db({"profile": name}) as db:
            assert db.get_session(marker)
        response = server._methods["config.get"](1, {"profile": name, "key": "full"})
        assert response["result"]["config"]["terminal"]["cwd"] == f"/{marker}"
    before = (home / "config.yaml").read_bytes()
    worker.rename(worker.with_name("gone"))
    for name in ("worker", "unknown"):
        with pytest.raises(FileNotFoundError):
            with server._profile_db({"profile": name}):
                pytest.fail("unavailable profile reached a database")
        with pytest.raises(FileNotFoundError):
            server._methods["config.set"](
                2, {"profile": name, "key": "busy", "value": "steer"}
            )
        assert (home / "config.yaml").read_bytes() == before
    # A real resolution I/O failure must propagate, too (no predicate patch).
    profiles = home / "profiles"
    profiles.rename(home / "saved-profiles")
    try:
        profiles.symlink_to("profiles")
    except OSError:
        # Windows sessions without SeCreateSymbolicLinkPrivilege still prove
        # that get_profile_dir I/O failures never soft-fall back to launch.
        monkeypatch.setattr(
            "hermes_cli.profiles.get_profile_dir",
            lambda name: (_ for _ in ()).throw(OSError("profiles store unreadable")),
        )
    with pytest.raises((OSError, RuntimeError)):
        server._profile_home("worker")


def test_tools_configure_stale_session_mutates_nothing(tmp_path, monkeypatch):
    """Explicit stale session_id must fail closed before save_config (026e3e84)."""
    from hermes_cli import config as hermes_config
    from tui_gateway import methods_tools, server

    home = tmp_path / ".hermes"
    home.mkdir()
    cfg_path = home / "config.yaml"
    cfg_path.write_text("tools: {}\n", encoding="utf-8")
    monkeypatch.setenv("HERMES_HOME", str(home))
    monkeypatch.setattr(server, "_hermes_home", home)
    monkeypatch.setattr(server, "_sessions", {})

    before = cfg_path.read_bytes()
    saved = {"called": False}

    def _boom_save(_cfg):
        saved["called"] = True
        raise AssertionError("save_config must not run for a stale session")

    monkeypatch.setattr(hermes_config, "save_config", _boom_save)
    monkeypatch.setattr(hermes_config, "load_config", lambda: {"tools": {}})

    # Install methods_* globals onto server so _sess_nowait/_err resolve.
    methods_tools._registry.install(server)
    response = server._methods["tools.configure"](
        9,
        {
            "session_id": "gone-runtime",
            "action": "disable",
            "names": ["web"],
        },
    )
    assert "error" in response
    assert response["error"]["code"] == 4001
    assert "session not found" in response["error"]["message"].lower()
    assert saved["called"] is False
    assert cfg_path.read_bytes() == before
