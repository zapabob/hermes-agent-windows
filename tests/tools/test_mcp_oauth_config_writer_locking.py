"""Persisted config transactions and lock-free side effects; no live services."""
from contextlib import contextmanager
import threading

import pytest
import yaml


@contextmanager
def paused_worker(action):
    entered, release = threading.Event(), threading.Event()
    errors, results = [], []
    def pause():
        entered.set()
        if not release.wait(10):
            raise TimeoutError("test barrier was not released")
    def run():
        try:
            results.append(action(pause))
        except BaseException as exc:
            errors.append(exc)
    worker = threading.Thread(target=run, daemon=True)
    worker.start()
    try:
        assert entered.wait(10), "worker did not reach operation barrier"
        yield results
    finally:
        release.set()
        worker.join(10)
    assert not worker.is_alive(), "worker did not settle"
    assert not errors, errors


def assert_lock_available(lock, expected):
    acquired = lock.acquire(blocking=False)
    try:
        assert acquired is expected
    finally:
        if acquired:
            lock.release()


@pytest.fixture
def config_file(monkeypatch, tmp_path):
    from hermes_cli import config, managed_scope
    path = tmp_path / "config.yaml"
    path.write_text(
        "terminal:\n  cwd: old\n  backend: local\n"
        "mcp_servers:\n  target:\n    command: old\n"
        "keep: $" "{KEEP_RAW}\n", encoding="utf-8"
    )
    monkeypatch.setattr(config, "get_config_path", lambda: path)
    monkeypatch.setattr(config, "get_hermes_home", lambda: tmp_path)
    monkeypatch.setattr(config, "ensure_hermes_home", lambda: None)
    monkeypatch.setattr(config, "is_managed", lambda: False)
    monkeypatch.setattr(managed_scope, "is_key_managed", lambda _key: False)
    monkeypatch.setattr(managed_scope, "managed_config_keys", lambda: set())
    monkeypatch.setattr(config, "terminal_config_env_var_for_key", lambda _key: None)
    monkeypatch.setattr(config, "warn_unpinned_cron_jobs_after_model_config_change", lambda *_a, **_k: None)
    monkeypatch.setattr(config, "_CONFIG_LOCK", threading.RLock())
    return path


@pytest.mark.parametrize("operation", ["save", "remove", "replace"])
def test_mcp_writers_hold_live_lock_and_persist(monkeypatch, config_file, operation):
    from hermes_cli import config, mcp_config
    original_read = mcp_config._read_raw_mcp_config
    def action(pause):
        def read():
            document = original_read()
            pause()
            return document
        monkeypatch.setattr(mcp_config, "_read_raw_mcp_config", read)
        if operation == "save":
            mcp_config._save_mcp_server("target", {"command": "new"})
        elif operation == "remove":
            mcp_config._remove_mcp_server("target")
        else:
            mcp_config._replace_mcp_servers({"target": {"command": "new"}})
    with paused_worker(action):
        assert_lock_available(config._CONFIG_LOCK, False)
    saved = yaml.safe_load(config_file.read_text(encoding="utf-8"))
    assert saved["keep"] == "$" "{KEEP_RAW}"
    assert saved["terminal"]["cwd"] == "old"
    if operation == "remove":
        assert "target" not in saved.get("mcp_servers", {})
    else:
        assert saved["mcp_servers"]["target"] == {"command": "new"}


@pytest.mark.parametrize("operation", ["cli_single", "cli_multi", "set", "unset"])
def test_four_writers_serialize_real_rmw(monkeypatch, config_file, operation):
    import cli
    from ruamel.yaml import YAML
    from hermes_cli import config, mcp_config
    monkeypatch.setattr(cli, "get_hermes_home", lambda: config_file.parent)
    real_rt_read = YAML.load
    real_raw_read = config.require_readable_config_before_write
    writer_ident = []
    def action(pause):
        writer_ident.append(threading.get_ident())
        def rt_read(self, stream):
            document = real_rt_read(self, stream)
            if threading.get_ident() == writer_ident[0]:
                pause()
            return document
        def raw_read(*args, **kwargs):
            document = real_raw_read(*args, **kwargs)
            if threading.get_ident() == writer_ident[0]:
                pause()
            return document
        monkeypatch.setattr(YAML, "load", rt_read)
        monkeypatch.setattr(config, "require_readable_config_before_write", raw_read)
        if operation == "cli_single":
            assert cli.save_config_value("terminal.cwd", "new")
        elif operation == "cli_multi":
            assert cli.save_config_values({"terminal.cwd": "new", "terminal.backend": "local"})
        elif operation == "set":
            config.set_config_value("terminal.cwd", "new")
        else:
            config.unset_config_value("terminal.cwd")
    failures = []
    attempted = threading.Event()
    def replace_target():
        attempted.set()
        try:
            mcp_config._replace_mcp_servers({"target": {"command": "newer"}})
        except BaseException as exc:
            failures.append(exc)
    contender = None
    try:
        with paused_worker(action):
            assert_lock_available(config._CONFIG_LOCK, False)
            contender = threading.Thread(target=replace_target, daemon=True)
            contender.start()
            assert attempted.wait(10)
    finally:
        if contender is not None:
            contender.join(10)
    assert contender is not None and not contender.is_alive()
    assert not failures, failures
    saved = yaml.safe_load(config_file.read_text(encoding="utf-8"))
    assert saved["mcp_servers"]["target"] == {"command": "newer"}
    assert saved["keep"] == "$" "{KEEP_RAW}"
    if operation == "unset":
        assert "cwd" not in saved["terminal"]
    else:
        assert saved["terminal"]["cwd"] == "new"


@pytest.mark.parametrize("stage", ["secret", "warning", "unset_secret"])
def test_side_effects_run_after_lock_release(monkeypatch, config_file, stage):
    from hermes_cli import config
    def action(pause):
        if stage == "warning":
            monkeypatch.setattr(config, "warn_unpinned_cron_jobs_after_model_config_change", lambda *_a, **_k: pause())
            config.set_config_value("model.default", "synthetic-model")
        else:
            monkeypatch.setattr(config, "terminal_config_env_var_for_key", lambda _k: "SYNTHETIC_TEST_KEY")
            if stage == "secret":
                monkeypatch.setattr(config, "save_env_value", lambda *_a, **_k: pause())
                config.set_config_value("terminal.backend", "local")
            else:
                monkeypatch.setattr(config, "remove_env_value", lambda *_a, **_k: (pause(), True)[1])
                config.unset_config_value("terminal.backend")
    with paused_worker(action):
        assert_lock_available(config._CONFIG_LOCK, True)


def test_rest_lock_replaced_and_nested_exception_released(monkeypatch):
    from hermes_cli import config, web_server
    adapter = web_server._DynamicConfigMutationLock()
    live_lock = threading.RLock()
    monkeypatch.setattr(config, "_CONFIG_LOCK", live_lock)
    class Expected(Exception):
        pass
    def action(pause):
        with pytest.raises(Expected):
            with adapter:
                with adapter:
                    pause()
                    raise Expected()
    with paused_worker(action):
        assert_lock_available(live_lock, False)
    assert_lock_available(live_lock, True)
