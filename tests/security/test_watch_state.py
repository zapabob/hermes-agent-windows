from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import psutil
import pytest

from downstream.security import watch_state


class _FakeWatcherProcess:
    def __init__(self, pid: int, *, create_time: float = 1234.5) -> None:
        self.pid = pid
        self._create_time = create_time

    def create_time(self) -> float:
        return self._create_time

    def cmdline(self) -> list[str]:
        return [
            sys.executable,
            "-m",
            "downstream.security.watcher",
            "--interval",
            "30",
            "--request-nonce",
            "f" * 32,
            "--owner-nonce",
            "a" * 32,
        ]

    def exe(self) -> str:
        return sys.executable

    def is_running(self) -> bool:
        return True

    def status(self) -> str:
        return psutil.STATUS_RUNNING


class _FakeUnrelatedProcess(_FakeWatcherProcess):
    def cmdline(self) -> list[str]:
        return [sys.executable, "-m", "http.server"]


def _owner_record(root: Path, *, nonce: str = "a" * 32, pid: int = 4242) -> dict[str, object]:
    return {
        "version": 1,
        "enabled": True,
        "request_nonce": "f" * 32,
        "pid": pid,
        "process_create_time": 1234.5,
        "owner_nonce": nonce,
        "profile_home": str(root.parent.resolve()),
        "python_executable": str(Path(sys.executable).resolve()),
    }


def test_malformed_watch_state_fails_closed(tmp_path: Path) -> None:
    root = tmp_path / "security"
    root.mkdir()
    (root / "watch-state.json").write_text(
        json.dumps({"enabled": True, "pid": "not-a-pid"}),
        encoding="utf-8",
    )

    status = watch_state.read_watch_status(root)

    assert status["enabled"] is False
    assert status["pid"] is None
    assert status["running"] is False
    assert status["error"] == "invalid state file"


def test_legacy_pid_without_process_identity_is_not_running(tmp_path: Path) -> None:
    root = tmp_path / "security"
    root.mkdir()
    (root / "watch-state.json").write_text(
        json.dumps({"enabled": True, "pid": os.getpid()}),
        encoding="utf-8",
    )

    status = watch_state.read_watch_status(root)

    assert status["enabled"] is True
    assert status["running"] is False
    assert status["error"] == "watcher identity is incomplete"


