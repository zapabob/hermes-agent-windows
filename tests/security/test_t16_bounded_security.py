from __future__ import annotations

import hashlib
import json
import os
import stat
import subprocess
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from downstream.security import engines as security_engines
from downstream.security import bounded_process as security_bounded_process
from downstream.security import clamav_definitions as security_clamav_definitions
from downstream.security import service as security_service_module
from downstream.security import updates as security_updates
from downstream.security import watch_state, watcher as security_watcher
from downstream.security.bounded_walk import ReparsePathError, stable_file_time_ns
from downstream.security.bounded_process import (
    BoundedProcessOutputError,
    BoundedProcessResult,
    run_bounded,
)
from downstream.security.engines import ClamAVEngine, versions_cache_key
from downstream.security.models import EngineState, Finding, ScanResult, Verdict
from downstream.security.service import SecurityService
from downstream.security.store import SecurityStore
from downstream.security.watcher import reconcile_once


class CleanEngine:
    name = "clamav"

    def version(self) -> str:
        return "test-clean-1"

    def scan(self, _path: Path, _sha256: str) -> list[Finding]:
        return [Finding(self.name, "no_detection", 0)]


class WatchStoreStub:
    def __init__(self, root: Path) -> None:
        self.root = root
        self.event = Mock()


class ReconcileServiceStub:
    def __init__(self, root: Path) -> None:
        self.root = root
        self.store = WatchStoreStub(root)
        self.scan_file = Mock()

    def quick_paths(self) -> list[Path]:
        return [self.root]


def _service(root: Path) -> SecurityService:
    service = SecurityService(
        SecurityStore(root / "security"),
        {"security": {"malware": {"auto_quarantine": False, "max_workers": 4}}},
    )
    service.engines = (CleanEngine(),)
    return service


def _managed_clamav_database(root: Path) -> Path:
    database = root / "managed-clamav-database"
    database.mkdir()
    (database / "main.cvd").write_bytes(b"inert definition metadata")
    return database


def _freeze_clamav_definition_metadata(
    monkeypatch: pytest.MonkeyPatch,
    database: Path,
    definition: Path,
) -> None:
    original_scandir = os.scandir
    original_open = Path.open
    original_path_stat = Path.stat
    original_fstat = os.fstat
    source_metadata = definition.stat(follow_symlinks=False)
    frozen_metadata = SimpleNamespace(
        st_mode=source_metadata.st_mode,
        st_size=source_metadata.st_size,
        st_mtime_ns=source_metadata.st_mtime_ns,
        st_ctime_ns=source_metadata.st_ctime_ns,
        st_dev=source_metadata.st_dev,
        st_ino=source_metadata.st_ino,
        st_file_attributes=getattr(source_metadata, "st_file_attributes", 0),
    )
    open_database_fds: set[int] = set()

    class FrozenEntry:
        name = definition.name
        path = str(definition)

        def stat(self, *, follow_symlinks: bool = True):
            return frozen_metadata

    class FrozenEntries:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return None

        def __iter__(self):
            return iter((FrozenEntry(),))

    class TrackedFile:
        def __init__(self, handle):
            self.handle = handle
            self.fd = handle.fileno()

        def __enter__(self):
            return self

        def __exit__(self, *args):
            open_database_fds.discard(self.fd)
            return self.handle.__exit__(*args)

        def fileno(self):
            return self.fd

        def __getattr__(self, name: str):
            return getattr(self.handle, name)

    def stable_scandir(path):
        if Path(path) == database:
            return FrozenEntries()
        return original_scandir(path)

    def stable_path_stat(path: Path, *args, **kwargs):
        if path == definition:
            return frozen_metadata
        return original_path_stat(path, *args, **kwargs)

    def track_database_open(path: Path, *args, **kwargs):
        handle = original_open(path, *args, **kwargs)
        if path == definition:
            open_database_fds.add(handle.fileno())
            return TrackedFile(handle)
        return handle

    def frozen_fstat(fd: int):
        if fd in open_database_fds:
            return frozen_metadata
        return original_fstat(fd)

    monkeypatch.setattr(os, "scandir", stable_scandir)
    monkeypatch.setattr(Path, "open", track_database_open)
    monkeypatch.setattr(Path, "stat", stable_path_stat)
    monkeypatch.setattr(os, "fstat", frozen_fstat)


