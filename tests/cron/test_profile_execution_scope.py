"""Run cron boundaries while another thread keeps the Desktop launch home."""
import concurrent.futures
import os
from pathlib import Path
import subprocess
import threading
from unittest.mock import MagicMock

import pytest

from cron import scheduler
from hermes_cli.inventory import load_picker_context


@pytest.fixture
def homes(tmp_path, monkeypatch):
    root = tmp_path / "launch"
    worker = root / "profiles" / "worker"
    target = root / "profiles" / "target"
    for name, home in (("launch", root), ("worker", worker), ("target", target)):
        home.mkdir(parents=True, exist_ok=True)
        (home / "config.yaml").write_text(
            'model:\n  provider: openrouter\n  default: ${MODEL_SCOPE_FIXTURE}\n', encoding="utf-8",
        )
        (home / ".env").write_text(
            f'MODEL_SCOPE_FIXTURE={name}-model\nOPENAI_API_KEY=owned-{name}\n', encoding="utf-8",
        )
    monkeypatch.setenv("HERMES_HOME", str(root))
    monkeypatch.setenv("MODEL_SCOPE_FIXTURE", "launch-model")
    monkeypatch.setenv("OPENAI_API_KEY", "owned-launch")
    monkeypatch.setattr(scheduler, "_hermes_home", root)
    monkeypatch.setattr(scheduler, "_resolve_origin", lambda _: None)
    # Keep the production dynamic resolver instead of the suite's deliberate
    # DEFAULT_DB_PATH test override; every resolved home still lives here.
    import hermes_state
    monkeypatch.setattr(hermes_state, "_IMPORT_DEFAULT_DB_PATH", hermes_state.DEFAULT_DB_PATH)
    monkeypatch.setattr("hermes_constants._get_platform_default_hermes_home", lambda: root)
    return root, worker, target


def mock_agent(monkeypatch, captured):
    def construct(**kwargs):
        captured.update(kwargs)
        db = kwargs.get("session_db")
        if db is not None:
            captured["db_path"] = Path(db.db_path)
            db.create_session("owned-cron-scope", "cron")
        agent = MagicMock()
        agent.run_conversation.return_value = {"final_response": "owned-result"}
        return agent

    monkeypatch.setattr("run_agent.AIAgent", construct)
    monkeypatch.setattr("hermes_cli.runtime_provider.resolve_runtime_provider", lambda **kw: {
        "api_key": "owned-key", "base_url": "https://owned.invalid/v1",
        "provider": "openrouter", "api_mode": "chat_completions",
    })
    monkeypatch.setattr("tools.mcp_tool.discover_mcp_tools", lambda: [])


@pytest.mark.parametrize("timeout", [0, 10])
def test_real_job_session_db_belongs_to_execution_profile(homes, monkeypatch, timeout):
    root, worker, _ = homes
    captured = {}
    mock_agent(monkeypatch, captured)
    monkeypatch.setattr(scheduler, "_get_session_db_timeout", lambda: timeout)
    result = scheduler.run_job({"id": "owned", "profile": "worker", "prompt": "owned fixture"})
    assert result[0], result
    assert captured["db_path"] == worker / "state.db"
    if (root / "state.db").exists():
        import sqlite3
        with sqlite3.connect(root / "state.db") as db:
            has_sessions = db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='sessions'").fetchone()
            if has_sessions:
                assert db.execute("SELECT count(*) FROM sessions WHERE id = ?", ("owned-cron-scope",)).fetchone()[0] == 0


@pytest.mark.parametrize("no_agent", [False, True])
def test_running_job_dotenv_cannot_change_desktop_model(homes, monkeypatch, no_agent):
    root, worker, _ = homes
    entered, release = threading.Event(), threading.Event()
    captured = {}
    mock_agent(monkeypatch, captured)

    def hold(*args, **kwargs):
        entered.set()
        assert release.wait(30)
        return (True, "owned-script") if no_agent else []

    if no_agent:
        monkeypatch.setattr(scheduler, "_run_job_script_with_claim_heartbeat", hold)
    else:
        monkeypatch.setattr("tools.mcp_tool.discover_mcp_tools", hold)
    job = {"id": "owned", "profile": "worker", "prompt": "owned fixture"}
    if no_agent:
        job.update(no_agent=True, script="owned.py")
    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(scheduler.run_job, job)
        try:
            assert entered.wait(30)
            assert os.environ["MODEL_SCOPE_FIXTURE"] == "launch-model"
            assert os.environ["OPENAI_API_KEY"] == "owned-launch"
            assert load_picker_context().current_model == "launch-model"
        finally:
            release.set()
        result = future.result(timeout=30)
    assert result[0], result
    assert os.environ["MODEL_SCOPE_FIXTURE"] == "launch-model"
    if not no_agent:
        assert captured["model"] == "worker-model"