def test_enabled_request_reports_an_unverified_runtime_lock_owner(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    root = tmp_path / "security"
    watch_state.set_watch_enabled(root, True)
    monkeypatch.setattr(watch_state, "runtime_lock_is_held", lambda _root: True, raising=False)

    status = watch_state.read_watch_status(root)

    assert status == {
        "enabled": True,
        "pid": None,
        "running": False,
        "error": "watcher runtime lock is held by an unverified process",
    }


def test_profile_mismatch_cannot_authenticate_watcher(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    root = tmp_path / "security"
    root.mkdir()
    record = _owner_record(root)
    record["profile_home"] = str((tmp_path / "another-profile").resolve())
    (root / "watch-state.json").write_text(json.dumps(record), encoding="utf-8")
    monkeypatch.setattr(watch_state.psutil, "Process", _FakeWatcherProcess)

    status = watch_state.read_watch_status(root)

    assert status["running"] is False
    assert status["error"] == "watcher profile does not match state path"


def test_reused_pid_with_different_start_time_is_not_running(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    root = tmp_path / "security"
    root.mkdir()
    (root / "watch-state.json").write_text(json.dumps(_owner_record(root)), encoding="utf-8")
    monkeypatch.setattr(
        watch_state.psutil,
        "Process",
        lambda pid: _FakeWatcherProcess(pid, create_time=9999.0),
    )

    status = watch_state.read_watch_status(root)

    assert status["running"] is False
    assert status["error"] == "watcher process identity changed"


def test_non_finite_start_time_cannot_authenticate_watcher(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    root = tmp_path / "security"
    root.mkdir()
    record = _owner_record(root)
    record["process_create_time"] = float("nan")
    (root / "watch-state.json").write_text(json.dumps(record), encoding="utf-8")
    monkeypatch.setattr(watch_state.psutil, "Process", _FakeWatcherProcess)

    status = watch_state.read_watch_status(root)

    assert status["running"] is False
    assert status["error"] == "watcher identity is incomplete"


def test_unrelated_command_at_recorded_pid_is_not_running(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    root = tmp_path / "security"
    root.mkdir()
    (root / "watch-state.json").write_text(json.dumps(_owner_record(root)), encoding="utf-8")
    monkeypatch.setattr(watch_state.psutil, "Process", _FakeUnrelatedProcess)

    status = watch_state.read_watch_status(root)

    assert status["running"] is False
    assert status["error"] == "watcher command does not match"


def test_embedded_module_marker_does_not_authenticate_watcher(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    root = tmp_path / "security"
    root.mkdir()
    (root / "watch-state.json").write_text(json.dumps(_owner_record(root)), encoding="utf-8")

    class _EmbeddedMarkerProcess(_FakeWatcherProcess):
        def cmdline(self) -> list[str]:
            return [sys.executable, "-c", "pass", "-m", "downstream.security.watcher"]

    monkeypatch.setattr(watch_state.psutil, "Process", _EmbeddedMarkerProcess)

    status = watch_state.read_watch_status(root)

    assert status["running"] is False
    assert status["error"] == "watcher command does not match"


def test_valid_owner_identity_reports_running(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    root = tmp_path / "security"
    root.mkdir()
    (root / "watch-state.json").write_text(json.dumps(_owner_record(root)), encoding="utf-8")
    monkeypatch.setattr(watch_state.psutil, "Process", _FakeWatcherProcess)

    status = watch_state.read_watch_status(root)

    assert status["running"] is True
    assert status["pid"] == 4242
    assert "error" not in status


def test_stale_owner_cannot_clear_new_owner(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    root = tmp_path / "security"
    root.mkdir()
    request_a = "1" * 32
    request_b = "2" * 32
    records = iter((_owner_record(root, nonce="a" * 32), _owner_record(root, nonce="b" * 32)))
    monkeypatch.setattr(
        watch_state,
        "_current_process_record",
        lambda _root, request, _owner: {**next(records), "request_nonce": request},
    )

    monkeypatch.setattr(watch_state, "_new_nonce", lambda: request_a)
    watch_state.set_watch_enabled(root, True)
    watch_state.claim_watch_owner(root, request_a, "a" * 32)
    monkeypatch.setattr(watch_state, "_new_nonce", lambda: request_b)
    watch_state.set_watch_enabled(root, True)
    watch_state.claim_watch_owner(root, request_b, "b" * 32)

    assert watch_state.clear_watch_owner(root, request_a, "a" * 32) is False
    persisted = json.loads((root / "watch-state.json").read_text(encoding="utf-8"))
    assert persisted["owner_nonce"] == "b" * 32


def test_disabled_request_cannot_be_claimed_by_late_process(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    root = tmp_path / "security"
    record = _owner_record(root)
    monkeypatch.setattr(watch_state, "_current_process_record", lambda _root, _request, _owner: record)
    watch_state.set_watch_enabled(root, False)

    assert watch_state.claim_watch_owner(root, "f" * 32, "a" * 32) is None
    persisted = json.loads((root / "watch-state.json").read_text(encoding="utf-8"))
    assert persisted["enabled"] is False
    assert persisted["pid"] is None


def test_late_owner_from_prior_enable_generation_cannot_claim(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    root = tmp_path / "security"
    record = _owner_record(root)
    monkeypatch.setattr(
        watch_state,
        "_current_process_record",
        lambda _root, request, _owner: {**record, "request_nonce": request},
    )
    nonces = iter(("1" * 32, "2" * 32))
    monkeypatch.setattr(watch_state, "_new_nonce", lambda: next(nonces))
    first_request = watch_state.begin_watch_enable(root)
    second_request = watch_state.begin_watch_enable(root)

    assert watch_state.claim_watch_owner(root, first_request, "a" * 32) is None
    assert watch_state.claim_watch_owner(root, second_request, "b" * 32) is not None


def test_prepare_disable_discards_unverified_pid(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    root = tmp_path / "security"
    root.mkdir()
    (root / "watch-state.json").write_text(json.dumps(_owner_record(root)), encoding="utf-8")
    monkeypatch.setattr(
        watch_state.psutil,
        "Process",
        lambda pid: _FakeWatcherProcess(pid, create_time=9999.0),
    )

    state, process = watch_state.prepare_watch_disable(root)

    assert process is None
    assert state["enabled"] is False
    assert state["pid"] is None


def test_prepare_disable_returns_verified_owner(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    root = tmp_path / "security"
    root.mkdir()
    (root / "watch-state.json").write_text(json.dumps(_owner_record(root)), encoding="utf-8")
    monkeypatch.setattr(watch_state.psutil, "Process", _FakeWatcherProcess)

    state, process = watch_state.prepare_watch_disable(root)

    assert isinstance(process, _FakeWatcherProcess)
    assert state["enabled"] is False
    assert state["owner_nonce"] == "a" * 32
    status = watch_state.read_watch_status(root)
    assert status == {"enabled": False, "pid": 4242, "running": True}


def test_runtime_lock_allows_only_one_watcher(tmp_path: Path) -> None:
    root = tmp_path / "security"

    with watch_state.runtime_lock(root) as first:
        with watch_state.runtime_lock(root) as second:
            assert first is True
            assert second is False


def test_control_lock_does_not_recreate_deleted_named_profile(tmp_path: Path) -> None:
    profile_home = tmp_path / "profiles" / "research"
    root = profile_home / "security"

    with watch_state.control_lock(root):
        assert not profile_home.exists()

    assert not profile_home.exists()
    assert (tmp_path / "profiles" / ".security-watch-locks").is_dir()


def test_verified_legacy_watcher_is_fenced_for_transition(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    root = tmp_path / "security"
    root.mkdir()
    (root / "watch-state.json").write_text(
        json.dumps({"enabled": True, "pid": 4242}),
        encoding="utf-8",
    )

    class _LegacyWatcherProcess(_FakeWatcherProcess):
        def cmdline(self) -> list[str]:
            return [sys.executable, "-m", "downstream.security.watcher", "--interval", "30"]

    monkeypatch.setattr(watch_state.psutil, "Process", _LegacyWatcherProcess)

    process, error = watch_state.prepare_legacy_watch_transition(root)

    assert isinstance(process, _LegacyWatcherProcess)
    assert error is None
    persisted = json.loads((root / "watch-state.json").read_text(encoding="utf-8"))
    assert persisted["version"] == 1
    assert persisted["enabled"] is False


def test_unverified_legacy_watcher_blocks_transition(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    root = tmp_path / "security"
    root.mkdir()
    legacy = {"enabled": True, "pid": 4242}
    (root / "watch-state.json").write_text(json.dumps(legacy), encoding="utf-8")
    monkeypatch.setattr(watch_state.psutil, "Process", _FakeUnrelatedProcess)

    process, error = watch_state.prepare_legacy_watch_transition(root)

    assert process is None
    assert error == "legacy watcher identity could not be verified"
    assert json.loads((root / "watch-state.json").read_text(encoding="utf-8")) == legacy