def test_status_does_not_spawn_scanners_compile_rules_or_copy_bundled_rules(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    binary = tmp_path / "clamdscan.exe"
    binary.write_bytes(b"inert scanner identity fixture")
    monkeypatch.setattr(
        security_engines.shutil,
        "which",
        lambda name: str(binary) if name == "clamdscan" else None,
    )
    monkeypatch.setattr(security_engines.importlib.util, "find_spec", lambda _name: SimpleNamespace())
    import_module = Mock(side_effect=AssertionError("status compiled YARA rules"))
    monkeypatch.setattr(security_engines.importlib, "import_module", import_module)
    subprocess_run = Mock(side_effect=AssertionError("status spawned a scanner"))
    subprocess_popen = Mock(side_effect=AssertionError("status spawned a scanner"))
    monkeypatch.setattr(security_engines.subprocess, "run", subprocess_run)
    monkeypatch.setattr(security_engines.subprocess, "Popen", subprocess_popen)

    root = tmp_path / "security"
    service = SecurityService(
        SecurityStore(root),
        {"security": {"malware": {"auto_quarantine": False}}},
    )

    status = service.status()

    assert status["engines"]["clamav"] == EngineState.SCANNER_UNAVAILABLE.value
    assert len(str(status["engines"]["clamav"])) <= 80
    import_module.assert_not_called()
    subprocess_run.assert_not_called()
    subprocess_popen.assert_not_called()
    assert not (root / "feeds" / "yara").exists()
    assert service.status()["engines"] == status["engines"]
    import_module.assert_not_called()
    subprocess_run.assert_not_called()
    subprocess_popen.assert_not_called()


def test_scan_paths_keeps_only_a_bounded_number_of_futures_in_flight(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    files = [tmp_path / f"fixture-{index}.txt" for index in range(24)]
    for path in files:
        path.write_text("inert fixture", encoding="utf-8")
    service = _service(tmp_path)
    started = threading.Event()
    release = threading.Event()
    lock = threading.Lock()
    current = 0
    largest = 0
    original_submit = ThreadPoolExecutor.submit

    def tracked_submit(executor, *args, **kwargs):
        nonlocal current, largest
        with lock:
            current += 1
            largest = max(largest, current)
        future = original_submit(executor, *args, **kwargs)

        def completed(_future) -> None:
            nonlocal current
            with lock:
                current -= 1

        future.add_done_callback(completed)
        return future

    def wait_for_release(candidate: Path, _quarantine: bool = True) -> ScanResult:
        started.set()
        assert release.wait(5)
        return ScanResult(str(candidate), "", 0, Verdict.CLEAN, 0, "allow", (), {})

    monkeypatch.setattr(security_service_module.ThreadPoolExecutor, "submit", tracked_submit)
    monkeypatch.setattr(service, "scan_file", wait_for_release)
    errors: list[BaseException] = []

    def run_scan() -> None:
        try:
            service.scan_paths(files, workers=4, quarantine=False)
        except BaseException as exc:  # surface worker-thread failures in the test
            errors.append(exc)

    worker = threading.Thread(target=run_scan)
    worker.start()
    try:
        assert started.wait(5)
        assert largest <= 8
    finally:
        release.set()
        worker.join(10)

    assert not worker.is_alive()
    assert not errors
    assert largest == 8


def test_scan_paths_marks_file_inventory_truncation_for_review(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    root = tmp_path / "large-root"
    root.mkdir()
    for index in range(3):
        (root / f"fixture-{index}.txt").write_text("inert fixture", encoding="utf-8")
    monkeypatch.setattr(security_service_module, "MAX_SCAN_FILES", 2, raising=False)

    results = _service(tmp_path).scan_paths([root], quarantine=False)

    scanned = [result for result in results if result.error is None]
    incomplete = [result for result in results if result.error == "directory_scan_incomplete"]
    assert len(scanned) == 2
    assert len(incomplete) == 1
    assert incomplete[0].verdict == Verdict.SCAN_ERROR
    assert incomplete[0].action == "blocked_pending_review"


def test_watcher_reports_inventory_truncation_and_keeps_state_bounded(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    root = tmp_path / "watch-root"
    root.mkdir()
    for index in range(3):
        (root / f"fixture-{index}.txt").write_text("inert fixture", encoding="utf-8")
    monkeypatch.setattr(security_watcher, "MAX_WATCH_FILES", 2, raising=False)
    service = ReconcileServiceStub(root)
    inventory_event_state: dict[str, float | str] = {}

    current = reconcile_once(service, {}, scan_changes=False, inventory_event_state=inventory_event_state)
    reconcile_once(service, current, scan_changes=False, inventory_event_state=inventory_event_state)

    assert len(current) == 2
    service.store.event.assert_called_once()
    event = service.store.event.call_args.args
    assert event[0] == "watch_inventory_incomplete"
    assert event[3] == "review"
    assert event[4]["reason"] == "file_limit"


def test_directory_walk_reports_skipped_reparse_points_as_incomplete(
    tmp_path: Path,
) -> None:
    root = tmp_path / "reparse-root"
    root.mkdir()
    (root / "fixture.txt").write_text("inert fixture", encoding="utf-8")
    report = security_service_module.DirectoryWalkReport()

    discovered = list(
        security_service_module.iter_regular_files(
            root,
            report,
            max_files=10,
            is_reparse=lambda _path: True,
        )
    )

    assert discovered == []
    assert report.complete is False
    assert report.truncated_reason == "reparse_point_skipped"


def test_definition_validation_rejects_inventory_over_limit_before_sigtool(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    store = SecurityStore(tmp_path / "security")
    updater = security_updates.DefinitionUpdater(store)
    candidate = tmp_path / "candidate"
    candidate.mkdir()
    for index in range(3):
        (candidate / f"database-{index}.cvd").write_bytes(b"x" * 512)
    monkeypatch.setattr(security_updates, "MAX_DEFINITION_FILES", 2, raising=False)
    monkeypatch.setattr(security_updates.shutil, "which", lambda _name: "sigtool")
    subprocess_popen = Mock(side_effect=AssertionError("over-limit validation invoked sigtool"))
    monkeypatch.setattr(security_updates.subprocess, "Popen", subprocess_popen)

    valid, detail = updater._validate(candidate)

    assert valid is False
    assert detail == "too many definition files"
    subprocess_popen.assert_not_called()


def test_clamav_inventory_entry_limit_rejects_before_reading_definitions(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    database = tmp_path / "bounded-database"
    database.mkdir()
    (database / "main.cvd").write_bytes(b"first inert definition")
    (database / "daily.ndb").write_bytes(b"second inert definition")
    open_definition = Mock(side_effect=AssertionError("inventory read definitions before enforcing entry cap"))
    monkeypatch.setattr(Path, "open", open_definition)

    with pytest.raises(security_clamav_definitions.DefinitionInventoryError) as error:
        security_clamav_definitions.inventory_clamav_definitions(database, max_entries=1)

    assert error.value.reason == "definition_entry_limit"
    open_definition.assert_not_called()


@pytest.mark.parametrize(
    ("version", "error"),
    [
        ("unknown", "definition_version_unavailable"),
        ("inventory-limit", "definition_inventory_limit"),
        ("file-limit", "definition_file_limit"),
        ("invalid-file", "definition_file_invalid"),
    ],
)
def test_definition_activation_with_incomplete_post_inventory_is_not_current(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    version: str,
    error: str,
) -> None:
    store = SecurityStore(tmp_path / "security")
    updater = security_updates.DefinitionUpdater(store)
    old_current = updater.root / "current"
    old_current.mkdir(parents=True)
    (old_current / "old.cvd").write_bytes(b"o" * 512)
    monkeypatch.setattr(
        security_updates.shutil,
        "which",
        lambda name: "freshclam.exe" if name == "freshclam" else None,
    )

    def create_valid_staging(arguments, **_kwargs):
        staging = Path(arguments[1].split("=", 1)[1])
        (staging / "main.cvd").write_bytes(b"n" * 512)
        return BoundedProcessResult(0, "", "", False)

    monkeypatch.setattr(security_updates, "run_bounded", create_valid_staging)
    monkeypatch.setattr(updater, "_definition_version", lambda _current: version)

    result = updater.update_clamav()

    assert result["ok"] is False
    assert result["state"] == "activation_unverified"
    assert result["activated"] is True
    assert result["version"] == "unknown"
    assert result["error"] == error
    feed = store.status_rows("feed_state")[0]
    assert feed["version"] == "activation_unverified"
    assert feed["status"] == "error"
    assert json.loads(feed["details_json"]) == {
        "activated": True,
        "error": error,
        "validation": "1 databases validated",
        "verification": "incomplete",
    }
    assert (updater.root / "current" / "main.cvd").read_bytes() == b"n" * 512
    assert (updater.root / "previous" / "old.cvd").read_bytes() == b"o" * 512


def test_bundled_yara_sync_rejects_oversized_definitions_without_partial_copy(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    store = SecurityStore(tmp_path / "security")
    monkeypatch.setattr(security_updates, "MAX_BUNDLED_YARA_FILE_BYTES", 1, raising=False)

    result = security_updates.sync_bundled_yara_rules(store)

    assert result == {
        "ok": False,
        "error": "bundled rule size limit exceeded",
        "synced_files": 0,
    }
    assert store.feed_versions().get("yara") is None
    assert list((store.root / "feeds" / "yara").glob("*.yar")) == []


def test_yara_status_marks_incomplete_rule_inventory_as_engine_error(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    rules = tmp_path / "rules"
    rules.mkdir()
    (rules / "one.yar").write_text("rule One { condition: true }", encoding="utf-8")
    (rules / "two.yar").write_text("rule Two { condition: true }", encoding="utf-8")
    monkeypatch.setattr(security_engines, "MAX_YARA_RULE_FILES", 1, raising=False)
    monkeypatch.setattr(security_engines.importlib.util, "find_spec", lambda _name: None)

    engine = security_engines.YaraEngine(rules)

    assert engine.version() == "engine_error"


def test_yara_compile_failure_remains_a_typed_engine_error(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    rules = tmp_path / "rules"
    rules.mkdir()
    (rules / "broken.yar").write_text("rule Broken { condition: true }", encoding="utf-8")
    target = tmp_path / "inert-target.bin"
    target.write_bytes(b"inert target")
    monkeypatch.setattr(security_engines.importlib.util, "find_spec", lambda _name: SimpleNamespace())
    compile_rule = Mock(side_effect=ValueError("synthetic compile rejection"))
    monkeypatch.setattr(
        security_engines.importlib,
        "import_module",
        lambda _name: SimpleNamespace(compile=compile_rule),
    )

    findings = security_engines.YaraEngine(rules).scan(target, "inert-sha256")

    assert findings[0].state == EngineState.ENGINE_ERROR
    assert findings[0].name == "YARA unavailable"
    compile_rule.assert_called_once()


def test_clamav_status_marks_incomplete_database_inventory_as_engine_error(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    binary = tmp_path / "clamscan.exe"
    binary.write_bytes(b"inert scanner identity fixture")
    database = tmp_path / "database"
    database.mkdir()
    (database / "main.cvd").write_bytes(b"inert definition metadata")
    (database / "daily.cvd").write_bytes(b"inert definition metadata")
    monkeypatch.setattr(
        security_engines.shutil,
        "which",
        lambda name: str(binary) if name == "clamscan" else None,
    )
    monkeypatch.setattr(security_engines, "MAX_CLAMAV_DATABASE_ENTRIES", 1, raising=False)

    engine = ClamAVEngine(database_dir=database)

    assert engine.version() == "engine_error"


@pytest.mark.parametrize("inventory_failure", ("entry_limit", "stat_error"))
def test_clamav_inventory_failure_cannot_reuse_or_write_clean_cache(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    inventory_failure: str,
) -> None:
    binary = tmp_path / "clamscan.exe"
    binary.write_bytes(b"inert scanner identity fixture")
    database = tmp_path / "database"
    database.mkdir()
    (database / "main.cvd").write_bytes(b"inert definition metadata")
    if inventory_failure == "entry_limit":
        (database / "daily.cvd").write_bytes(b"inert definition metadata")
        monkeypatch.setattr(security_engines, "MAX_CLAMAV_DATABASE_ENTRIES", 1, raising=False)
    else:
        class FailedEntry:
            name = "main.cvd"

            def stat(self, *, follow_symlinks: bool = True):
                raise PermissionError("synthetic definition stat failure")

        class FailedScandir:
            def __enter__(self):
                return self

            def __exit__(self, *_args):
                return False

            def __iter__(self):
                return iter((FailedEntry(),))

        original_scandir = security_engines.os.scandir

        def scandir_database_only(path):
            if Path(path) == database:
                return FailedScandir()
            return original_scandir(path)

        monkeypatch.setattr(security_engines.os, "scandir", scandir_database_only)
    monkeypatch.setattr(
        security_engines.shutil,
        "which",
        lambda name: str(binary) if name == "clamscan" else None,
    )
    service = _service(tmp_path)
    service.engines = (ClamAVEngine(database_dir=database),)
    target = tmp_path / "inert-target.bin"
    target.write_bytes(b"inert target")
    sha256, size, _identity = service._hash_stable(target)
    failed_versions = {"clamav": EngineState.ENGINE_ERROR.value}
    service.store.record_scan(
        ScanResult(
            str(target),
            sha256,
            size,
            Verdict.CLEAN,
            0,
            "allow",
            (Finding("clamav", "no_detection", 0),),
            failed_versions,
        ),
        versions_cache_key(failed_versions),
    )
    run = Mock(
        return_value=BoundedProcessResult(
            returncode=0,
            stdout="",
            stderr="",
            output_truncated=False,
        )
    )
    monkeypatch.setattr(security_engines, "run_bounded", run)

    result = service.scan_file(target)

    assert result.verdict == Verdict.SCAN_ERROR
    assert result.cached is False
    assert any(finding.state == EngineState.ENGINE_ERROR for finding in result.findings)
    run.assert_not_called()
    cached = service.store.cache_get(sha256, versions_cache_key(service.versions()))
    assert cached is not None
    assert cached.verdict == Verdict.CLEAN


def test_engine_error_version_cannot_replay_or_record_a_clean_scan(
    tmp_path: Path,
) -> None:
    class ErrorVersionCleanEngine:
        name = "clamav"

        def version(self) -> str:
            return EngineState.ENGINE_ERROR.value

        def scan(self, _path: Path, _sha256: str) -> list[Finding]:
            return [Finding(self.name, "no_detection", 0)]

    service = _service(tmp_path)
    service.engines = (ErrorVersionCleanEngine(),)
    target = tmp_path / "inert-target.bin"
    target.write_bytes(b"inert target")
    sha256, size, _identity = service._hash_stable(target)
    failed_versions = {"clamav": EngineState.ENGINE_ERROR.value}
    service.store.record_scan(
        ScanResult(
            str(target),
            sha256,
            size,
            Verdict.CLEAN,
            0,
            "allow",
            (Finding("clamav", "no_detection", 0),),
            failed_versions,
        ),
        versions_cache_key(failed_versions),
    )

    result = service.scan_file(target)

    assert result.verdict == Verdict.SCAN_ERROR
    assert result.action == "blocked_pending_review"
    assert result.cached is False
    assert any(finding.state == EngineState.ENGINE_ERROR for finding in result.findings)
    cached = service.store.cache_get(sha256, versions_cache_key(failed_versions))
    assert cached is not None
    assert cached.verdict == Verdict.CLEAN


def test_clamav_missing_managed_database_never_scans_with_default_database(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    binary = tmp_path / "clamscan.exe"
    binary.write_bytes(b"inert scanner identity fixture")
    managed_database = tmp_path / "selected-profile" / "feeds" / "clamav" / "current"
    monkeypatch.setattr(
        security_engines.shutil,
        "which",
        lambda name: str(binary) if name == "clamscan" else None,
    )
    run = Mock(
        return_value=BoundedProcessResult(
            returncode=0,
            stdout="",
            stderr="",
            output_truncated=False,
        )
    )
    monkeypatch.setattr(security_engines, "run_bounded", run)
    service = _service(tmp_path)
    service.engines = (ClamAVEngine(database_dir=managed_database),)
    target = tmp_path / "inert-target.bin"
    target.write_bytes(b"inert target")

    result = service.scan_file(target, use_cache=False)

    assert result.verdict == Verdict.SCAN_ERROR
    assert result.action == "blocked_pending_review"
    assert any(finding.state == EngineState.ENGINE_ERROR for finding in result.findings)
    run.assert_not_called()


def test_clamav_rejects_definitions_changed_during_scan(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    binary = tmp_path / "clamscan.exe"
    binary.write_bytes(b"inert scanner identity fixture")
    database = _managed_clamav_database(tmp_path)
    target = tmp_path / "inert-target.bin"
    target.write_bytes(b"inert target")
    monkeypatch.setattr(
        security_engines.shutil,
        "which",
        lambda name: str(binary) if name == "clamscan" else None,
    )

    def scan_and_replace_definition(*_args, **_kwargs):
        (database / "main.cvd").write_bytes(b"updated inert metadata")
        return BoundedProcessResult(
            returncode=0,
            stdout="",
            stderr="",
            output_truncated=False,
        )

    run = Mock(side_effect=scan_and_replace_definition)
    monkeypatch.setattr(security_engines, "run_bounded", run)

    findings = ClamAVEngine(database_dir=database).scan(target, "inert-sha256")

    assert len(findings) == 1
    assert findings[0].state == EngineState.ENGINE_ERROR
    assert findings[0].name == "ClamAV definitions changed during scan"
    run.assert_called_once()


def test_clamav_cache_identity_distinguishes_managed_database_paths(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    binary = tmp_path / "clamscan.exe"
    binary.write_bytes(b"inert scanner identity fixture")
    first_database = tmp_path / "profile-one" / "current"
    second_database = tmp_path / "profile-two" / "current"
    first_database.mkdir(parents=True)
    second_database.mkdir(parents=True)
    first_file = first_database / "main.cvd"
    second_file = second_database / "main.cvd"
    first_file.write_bytes(b"same inert database bytes")
    second_file.write_bytes(b"same inert database bytes")
    timestamp = first_file.stat().st_mtime_ns
    os.utime(second_file, ns=(timestamp, timestamp))
    monkeypatch.setattr(
        security_engines.shutil,
        "which",
        lambda name: str(binary) if name == "clamscan" else None,
    )

    first_version = ClamAVEngine(database_dir=first_database).version()
    second_version = ClamAVEngine(database_dir=second_database).version()

    assert first_version.startswith("binary-id-")
    assert second_version.startswith("binary-id-")
    assert first_version != second_version


def test_clamav_content_identity_invalidates_clean_cache_when_metadata_is_unchanged(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    binary = tmp_path / "clamscan.exe"
    binary.write_bytes(b"inert scanner identity fixture")
    database = tmp_path / "managed-clamav-database"
    database.mkdir()
    definition = database / "main.cvd"
    definition.write_bytes(b"definition-A")
    target = tmp_path / "inert-target.bin"
    target.write_bytes(b"inert target")
    monkeypatch.setattr(
        security_engines.shutil,
        "which",
        lambda name: str(binary) if name == "clamscan" else None,
    )

    # Model a Windows same-size rewrite whose visible metadata is unchanged.
    # The bytes must still participate in the engine/cache identity.
    _freeze_clamav_definition_metadata(monkeypatch, database, definition)
    run = Mock(
        return_value=BoundedProcessResult(
            returncode=0,
            stdout="",
            stderr="",
            output_truncated=False,
        )
    )
    monkeypatch.setattr(security_engines, "run_bounded", run)
    service = _service(tmp_path)
    engine = ClamAVEngine(database_dir=database)
    service.engines = (engine,)

    first = service.scan_file(target, quarantine=False)
    first_identity = engine.version()
    definition.write_bytes(b"definition-B")
    second_identity = engine.version()
    second = service.scan_file(target, quarantine=False)

    assert first.verdict == Verdict.CLEAN
    assert first.cached is False
    assert second_identity != first_identity
    assert second.verdict == Verdict.CLEAN
    assert second.cached is False
    assert run.call_count == 2


@pytest.mark.parametrize(
    ("definition_sizes", "file_limit", "total_limit", "expected_reason"),
    [
        ((9,), 8, 16, "database-file-limit"),
        ((6, 6), 8, 10, "database-total-limit"),
    ],
)
def test_clamav_database_byte_caps_fail_closed_before_scanning(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    definition_sizes: tuple[int, ...],
    file_limit: int,
    total_limit: int,
    expected_reason: str,
) -> None:
    binary = tmp_path / "clamscan.exe"
    binary.write_bytes(b"inert scanner identity fixture")
    database = tmp_path / "managed-clamav-database"
    database.mkdir()
    for index, size in enumerate(definition_sizes):
        (database / f"definition-{index}.cvd").write_bytes(b"x" * size)
    target = tmp_path / "inert-target.bin"
    target.write_bytes(b"inert target")
    monkeypatch.setattr(
        security_engines.shutil,
        "which",
        lambda name: str(binary) if name == "clamscan" else None,
    )
    monkeypatch.setattr(security_engines, "MAX_CLAMAV_DATABASE_FILE_BYTES", file_limit)
    monkeypatch.setattr(security_engines, "MAX_CLAMAV_DATABASE_TOTAL_BYTES", total_limit)
    run = Mock()
    monkeypatch.setattr(security_engines, "run_bounded", run)
    engine = ClamAVEngine(database_dir=database)

    assert engine.version() == EngineState.ENGINE_ERROR.value
    findings = engine.scan(target, "inert-sha256")

    assert len(findings) == 1
    assert findings[0].state == EngineState.ENGINE_ERROR
    assert findings[0].details["reason"] == expected_reason
    run.assert_not_called()


def test_clamav_database_reparse_file_is_rejected_before_scanning(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    binary = tmp_path / "clamscan.exe"
    binary.write_bytes(b"inert scanner identity fixture")
    database = _managed_clamav_database(tmp_path)
    target = tmp_path / "inert-target.bin"
    target.write_bytes(b"inert target")
    monkeypatch.setattr(
        security_engines.shutil,
        "which",
        lambda name: str(binary) if name == "clamscan" else None,
    )
    reparse_flag = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)
    monkeypatch.setattr(security_engines.stat, "FILE_ATTRIBUTE_REPARSE_POINT", reparse_flag, raising=False)
    definition = database / "main.cvd"
    original_path_stat = Path.stat
    metadata = definition.stat(follow_symlinks=False)
    reparse_metadata = SimpleNamespace(
        st_mode=metadata.st_mode,
        st_size=metadata.st_size,
        st_mtime_ns=metadata.st_mtime_ns,
        st_ctime_ns=metadata.st_ctime_ns,
        st_dev=metadata.st_dev,
        st_ino=metadata.st_ino,
        st_file_attributes=reparse_flag,
    )

    def report_reparse(path: Path, *args, **kwargs):
        if path == definition:
            return reparse_metadata
        return original_path_stat(path, *args, **kwargs)

    monkeypatch.setattr(Path, "stat", report_reparse)
    run = Mock()
    monkeypatch.setattr(security_engines, "run_bounded", run)
    engine = ClamAVEngine(database_dir=database)

    assert engine.version() == EngineState.ENGINE_ERROR.value
    findings = engine.scan(target, "inert-sha256")

    assert len(findings) == 1
    assert findings[0].state == EngineState.ENGINE_ERROR
    assert findings[0].details["reason"] == "database-reparse-point"
    run.assert_not_called()


def test_clamav_detection_name_retention_is_bounded(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    binary = tmp_path / "clamscan.exe"
    binary.write_bytes(b"inert scanner identity fixture")
    database = _managed_clamav_database(tmp_path)
    target = tmp_path / "inert-target.bin"
    target.write_bytes(b"inert target")
    monkeypatch.setattr(
        security_engines.shutil,
        "which",
        lambda name: str(binary) if name == "clamscan" else None,
    )
    monkeypatch.setattr(
        security_engines,
        "run_bounded",
        lambda *_args, **_kwargs: BoundedProcessResult(
            returncode=1,
            stdout=f"{target}: {'X' * 10000} FOUND\n",
            stderr="",
            output_truncated=False,
        ),
    )

    findings = ClamAVEngine(database_dir=database).scan(target, "inert-sha256")

    assert findings[0].score == 90
    assert len(findings[0].name) <= 160


def test_clamav_does_not_treat_truncated_exit_zero_as_clean(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    binary = tmp_path / "clamscan.exe"
    binary.write_bytes(b"inert scanner identity fixture")
    database = _managed_clamav_database(tmp_path)
    target = tmp_path / "inert-target.bin"
    target.write_bytes(b"inert target")
    monkeypatch.setattr(
        security_engines.shutil,
        "which",
        lambda name: str(binary) if name == "clamscan" else None,
    )
    monkeypatch.setattr(
        security_engines,
        "run_bounded",
        lambda *_args, **_kwargs: BoundedProcessResult(
            returncode=0,
            stdout="partial diagnostics",
            stderr="",
            output_truncated=True,
        ),
    )

    findings = ClamAVEngine(database_dir=database).scan(target, "inert-sha256")

    assert len(findings) == 1
    assert findings[0].state == EngineState.ENGINE_ERROR
    assert findings[0].name == "ClamAV output incomplete"


def test_yara_match_overflow_is_marked_as_an_incomplete_scan(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    rules = tmp_path / "rules"
    rules.mkdir()
    (rules / "many.yar").write_text("rule Many { condition: true }", encoding="utf-8")
    monkeypatch.setattr(security_engines.importlib.util, "find_spec", lambda _name: SimpleNamespace())
    engine = security_engines.YaraEngine(rules)
    engine.version()
    engine._compiled = SimpleNamespace(
        match=lambda *_args, **_kwargs: [
            SimpleNamespace(rule=f"rule-{index}", meta={}, tags=[])
            for index in range(security_engines.MAX_YARA_MATCHES + 1)
        ]
    )
    engine._compiled_revision = engine._inventory_revision
    target = tmp_path / "inert-target.bin"
    target.write_bytes(b"inert target")

    findings = engine.scan(target, "inert-sha256")

    assert len(findings) == security_engines.MAX_YARA_MATCHES + 1
    assert findings[-1].state == EngineState.ENGINE_ERROR
    assert findings[-1].name == "YARA result limit exceeded"
    assert findings[-1].details["result_limit"] == security_engines.MAX_YARA_MATCHES


def test_watcher_state_read_rejects_oversized_status_file(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    root = tmp_path / "security"
    root.mkdir()
    state = {"version": 1, "enabled": False, "padding": "x" * 256}
    (root / "watch-state.json").write_text(json.dumps(state), encoding="utf-8")
    monkeypatch.setattr(watch_state, "MAX_WATCH_STATE_BYTES", 64, raising=False)

    status = watch_state.read_watch_status(root)

    assert status["error"] == "invalid state file"
    assert status["running"] is False


def test_bounded_process_retains_only_a_limited_output_tail() -> None:
    result = run_bounded(
        [
            sys.executable,
            "-c",
            "import sys; sys.stdout.write('a' * 10000 + 'TAIL'); sys.stderr.write('b' * 10000 + 'END')",
        ],
        timeout=10,
        max_output_bytes_per_stream=128,
    )

    assert result.returncode == 0
    assert len(result.stdout.encode("utf-8")) <= 128
    assert len(result.stderr.encode("utf-8")) <= 128
    assert result.stdout.endswith("TAIL")
    assert result.stderr.endswith("END")
    assert result.output_truncated is True


def test_bounded_process_terminates_a_timed_out_child() -> None:
    with pytest.raises(subprocess.TimeoutExpired):
        run_bounded(
            [sys.executable, "-c", "import time; time.sleep(10)"],
            timeout=0.1,
            max_output_bytes_per_stream=64,
        )


def test_bounded_process_rejects_pipe_held_open_by_descendant() -> None:
    descendant_pid: int | None = None
    try:
        with pytest.raises(BoundedProcessOutputError) as raised:
            run_bounded(
                [
                    sys.executable,
                    "-c",
                    "import subprocess,sys; p=subprocess.Popen([sys.executable,'-c','import time; time.sleep(30)']); print(p.pid, flush=True)",
                ],
                timeout=5,
                max_output_bytes_per_stream=256,
            )
        descendant_pid = int(raised.value.stdout.strip())
        import psutil

        try:
            psutil.Process(descendant_pid).wait(timeout=2)
        except psutil.NoSuchProcess:
            pass
        assert not psutil.pid_exists(descendant_pid)
    finally:
        if descendant_pid is not None:
            try:
                import psutil
            except ImportError:
                pass
            else:
                try:
                    child = psutil.Process(descendant_pid)
                    child.kill()
                    child.wait(timeout=2)
                except psutil.Error:
                    pass


@pytest.mark.skipif(os.name == "nt", reason="POSIX process groups enforce descendant quiescence")
def test_bounded_process_rejects_descendant_that_closes_captured_pipes() -> None:
    descendant_pid: int | None = None
    try:
        try:
            run_bounded(
                [
                    sys.executable,
                    "-c",
                    "import subprocess,sys; p=subprocess.Popen([sys.executable,'-c','import os,time; os.close(1); os.close(2); time.sleep(30)']); print(p.pid, flush=True)",
                ],
                timeout=5,
                max_output_bytes_per_stream=256,
            )
            pytest.fail("bounded process returned while a detached descendant remained in its group")
        except BoundedProcessOutputError as exc:
            descendant_pid = int(exc.stdout.strip())
    finally:
        if descendant_pid is not None:
            import psutil

            try:
                psutil.Process(descendant_pid).wait(timeout=2)
            except psutil.NoSuchProcess:
                pass
            assert not psutil.pid_exists(descendant_pid)


@pytest.mark.skipif(os.name != "nt", reason="Windows process jobs enforce descendant-count limits")
def test_bounded_process_marks_process_tree_over_256_as_incomplete(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        security_bounded_process,
        "_windows_job_process_counts",
        lambda _handle: (security_bounded_process.MAX_BOUNDED_PROCESS_TREE_NODES + 1, 0),
    )

    with pytest.raises(BoundedProcessOutputError):
        run_bounded([sys.executable, "-c", "pass"], timeout=5)


@pytest.mark.skipif(os.name != "nt", reason="Windows suspended job setup is platform-specific")
@pytest.mark.parametrize("failure_stage", ("assignment", "resume"))
def test_bounded_process_job_setup_failure_terminates_and_fails_closed(
    monkeypatch: pytest.MonkeyPatch,
    failure_stage: str,
) -> None:
    job = object()
    process = SimpleNamespace(pid=4242, wait=Mock(return_value=0))
    terminate = Mock()
    close_job = Mock()
    assign = Mock(
        side_effect=subprocess.SubprocessError("synthetic assignment failure")
        if failure_stage == "assignment"
        else None
    )
    resume = Mock(
        side_effect=subprocess.SubprocessError("synthetic resume failure")
        if failure_stage == "resume"
        else None
    )
    monkeypatch.setattr(security_bounded_process, "_create_windows_job", lambda: job)
    monkeypatch.setattr(security_bounded_process.subprocess, "Popen", lambda *_args, **_kwargs: process)
    monkeypatch.setattr(security_bounded_process, "_assign_windows_job", assign)
    monkeypatch.setattr(security_bounded_process, "_resume_suspended_process", resume)
    monkeypatch.setattr(security_bounded_process, "_terminate_process_tree", terminate)
    monkeypatch.setattr(security_bounded_process, "_close_windows_job", close_job)

    with pytest.raises(subprocess.SubprocessError, match="could not establish bounded Windows process job"):
        run_bounded(["clamscan.exe", "--version"], timeout=5)

    assert assign.call_count == 1
    assert resume.call_count == (1 if failure_stage == "resume" else 0)
    terminate.assert_called_once_with(process, job)
    close_job.assert_called_once_with(job)
    process.wait.assert_called_once_with(timeout=2)


def test_scan_roots_and_direct_file_targets_reject_symlinks_without_scanning_outside(
    tmp_path: Path,
) -> None:
    outside = tmp_path / "outside"
    outside.mkdir()
    outside_file = outside / "fixture.txt"
    outside_file.write_text("inert target", encoding="utf-8")
    linked_root = tmp_path / "linked-root"
    linked_file = tmp_path / "linked-file.txt"
    try:
        linked_root.symlink_to(outside, target_is_directory=True)
        linked_file.symlink_to(outside_file)
    except (OSError, NotImplementedError) as exc:
        pytest.skip(f"symlink creation is unavailable on this host: {type(exc).__name__}")

    service = _service(tmp_path)
    root_results = service.scan_paths([linked_root], quarantine=False)
    direct_result = service.scan_file(linked_file, quarantine=False, use_cache=False)

    assert len(root_results) == 1
    assert root_results[0].error == "directory_scan_incomplete"
    assert root_results[0].verdict == Verdict.SCAN_ERROR
    assert direct_result.error == "reparse_point_rejected"
    assert direct_result.verdict == Verdict.SCAN_ERROR
    with service.store.connection() as connection:
        assert connection.execute("SELECT COUNT(*) FROM scan_results").fetchone()[0] == 0
    assert not (service.store.root / "quarantine").exists()


def test_lexical_path_check_rejects_windows_reparse_attribute(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    candidate = tmp_path / "junction-like-root"
    candidate.mkdir()
    original_stat = Path.stat
    reparse_flag = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)
    monkeypatch.setattr(security_service_module.stat, "FILE_ATTRIBUTE_REPARSE_POINT", reparse_flag, raising=False)

    def report_reparse_attribute(path: Path, *args, **kwargs):
        metadata = original_stat(path, *args, **kwargs)
        if path == candidate and kwargs.get("follow_symlinks") is False:
            return SimpleNamespace(st_mode=metadata.st_mode, st_file_attributes=reparse_flag)
        return metadata

    monkeypatch.setattr(Path, "stat", report_reparse_attribute)

    with pytest.raises(ReparsePathError):
        security_service_module.absolute_path_without_reparse(candidate)


def test_service_converts_reparse_roots_and_direct_files_to_review(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    root = tmp_path / "synthetic-reparse-root"
    root.mkdir()
    candidate = root / "fixture.txt"
    candidate.write_text("inert target", encoding="utf-8")
    original_check = security_service_module.absolute_path_without_reparse

    def reject_synthetic_reparse(path: Path | str) -> Path:
        if Path(path) in {root, candidate}:
            raise ReparsePathError("synthetic reparse point")
        return original_check(path)

    monkeypatch.setattr(security_service_module, "absolute_path_without_reparse", reject_synthetic_reparse)
    service = _service(tmp_path)

    root_results = service.scan_paths([root], quarantine=False)
    direct_result = service.scan_file(candidate, quarantine=False, use_cache=False)

    assert len(root_results) == 1
    assert root_results[0].error == "directory_scan_incomplete"
    assert direct_result.error == "reparse_point_rejected"
    with service.store.connection() as connection:
        assert connection.execute("SELECT COUNT(*) FROM scan_results").fetchone()[0] == 0


def test_snapshot_verification_failure_is_not_recorded_cached_or_quarantined(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    target = tmp_path / "inert-snapshot-cleanup-fixture.bin"
    target.write_bytes(b"inert snapshot cleanup fixture")
    store = SecurityStore(tmp_path / "security")
    service = SecurityService(
        store,
        {"security": {"malware": {"auto_quarantine": True}}},
    )

    class DetectionEngine:
        name = "yara"

        def version(self) -> str:
            return "inert-detection-1"

        def scan(self, _path: Path, _sha256: str) -> list[Finding]:
            return [Finding(self.name, "synthetic-inert-detection", 90)]

    service.engines = (DetectionEngine(),)
    original_hash = security_service_module.hash_stable_file
    calls = 0

    def fail_snapshot_verification(path: Path):
        nonlocal calls
        calls += 1
        if calls == 4:
            raise OSError("synthetic snapshot verification failure")
        return original_hash(path)

    monkeypatch.setattr(security_service_module, "hash_stable_file", fail_snapshot_verification)

    result = service.scan_file(target, use_cache=False)

    assert result.verdict == Verdict.SCAN_ERROR
    assert result.action == "blocked_pending_review"
    assert result.error == "scan_snapshot_unavailable"
    assert result.findings == ()
    assert calls == 4
    with store.connection() as connection:
        assert connection.execute("SELECT COUNT(*) FROM scan_results").fetchone()[0] == 0
        assert connection.execute("SELECT COUNT(*) FROM quarantine_items").fetchone()[0] == 0
    assert not (store.root / "quarantine").exists()
    assert not (store.root / "vault-key.dpapi").exists()


@pytest.mark.parametrize("suffix", ("ndb", "hdb", "ldb"))
def test_clamav_cache_identity_tracks_supplemental_definition_bytes(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    suffix: str,
) -> None:
    scanner = tmp_path / "clamscan.exe"
    scanner.write_bytes(b"inert scanner identity fixture")
    monkeypatch.setattr(
        security_engines.shutil,
        "which",
        lambda name: str(scanner) if name == "clamscan" else None,
    )
    database = tmp_path / "supplemental-database"
    database.mkdir()
    definition = database / f"extra.{suffix}"
    definition.write_bytes(b"A" * 64)
    fixed_mtime = definition.stat().st_mtime_ns
    run = Mock(return_value=SimpleNamespace(stdout="ClamAV test-version", stderr="", returncode=0))
    monkeypatch.setattr(security_engines.subprocess, "run", run)

    engine = ClamAVEngine(database_dir=database)
    before = engine.version()
    definition.write_bytes(b"B" * 64)
    os.utime(definition, ns=(fixed_mtime, fixed_mtime))
    after = engine.version()

    assert before != after
    run.assert_not_called()


def test_oversized_target_is_rejected_before_hashing_or_persistence(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    target = tmp_path / "inert-oversized-target.bin"
    target.write_bytes(b"123456789")
    service = _service(tmp_path)
    monkeypatch.setattr(security_service_module, "MAX_SCAN_TARGET_BYTES", 8, raising=False)
    first_hash = Mock(wraps=service._hash_stable)
    monkeypatch.setattr(service, "_hash_stable", first_hash)

    result = service.scan_file(target, quarantine=False, use_cache=False)

    assert result.verdict == Verdict.SCAN_ERROR
    assert result.action == "blocked_pending_review"
    assert result.error == "scan_target_too_large"
    first_hash.assert_not_called()
    with service.store.connection() as connection:
        assert connection.execute("SELECT COUNT(*) FROM scan_results").fetchone()[0] == 0
    assert not (service.store.root / "quarantine").exists()


def test_yara_same_instance_recompiles_when_rule_contents_change(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    rules = tmp_path / "rules"
    rules.mkdir()
    rule = rules / "sample.yar"
    rule.write_text("rule Old { condition: true }\n", encoding="utf-8")
    original_mtime = rule.stat().st_mtime_ns
    target = tmp_path / "inert-target.bin"
    target.write_bytes(b"inert target")

    class CompiledRules:
        def __init__(self, names: tuple[str, ...]) -> None:
            self.names = names

        def match(self, *_args, **_kwargs):
            return [SimpleNamespace(rule=name, meta={}, tags=[]) for name in self.names]

    class FakeYara:
        def compile(self, *, source=None, sources=None):
            if source is not None:
                return object()
            return CompiledRules(tuple(item.split()[1] for item in sources.values()))

    monkeypatch.setattr(security_engines.importlib.util, "find_spec", lambda _name: SimpleNamespace())
    monkeypatch.setattr(security_engines.importlib, "import_module", lambda _name: FakeYara())
    engine = security_engines.YaraEngine(rules)
    first_version = engine.version()
    first_findings = engine.scan(target, "inert-sha256")

    rule.write_text("rule New { condition: true }\n", encoding="utf-8")
    os.utime(rule, ns=(original_mtime, original_mtime))
    second_version = engine.version()
    second_findings = engine.scan(target, "inert-sha256")

    assert first_version != second_version
    assert [finding.name for finding in first_findings] == ["Old"]
    assert [finding.name for finding in second_findings] == ["New"]


@pytest.mark.parametrize("positive_source", ("yara", "hash_reputation"))
def test_version_error_does_not_suppress_positive_independent_findings_or_quarantine(
    tmp_path: Path,
    positive_source: str,
) -> None:
    class ClamAVVersionError:
        name = "clamav"

        def version(self) -> str:
            return EngineState.ENGINE_ERROR.value

        def scan(self, _path: Path, _sha256: str) -> list[Finding]:
            return [Finding(self.name, "no_detection", 0)]

    class PositiveEngine:
        name = positive_source

        def version(self) -> str:
            return "positive-fixture-v1"

        def scan(self, _path: Path, _sha256: str) -> list[Finding]:
            return [Finding(self.name, "synthetic-known-detection", 90)]

    target = tmp_path / "inert-detected-target.bin"
    target.write_bytes(b"inert target")
    service = SecurityService(
        SecurityStore(tmp_path / "security"),
        {"security": {"malware": {"auto_quarantine": True}}},
    )
    service.engines = (ClamAVVersionError(), PositiveEngine())
    quarantine = Mock(return_value="fixture-quarantine-id")
    service._vault = SimpleNamespace(quarantine=quarantine)

    result = service.scan_file(target)
    projection = result.to_dict()

    assert result.verdict == Verdict.MALICIOUS
    expected_health = "DEGRADED" if positive_source == "yara" else "ERROR"
    assert projection["engine_health"] == expected_health
    assert projection["execution_decision"] == "BLOCK"
    assert result.action == "quarantined"
    assert result.quarantine_id == "fixture-quarantine-id"
    assert any(finding.name == "synthetic-known-detection" for finding in result.findings)
    assert any(
        finding.source == "clamav" and finding.state == EngineState.ENGINE_ERROR
        for finding in result.findings
    )
    quarantine.assert_called_once()
    with service.store.connection() as connection:
        assert connection.execute("SELECT COUNT(*) FROM scan_results").fetchone()[0] == 0


def test_cached_result_is_rejected_when_engine_version_degrades_before_return(
    tmp_path: Path,
) -> None:
    class FlippingVersionEngine:
        name = "clamav"

        def __init__(self) -> None:
            self.version_calls = 0
            self.scan_calls = 0

        def version(self) -> str:
            self.version_calls += 1
            if self.version_calls == 1:
                return "healthy-fixture-v1"
            return EngineState.ENGINE_ERROR.value

        def scan(self, _path: Path, _sha256: str) -> list[Finding]:
            self.scan_calls += 1
            return [Finding(self.name, "no_detection", 0)]

    target = tmp_path / "inert-cached-target.bin"
    target.write_bytes(b"inert target")
    service = _service(tmp_path)
    engine = FlippingVersionEngine()
    service.engines = (engine,)
    sha256, size, _identity = service._hash_stable(target)
    healthy_versions = {"clamav": "healthy-fixture-v1"}
    service.store.record_scan(
        ScanResult(
            str(target),
            sha256,
            size,
            Verdict.CLEAN,
            0,
            "allow",
            (Finding("clamav", "no_detection", 0),),
            healthy_versions,
        ),
        versions_cache_key(healthy_versions),
    )

    result = service.scan_file(target, quarantine=False)

    assert engine.version_calls == 2
    assert engine.scan_calls == 0
    assert result.cached is False
    assert result.verdict == Verdict.SCAN_ERROR
    assert result.engine_versions == {"clamav": EngineState.ENGINE_ERROR.value}
    assert any(finding.state == EngineState.ENGINE_ERROR for finding in result.findings)
    assert service.store.cache_get(sha256, versions_cache_key({"clamav": EngineState.ENGINE_ERROR.value})) is None
    assert service.store.cache_get(sha256, versions_cache_key(healthy_versions)).verdict == Verdict.CLEAN


@pytest.mark.parametrize("swap_boundary", ("before_hash", "before_snapshot"))
def test_target_ancestor_reparse_swap_is_rejected_at_read_boundaries(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    swap_boundary: str,
) -> None:
    parent = tmp_path / "scan-parent"
    parent.mkdir()
    target = parent / "inert-target.bin"
    target.write_bytes(b"inside inert target")
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / target.name).write_bytes(b"outside inert target")
    displaced_parent = tmp_path / "scan-parent-original"
    swapped = False

    def swap_ancestor() -> None:
        nonlocal swapped
        if swapped:
            return
        parent.rename(displaced_parent)
        try:
            parent.symlink_to(outside, target_is_directory=True)
        except (OSError, NotImplementedError) as exc:
            displaced_parent.rename(parent)
            pytest.skip(f"directory symlink creation is unavailable on this host: {type(exc).__name__}")
        swapped = True

    class CleanEngine:
        name = "clamav"

        def __init__(self) -> None:
            self.scan_calls = 0

        def version(self) -> str:
            if swap_boundary == "before_snapshot":
                swap_ancestor()
            return "clean-fixture-v1"

        def scan(self, _path: Path, _sha256: str) -> list[Finding]:
            self.scan_calls += 1
            return [Finding(self.name, "no_detection", 0)]

    service = _service(tmp_path)
    engine = CleanEngine()
    service.engines = (engine,)
    if swap_boundary == "before_hash":
        original_hash = service._hash_stable

        def swap_before_hash(path: Path):
            swap_ancestor()
            return original_hash(path)

        monkeypatch.setattr(service, "_hash_stable", swap_before_hash)

    result = service.scan_file(target, quarantine=False, use_cache=False)

    assert swapped
    assert result.verdict == Verdict.SCAN_ERROR
    assert result.error == "file_changed_during_scan"
    assert result.action == "blocked_pending_review"
    assert engine.scan_calls == 0
    with service.store.connection() as connection:
        assert connection.execute("SELECT COUNT(*) FROM scan_results").fetchone()[0] == 0
    assert not (service.store.root / "quarantine").exists()


@pytest.mark.parametrize("swap_boundary", ("before_hash", "before_snapshot"))
def test_reparse_ancestor_replacement_is_rechecked_at_read_boundaries(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    swap_boundary: str,
) -> None:
    parent = tmp_path / "synthetic-scan-parent"
    parent.mkdir()
    target = parent / "inert-target.bin"
    target.write_bytes(b"inert target")
    reparse_flag = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)
    monkeypatch.setattr(security_service_module.stat, "FILE_ATTRIBUTE_REPARSE_POINT", reparse_flag, raising=False)
    original_stat = Path.stat
    ancestor_replaced = False
    scanner = Mock(return_value=[Finding("clamav", "no_detection", 0)])

    def report_reparse_after_swap(path: Path, *args, **kwargs):
        metadata = original_stat(path, *args, **kwargs)
        if ancestor_replaced and path == parent and kwargs.get("follow_symlinks") is False:
            return SimpleNamespace(st_mode=metadata.st_mode, st_file_attributes=reparse_flag)
        return metadata

    monkeypatch.setattr(Path, "stat", report_reparse_after_swap)

    def replace_ancestor() -> None:
        nonlocal ancestor_replaced
        ancestor_replaced = True

    class CleanEngine:
        name = "clamav"

        def version(self) -> str:
            if swap_boundary == "before_snapshot":
                replace_ancestor()
            return "clean-fixture-v1"

        def scan(self, *args, **kwargs):
            return scanner(*args, **kwargs)

    service = _service(tmp_path)
    service.engines = (CleanEngine(),)
    if swap_boundary == "before_hash":
        original_hash = service._hash_stable

        def replace_before_hash(path: Path):
            replace_ancestor()
            return original_hash(path)

        monkeypatch.setattr(service, "_hash_stable", replace_before_hash)

    result = service.scan_file(target, quarantine=False, use_cache=False)

    assert ancestor_replaced
    assert result.verdict == Verdict.SCAN_ERROR
    assert result.error == "file_changed_during_scan"
    assert result.action == "blocked_pending_review"
    scanner.assert_not_called()
    with service.store.connection() as connection:
        assert connection.execute("SELECT COUNT(*) FROM scan_results").fetchone()[0] == 0
    assert not (service.store.root / "quarantine").exists()


def test_watcher_root_limit_remains_incomplete_until_inventory_recovers(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    roots = [tmp_path / "first-root", tmp_path / "second-root"]
    for root in roots:
        root.mkdir()
    monkeypatch.setattr(security_watcher, "MAX_SCAN_ROOTS", 1)
    service = ReconcileServiceStub(roots[0])
    service.quick_paths = Mock(return_value=roots)
    inventory_event_state: dict[str, float | str] = {}

    current = reconcile_once(service, {}, scan_changes=False, inventory_event_state=inventory_event_state)
    reconcile_once(service, current, scan_changes=False, inventory_event_state=inventory_event_state)

    inventory_events = [
        call for call in service.store.event.call_args_list
        if call.args and call.args[0] == "watch_inventory_incomplete"
    ]
    assert len(inventory_events) == 1
    assert inventory_events[0].args[4]["reason"] == "root_limit"
    assert inventory_event_state["<root-limit>"] == "root_limit"


def test_bounded_process_pipe_read_failure_is_typed_and_fails_closed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        security_bounded_process.os,
        "read",
        Mock(side_effect=OSError("synthetic pipe read failure")),
    )

    with pytest.raises(BoundedProcessOutputError) as error:
        run_bounded(
            [sys.executable, "-c", "print('benign scanner output')"],
            timeout=10,
            max_output_bytes_per_stream=128,
        )

    assert error.value.reason == "output_pipe_read_failed"


def test_active_snapshot_budget_is_process_global_and_reserved_before_hashing(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    first_target = tmp_path / "first-small-target.bin"
    second_target = tmp_path / "second-small-target.bin"
    first_target.write_bytes(b"1234")
    second_target.write_bytes(b"5678")
    first_service = _service(tmp_path / "first-profile")
    second_service = _service(tmp_path / "second-profile")
    monkeypatch.setattr(security_service_module, "MAX_SCAN_TARGET_BYTES", 8, raising=False)
    monkeypatch.setattr(security_service_module, "MAX_ACTIVE_SCAN_BYTES", 6, raising=False)
    first_hash_entered = threading.Event()
    release_first_hash = threading.Event()
    original_first_hash = first_service._hash_stable
    second_hash = Mock(wraps=second_service._hash_stable)

    def hold_first_reservation(path: Path):
        first_hash_entered.set()
        assert release_first_hash.wait(5)
        return original_first_hash(path)

    monkeypatch.setattr(first_service, "_hash_stable", hold_first_reservation)
    monkeypatch.setattr(second_service, "_hash_stable", second_hash)
    with ThreadPoolExecutor(max_workers=1) as pool:
        first_future = pool.submit(
            first_service.scan_file,
            first_target,
            quarantine=False,
            use_cache=False,
        )
        try:
            assert first_hash_entered.wait(5)
            rejected = second_service.scan_file(
                second_target,
                quarantine=False,
                use_cache=False,
            )
        finally:
            release_first_hash.set()
        first_result = first_future.result(timeout=10)

    assert rejected.verdict == Verdict.SCAN_ERROR
    assert rejected.action == "blocked_pending_review"
    assert rejected.error == "scan_budget_exceeded"
    second_hash.assert_not_called()
    assert first_result.verdict == Verdict.CLEAN
    with second_service.store.connection() as connection:
        assert connection.execute("SELECT COUNT(*) FROM scan_results").fetchone()[0] == 0


_TOUCHED_MTIME_NS = 1_600_000_000_000_000_000


def _write_touched(path: Path, data: bytes) -> Path:
    path.write_bytes(data)
    # NTFS stamps files from the coarse system clock; wait past its tick so the
    # utime below moves the metadata change time strictly after creation time,
    # which is the state left behind by sync_bundled_yara_rules.
    time.sleep(0.05)
    os.utime(path, ns=(_TOUCHED_MTIME_NS, _TOUCHED_MTIME_NS))
    return path


def test_stable_file_time_prefers_birthtime_only_for_windows_data() -> None:
    with_birth = SimpleNamespace(st_ctime_ns=200, st_birthtime_ns=100)
    without_birth = SimpleNamespace(st_ctime_ns=200)

    assert stable_file_time_ns(with_birth, windows=True) == 100
    assert stable_file_time_ns(with_birth, windows=False) == 200
    assert stable_file_time_ns(without_birth, windows=True) == 200
    assert stable_file_time_ns(without_birth, windows=False) == 200


def test_hash_stable_file_accepts_unchanged_touched_file(tmp_path: Path) -> None:
    data = b"inert unchanged fixture"
    target = _write_touched(tmp_path / "touched.txt", data)

    sha256, size, identity = security_service_module.hash_stable_file(target)

    assert sha256 == hashlib.sha256(data).hexdigest()
    assert size == len(data)
    assert identity == security_service_module._stat_identity(target.stat(follow_symlinks=False))


def test_scan_snapshot_accepts_unchanged_touched_file(tmp_path: Path) -> None:
    target = _write_touched(tmp_path / "touched.txt", b"inert unchanged fixture")

    result = _service(tmp_path).scan_file(target, quarantine=False, use_cache=False)

    assert result.error is None
    assert result.verdict == Verdict.CLEAN


def test_clamav_definition_inventory_accepts_unchanged_touched_file(tmp_path: Path) -> None:
    database = tmp_path / "clamav-db"
    database.mkdir()
    _write_touched(database / "custom.hdb", b"0" * 32 + b":4:inert\n")

    inventory = security_clamav_definitions.inventory_clamav_definitions(database)

    assert [item.name for item in inventory.files] == ["custom.hdb"]


def test_yara_rule_inventory_accepts_unchanged_touched_file(tmp_path: Path) -> None:
    rules = tmp_path / "yara"
    rules.mkdir()
    _write_touched(rules / "inert.yar", b"rule inert { condition: false }\n")

    sources, error, revision = security_engines.YaraEngine(rules)._read_inventory()

    assert error is None
    assert set(sources) == {"inert"}
    assert revision


def test_bundled_yara_sync_reads_unchanged_touched_files(tmp_path: Path) -> None:
    data = b"rule inert { condition: false }\n"
    bundled = tmp_path / "bundled"
    bundled.mkdir()
    _write_touched(bundled / "inert.yar", data)
    existing = _write_touched(tmp_path / "existing.yar", data)

    files, version, error = security_updates._inventory_bundled_yara_rules(bundled)

    assert error is None
    assert [item[1] for item in files] == [data]
    assert version != "bundled"
    assert security_updates._read_existing_yara_rule(existing) == data


def test_hash_policy_rejects_replaced_file_with_identical_size_and_mtime(tmp_path: Path) -> None:
    target = _write_touched(tmp_path / "target.bin", b"original-bytes")
    _sha256, size, identity = security_service_module.hash_stable_file(target)
    replacement = _write_touched(tmp_path / "replacement.bin", b"replaced-bytes")
    os.replace(replacement, target)

    with pytest.raises(RuntimeError, match="file changed during scan"):
        security_service_module._hash_with_policy(
            target,
            max_bytes=1024,
            expected_size=size,
            expected_identity=identity,
        )


def test_hash_policy_rejects_same_path_content_mutation(tmp_path: Path) -> None:
    target = _write_touched(tmp_path / "target.bin", b"original-bytes")
    _sha256, size, identity = security_service_module.hash_stable_file(target)
    target.write_bytes(b"mutated--bytes")

    with pytest.raises(RuntimeError, match="file changed during scan"):
        security_service_module._hash_with_policy(
            target,
            max_bytes=1024,
            expected_size=size,
            expected_identity=identity,
        )


def test_hash_stable_file_rejects_mutation_after_handle_read(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    target = _write_touched(tmp_path / "target.bin", b"original-bytes")
    original_check = security_service_module._assert_path_has_no_reparse_components
    calls = 0

    def mutate_after_read(path: Path) -> None:
        nonlocal calls
        calls += 1
        if calls == 4:
            target.write_bytes(b"mutated--bytes")
        original_check(path)

    monkeypatch.setattr(security_service_module, "_assert_path_has_no_reparse_components", mutate_after_read)

    with pytest.raises(RuntimeError, match="file changed during scan"):
        security_service_module.hash_stable_file(target)
    assert calls == 4


def test_scan_snapshot_rejects_bytes_that_differ_from_the_source_digest(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    target = _write_touched(tmp_path / "target.bin", b"original-bytes")
    service = _service(tmp_path)
    engine = Mock(wraps=CleanEngine())
    engine.name = "clamav"
    service.engines = (engine,)
    original_write = security_service_module._write_snapshot_chunk

    def write_corrupted(handle: object, chunk: bytes) -> None:
        original_write(handle, bytes(byte ^ 0xFF for byte in chunk))

    monkeypatch.setattr(security_service_module, "_write_snapshot_chunk", write_corrupted)

    result = service.scan_file(target, quarantine=False, use_cache=False)

    assert result.verdict == Verdict.SCAN_ERROR
    assert result.error == "scan_snapshot_unavailable"
    engine.scan.assert_not_called()


@pytest.mark.windows_only
def test_native_junction_components_are_rejected_before_hashing(tmp_path: Path) -> None:
    winapi = pytest.importorskip("_winapi")
    outside = tmp_path / "outside"
    outside.mkdir()
    _write_touched(outside / "fixture.txt", b"inert target")
    junction = tmp_path / "junction"
    try:
        winapi.CreateJunction(str(outside), str(junction))
    except OSError as exc:
        pytest.skip(f"BLOCKED_NATIVE_PATH: junction creation denied: {type(exc).__name__}")
    through_junction = junction / "fixture.txt"

    with pytest.raises(RuntimeError):
        security_service_module.hash_stable_file(through_junction)
    result = _service(tmp_path).scan_file(through_junction, quarantine=False, use_cache=False)

    assert result.verdict == Verdict.SCAN_ERROR
    assert result.error == "reparse_point_rejected"
