"""Regression tests for #4707 — cron must be per-profile.

Design intent (Teknium, June 2026): a profile's cron jobs both LIVE in that
profile's HERMES_HOME and EXECUTE under it.

- Storage: a job created under profile ``coder`` writes to
  ``~/.hermes/profiles/coder/cron/jobs.json`` — NOT the shared default root.
- Execution: the profile-scoped gateway's in-process ticker resolves the
  active HERMES_HOME (profile home) at call time, so jobs run with that
  profile's ``.env`` / ``config.yaml`` / scripts / skills.

This is the opposite direction from the (reverted) #50112/#32091 "anchor at the
shared root" approach. Anchoring at the root funnels every profile's jobs into
one store and runs them under whatever HERMES_HOME the ticker happens to have —
leaking config/credentials/skills across profiles, the security boundary #4707
was filed for. These tests pin per-profile isolation so a stale-branch merge or
a re-anchor "fix" can't silently flip it back.
"""
import importlib
import concurrent.futures
import os
import subprocess
import sys
import threading
from pathlib import Path


def _set_profile_env(monkeypatch, root: Path, profile_home: Path) -> None:
    """Pretend the platform default root is ``root`` and the active
    HERMES_HOME is a profile under it (``<root>/profiles/<name>``)."""
    import hermes_constants

    monkeypatch.setattr(
        hermes_constants, "_get_platform_default_hermes_home", lambda: root
    )
    monkeypatch.setenv("HERMES_HOME", str(profile_home))


def test_cron_storage_anchors_at_profile_home(tmp_path, monkeypatch):
    """Under a profile HERMES_HOME (<root>/profiles/<name>), the cron store
    resolves to <profile>/cron, NOT the shared <root>/cron."""
    root = tmp_path / "hermes_home"
    profile_home = root / "profiles" / "coder"
    profile_home.mkdir(parents=True)

    _set_profile_env(monkeypatch, root, profile_home)

    import hermes_constants

    # Sanity: the override is wired the way the gateway sees it.
    assert hermes_constants.get_hermes_home().resolve() == profile_home.resolve()
    assert hermes_constants.get_default_hermes_root().resolve() == root.resolve()

    # cron/jobs.py computes HERMES_DIR from get_hermes_home() at import, so a
    # fresh import under this env anchors the store at <profile>/cron.
    import cron.jobs as jobs

    importlib.reload(jobs)
    try:
        assert jobs.HERMES_DIR.resolve() == profile_home.resolve()
        assert (
            jobs.JOBS_FILE.resolve()
            == (profile_home / "cron" / "jobs.json").resolve()
        )
        # The shared-root path must NOT be the store — that would re-break
        # per-profile isolation (#4707).
        assert (
            jobs.JOBS_FILE.resolve() != (root / "cron" / "jobs.json").resolve()
        )
    finally:
        monkeypatch.undo()
        importlib.reload(jobs)


def test_job_needs_sequential_tick_for_workdir_or_named_profile():
    """Tick must serialize jobs that mutate process-global Hermes state.

    A live gateway loop died every minute with
    ``NameError: name '_job_needs_sequential_tick' is not defined`` after a
    merge dropped the helper while leaving the call site in ``tick()``.
    """
    from cron.scheduler import _job_needs_sequential_tick

    assert _job_needs_sequential_tick({}) is False
    assert _job_needs_sequential_tick({"workdir": "C:/tmp/project"}) is True
    assert _job_needs_sequential_tick({"profile": "alpha"}) is True
    assert _job_needs_sequential_tick({"profile": "default"}) is True
    assert _job_needs_sequential_tick({"profile": "  "}) is False


def test_named_cron_cannot_retarget_concurrent_desktop_model_inventory(tmp_path, monkeypatch):
    """Hold a real cron scope while the Desktop's other thread reads config."""
    from cron import scheduler
    from hermes_cli.inventory import load_picker_context
    from hermes_constants import get_hermes_home
    from tools.environments.local import build_subprocess_env

    root = tmp_path / "root"
    profile = root / "profiles" / "cloud"
    profile.mkdir(parents=True)
    (root / "config.yaml").write_text(
        "model:\n  provider: fixture-local\n  default: local-fixture-model\n", encoding="utf-8",
    )
    (profile / "config.yaml").write_text(
        "model:\n  provider: nvidia\n  default: cloud-fixture-model\n", encoding="utf-8",
    )
    _set_profile_env(monkeypatch, root, root)
    monkeypatch.setattr(scheduler, "_hermes_home", root)
    entered, release = threading.Event(), threading.Event()

    def cron_worker():
        with scheduler._cron_profile_context({"id": "owned", "profile": "cloud"}):
            entered.set()
            assert release.wait(10)
            context = load_picker_context()
            child_home = subprocess.check_output(
                [sys.executable, "-B", "-c", "import os; print(os.environ['HERMES_HOME'])"],
                env=build_subprocess_env(), text=True, encoding="utf-8", timeout=10,
            ).strip()
            return context, scheduler._get_hermes_home(), child_home

    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(cron_worker)
        try:
            assert entered.wait(10)
            desktop = load_picker_context()
            assert os.environ["HERMES_HOME"] == str(root)
            assert get_hermes_home() == root and scheduler._get_hermes_home() == root
            assert (desktop.current_provider, desktop.current_model) == ("fixture-local", "local-fixture-model")
        finally:
            release.set()
        context, scheduler_home, child_home = future.result(timeout=15)
    assert (context.current_provider, context.current_model) == ("nvidia", "cloud-fixture-model")
    assert scheduler_home == profile and Path(child_home) == profile
    assert os.environ["HERMES_HOME"] == str(root)


