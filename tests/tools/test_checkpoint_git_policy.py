"""The private shadow store owns Git config independently of user repos."""
import subprocess
from pathlib import Path

from tools import checkpoint_manager as cp


def test_shadow_commands_drop_ambient_config_injection(tmp_path, monkeypatch):
    work = tmp_path / "work"
    work.mkdir()
    store = tmp_path / "private" / "store"
    assert cp._init_store(store, str(work)) is None
    monkeypatch.setenv("GIT_CONFIG_COUNT", "1")
    monkeypatch.setenv("GIT_CONFIG_KEY_0", "user.name")
    monkeypatch.setenv("GIT_CONFIG_VALUE_0", "AMBIENT_FIXTURE")
    ok, value, error = cp._run_git(["config", "--get", "user.name"], store, str(work))
    assert ok, error
    assert value == "Hermes Checkpoint"


def test_shadow_init_does_not_copy_ambient_template(tmp_path, monkeypatch):
    template = tmp_path / "owned-template"
    template.mkdir()
    (template / "owned-template-marker").write_text("FIXTURE", encoding="utf-8")
    monkeypatch.setenv("GIT_TEMPLATE_DIR", str(template))
    work = tmp_path / "work"
    work.mkdir()
    store = tmp_path / "private" / "store"
    assert cp._init_store(store, str(work)) is None
    assert not (store / "owned-template-marker").exists()
    assert (template / "owned-template-marker").read_text(encoding="utf-8") == "FIXTURE"


def test_shadow_init_reports_config_write_failure(tmp_path, monkeypatch):
    work = tmp_path / "work"
    work.mkdir()
    monkeypatch.setattr(cp, "_run_git", lambda *a, **kw: (False, "", "owned config failure"))
    error = cp._init_store(tmp_path / "private" / "store", str(work))
    assert error and "owned config failure" in error


def test_shadow_timeout_uses_existing_bounded_owner(tmp_path, monkeypatch):
    work = tmp_path / "work"
    work.mkdir()
    monkeypatch.setattr(cp, "bounded_probe_run", lambda *a, **kw: None, raising=False)
    ok, stdout, error = cp._run_git(["status"], tmp_path / "store", str(work), timeout=1)
    assert not ok
    assert not stdout
    assert "timed out or could not start" in error


def test_shadow_store_preserves_project_config_and_separate_index(tmp_path):
    work = tmp_path / "work"
    work.mkdir()
    git_dir = work / ".git"
    git_dir.mkdir()
    config = git_dir / "config"
    config.write_text("[invalid\n", encoding="utf-8")
    before = config.read_bytes()
    store = tmp_path / "private" / "store"
    assert cp._init_store(store, str(work)) is None
    index = store / "indexes" / "project-owned"
    ok, _, error = cp._run_git(["add", "--", "tracked.txt"], store, str(work), index_file=index)
    assert not ok  # No such file is a normal Git failure, not a discovery bypass.
    assert config.read_bytes() == before
    (work / "tracked.txt").write_bytes(b"private shadow bytes\n")
    ok, _, error = cp._run_git(["add", "--", "tracked.txt"], store, str(work), index_file=index)
    assert ok, error
    assert index.is_file()
    assert not (store / "index").exists()
    assert config.read_bytes() == before


def test_shadow_objects_cannot_be_redirected_by_ambient_git_env(tmp_path, monkeypatch):
    work = tmp_path / "work"
    work.mkdir()
    (work / "tracked.txt").write_bytes(b"owned object routing fixture\n")
    store = tmp_path / "private" / "store"
    assert cp._init_store(store, str(work)) is None
    unrelated = tmp_path / "unrelated-objects"
    unrelated.mkdir()
    monkeypatch.setenv("GIT_OBJECT_DIRECTORY", str(unrelated))
    ok, _, error = cp._run_git(["add", "--", "tracked.txt"], store, str(work), index_file=store / "indexes" / "owned")
    assert ok, error
    assert not list(unrelated.rglob("*"))
    assert list((store / "objects").rglob("*"))


def test_failed_shadow_configuration_is_not_accepted_on_retry(tmp_path, monkeypatch):
    work = tmp_path / "work"
    work.mkdir()
    monkeypatch.setattr(cp, "_run_git", lambda *a, **kw: (False, "", "owned config failure"))
    store = tmp_path / "private" / "store"
    assert "owned config failure" in cp._init_store(store, str(work))
    assert "owned config failure" in cp._init_store(store, str(work))