@pytest.mark.parametrize("explicit", [False, True])
def test_bot_chat_delivery_child_uses_own_or_explicit_profile(homes, monkeypatch, explicit):
    from hermes_constants import set_hermes_home_override, reset_hermes_home_override
    root, worker, target = homes
    calls = []

    def capture(argv, **kwargs):
        if argv[0] == "owned-hermes":
            calls.append((argv, kwargs["env"]))
        return subprocess.CompletedProcess(argv, 0, "", "")

    monkeypatch.setattr(scheduler.subprocess, "run", capture)
    monkeypatch.setattr(scheduler.shutil, "which", lambda _: "owned-hermes")
    token = set_hermes_home_override(worker)
    try:
        result = scheduler._deliver_to_bot_chat({"id": "owned"}, "owned output", "target" if explicit else "")
    finally:
        reset_hermes_home_override(token)
    assert result is None
    argv, child = calls[0]
    expected = target if explicit else worker
    assert Path(child["HERMES_HOME"]) == expected
    assert child.get("OPENAI_API_KEY") == "owned-" + expected.name
    assert child.get("OPENAI_API_KEY") != "owned-launch"
    assert ("-p" in argv) is explicit
    assert os.environ["HERMES_HOME"] == str(root)


def test_profile_config_env_cache_tracks_context_values_without_global_mutation(homes):
    from agent.secret_scope import set_secret_scope, reset_secret_scope
    from hermes_constants import set_hermes_home_override, reset_hermes_home_override
    _, worker, _ = homes
    home_token = set_hermes_home_override(worker)
    try:
        for model in ("worker-model", "worker-model-rotated"):
            scope_token = set_secret_scope({"MODEL_SCOPE_FIXTURE": model})
            try:
                assert load_picker_context().current_model == model
            finally:
                reset_secret_scope(scope_token)
    finally:
        reset_hermes_home_override(home_token)
    assert load_picker_context().current_model == "launch-model"


def test_cache_projection_does_not_parse_an_unbound_profile_environment(homes, monkeypatch):
    from agent.secret_scope import set_secret_scope, reset_secret_scope
    from hermes_cli.config import peek_effective_config
    from hermes_constants import set_hermes_home_override, reset_hermes_home_override

    _, worker, _ = homes
    home_token = set_hermes_home_override(worker)
    scope_token = set_secret_scope({"MODEL_SCOPE_FIXTURE": "worker-model"})
    try:
        assert load_picker_context().current_model == "worker-model"
        assert peek_effective_config(worker / "config.yaml") is not None
    finally:
        reset_secret_scope(scope_token)

    def forbid_read(*args, **kwargs):
        raise AssertionError("Projection must not parse a profile environment")

    monkeypatch.setattr("agent.secret_scope.build_profile_secret_scope", forbid_read)
    try:
        assert peek_effective_config(worker / "config.yaml") is None
    finally:
        reset_hermes_home_override(home_token)


@pytest.mark.parametrize("profile,expected", [("worker", ""), ("default", "owned-launch-only")])
def test_scoped_cron_provider_cannot_borrow_another_home_key(homes, monkeypatch, profile, expected):
    from hermes_cli.runtime_provider import _getenv

    monkeypatch.setenv("ANTHROPIC_API_KEY", "owned-launch-only")
    with scheduler._cron_profile_context({"profile": profile}), scheduler._cron_profile_environment():
        assert _getenv("ANTHROPIC_API_KEY") == expected


def test_http_model_picker_keeps_launch_profile_during_real_cron_job(homes, monkeypatch):
    """Exercise actual authenticated REST handlers; external catalogue is a double."""
    from starlette.testclient import TestClient
    from hermes_cli import inventory, web_server

    root, worker, _ = homes
    configs_before = {home: (home / "config.yaml").read_bytes() for home in (root, worker)}
    entered, release = threading.Event(), threading.Event()

    def script(*args, **kwargs):
        entered.set()
        assert release.wait(30)
        return True, "owned-output"

    def catalogue(ctx, **kwargs):
        return {"provider": ctx.current_provider, "model": ctx.current_model, "providers": []}

    monkeypatch.setattr(scheduler, "_run_job_script_with_claim_heartbeat", script)
    monkeypatch.setattr(inventory, "build_model_options_payload", catalogue)
    monkeypatch.setattr(web_server, "_dashboard_code_skew_guard", lambda: None)
    monkeypatch.setattr("agent.model_metadata.get_model_context_length", lambda **kwargs: 131072)
    monkeypatch.setattr("agent.models_dev.get_model_capabilities", lambda **kwargs: None)
    with TestClient(web_server.app) as client, concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
        client.headers[web_server._SESSION_HEADER_NAME] = web_server._SESSION_TOKEN
        future = pool.submit(scheduler.run_job, {
            "id": "owned", "profile": "worker", "no_agent": True, "script": "owned.py",
        })
        try:
            assert entered.wait(30)
            for endpoint in ("info", "options"):
                for profile, expected in ((None, "launch-model"), ("worker", "worker-model"), (None, "launch-model")):
                    response = client.get(f"/api/model/{endpoint}", params={"profile": profile} if profile else {})
                    assert response.status_code == 200, response.text
                    assert response.json()["model"] == expected
                    assert response.json()["provider"] == "openrouter"
        finally:
            release.set()
        assert future.result(timeout=30)[0]
    assert os.environ["HERMES_HOME"] == str(root)
    assert all((home / "config.yaml").read_bytes() == before for home, before in configs_before.items())
