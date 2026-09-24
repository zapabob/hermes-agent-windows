from __future__ import annotations

import hashlib
import importlib
import json
import os
import shutil
import sqlite3
import sys
import zipfile
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace
from typing import cast
from unittest.mock import Mock, call, patch

import pytest
from cryptography.exceptions import InvalidTag

from downstream.security.engines import (
    ClamAVEngine,
    DefinitionInventoryError,
    HashReputationEngine,
    StaticHeuristicsEngine,
    YaraEngine,
    inventory_clamav_definitions,
)
from downstream.security.cli import _watch_disable, _watch_enable, resume_watch_if_enabled
from downstream.security import cli as security_cli
from downstream.security import watch_state, watcher as security_watcher
from downstream.security.execution_gate import _candidates, preflight_command
from downstream.security.models import EngineState, Finding, ScanResult, Verdict
from downstream.security.service import SecurityService
from downstream.security.store import SecurityStore
from downstream.security.updates import DefinitionUpdater
from downstream.security.watcher import reconcile_once


EICAR = b"X5O!P%@AP[4\\PZX54(P^)7CC)7}$EICAR-STANDARD-ANTIVIRUS-TEST-FILE!$H+H*"


class DetectionEngine:
    name = "clamav"

    def version(self) -> str:
        return "test-signatures-1"

    def scan(self, _path: Path, _sha256: str) -> list[Finding]:
        return [Finding(self.name, "Eicar-Signature", 90)]


class CleanEngine:
    name = "clamav"

    def version(self) -> str:
        return "test-signatures-1"

    def scan(self, _path: Path, _sha256: str) -> list[Finding]:
        return [Finding(self.name, "no_detection", 0)]


class UnavailableEngine:
    name = "clamav"

    def version(self) -> str:
        return EngineState.SCANNER_UNAVAILABLE.value

    def scan(self, _path: Path, _sha256: str) -> list[Finding]:
        return [Finding(self.name, "unavailable", 0, EngineState.SCANNER_UNAVAILABLE)]


class TimeoutEngine:
    name = "clamav"

    def version(self) -> str:
        return "test-signatures-1"

    def scan(self, _path: Path, _sha256: str) -> list[Finding]:
        return [Finding(self.name, "bounded timeout", 0, EngineState.SCAN_TIMEOUT)]


class WatchStoreStub:
    def __init__(self, root: Path | None = None) -> None:
        self.root = root or Path.cwd()
        self.event = Mock()


class WatchControlServiceStub:
    def __init__(self, root: Path) -> None:
        self.config: dict[str, object] = {"watch_interval": 7}
        self.store = WatchStoreStub(root)
        self._statuses = iter((
            {"running": False},
            {"enabled": True, "pid": 4242, "running": True},
        ))

    def watch_status(self) -> dict[str, object]:
        return next(self._statuses)


class ReconcileServiceStub:
    def __init__(self, root: Path) -> None:
        self.root = root
        self.store = WatchStoreStub(root)
        self.scan_file = Mock()

    def quick_paths(self) -> list[Path]:
        return [self.root]


def service_for(tmp_path: Path, engine: object) -> SecurityService:
    store = SecurityStore(tmp_path / "security")
    service = SecurityService(store, {"security": {"malware": {"auto_quarantine": True}}})
    service.engines = (engine, StaticHeuristicsEngine())
    return service


def test_read_only_service_does_not_create_security_state(tmp_path: Path) -> None:
    root = tmp_path / "security"

    service = SecurityService(SecurityStore(root, read_only=True), {}, read_only=True)

    assert service.status()["summary"]["files_scanned"] == 0
    assert not root.exists()


def test_read_only_store_reads_existing_state_without_writing(tmp_path: Path) -> None:
    root = tmp_path / "security"
    writable = SecurityStore(root)
    writable.upsert_feed("hash_reputation", "2026.09.01", "ok", {})

    read_only = SecurityStore(root, read_only=True)

    assert read_only.feed_versions() == {"hash_reputation": "2026.09.01"}
    with pytest.raises(RuntimeError, match="read-only"):
        read_only.upsert_feed("hash_reputation", "changed", "ok", {})


def test_unavailable_authoritative_scanner_is_not_clean(tmp_path: Path) -> None:
    target = tmp_path / "sample.txt"
    target.write_text("harmless", encoding="utf-8")
    result = service_for(tmp_path, UnavailableEngine()).scan_file(target, quarantine=False)
    assert result.verdict == Verdict.SCAN_ERROR
    assert result.action == "blocked_pending_review"


def test_clean_file_is_clean_with_available_authoritative_scanner(tmp_path: Path) -> None:
    target = tmp_path / "clean.txt"
    target.write_text("harmless", encoding="utf-8")
    result = service_for(tmp_path, CleanEngine()).scan_file(target, quarantine=False)
    assert result.verdict == Verdict.CLEAN
    assert result.action == "allow"


def test_scanner_timeout_is_scan_error(tmp_path: Path) -> None:
    target = tmp_path / "timeout.bin"
    target.write_bytes(b"bounded")
    result = service_for(tmp_path, TimeoutEngine()).scan_file(target, quarantine=False)
    assert result.verdict == Verdict.SCAN_ERROR
    assert result.error == "bounded timeout"


def test_static_heuristic_only_warns(tmp_path: Path) -> None:
    target = tmp_path / "invoice.pdf.exe"
    target.write_bytes(b"MZ" + b"0" * 32)
    result = service_for(tmp_path, UnavailableEngine()).scan_file(target, quarantine=False)
    assert result.verdict == Verdict.SUSPICIOUS
    assert result.score == 20
    assert target.exists()


def test_high_confidence_detection_is_encrypted_before_source_removal(tmp_path: Path) -> None:
    target = tmp_path / "eicar.com"
    target.write_bytes(EICAR)
    service = service_for(tmp_path, DetectionEngine())
    result = service.scan_file(target)
    assert result.verdict == Verdict.MALICIOUS
    assert result.action == "quarantined"
    assert not target.exists()
    item = service.vault.inspect(str(result.quarantine_id))
    blob = service.vault.root / str(item["blob_name"])
    payload = blob.read_bytes()
    assert payload.startswith(b"HERMESQ1")
    assert EICAR not in payload
    assert hashlib.sha256(EICAR).hexdigest() == item["sha256"]


def test_restore_rescans_and_never_overwrites(tmp_path: Path) -> None:
    target = tmp_path / "eicar.com"
    target.write_bytes(EICAR)
    service = service_for(tmp_path, DetectionEngine())
    item_id = str(service.scan_file(target).quarantine_id)
    target.write_text("existing", encoding="utf-8")
    with pytest.raises(FileExistsError):
        service.vault.restore(item_id, lambda path: service.scan_file(path, quarantine=False, use_cache=False))
    target.unlink()
    malicious = ScanResult(str(target), hashlib.sha256(EICAR).hexdigest(), len(EICAR), Verdict.MALICIOUS, 90, "quarantine", (), {})
    with pytest.raises(PermissionError):
        service.vault.restore(item_id, lambda _path: malicious)
    restored = service.vault.restore(item_id, lambda _path: malicious, force=True)
    assert restored.read_bytes() == EICAR


def test_cache_key_changes_with_signature_version(tmp_path: Path) -> None:
    target = tmp_path / "sample.txt"
    target.write_text("harmless", encoding="utf-8")
    service = service_for(tmp_path, CleanEngine())
    first = service.scan_file(target, quarantine=False)
    second = service.scan_file(target, quarantine=False)
    assert first.cached is False
    assert second.cached is True
    service.engines = (SimpleNamespace(name="clamav", version=lambda: "test-signatures-2", scan=lambda _p, _h: [Finding("clamav", "no_detection", 0)]),)
    third = service.scan_file(target, quarantine=False)
    assert third.cached is False


def test_known_sha256_fixture_is_malicious_and_allowlist_preserves_evidence(tmp_path: Path) -> None:
    target = tmp_path / "known.bin"
    target.write_bytes(b"known deterministic fixture")
    sha256 = hashlib.sha256(target.read_bytes()).hexdigest()
    service = service_for(tmp_path, CleanEngine())
    service.store.upsert_malware_hash(
        sha256,
        source="test-feed",
        malware_family="Hermes.Test.Fixture",
        confidence=100,
        feed_version="test-1",
    )
    service.engines = (HashReputationEngine(service.store), CleanEngine(), StaticHeuristicsEngine())
    first = service.scan_file(target, quarantine=False)
    assert first.verdict == Verdict.MALICIOUS
    assert first.score == 100
    with service.store.connection() as con:
        con.execute(
            "INSERT INTO allowlist(kind,value,reason,created_by,created_at) VALUES('sha256',?,?,?,datetime('now'))",
            (sha256, "verified false positive", "test-user"),
        )
    allowed = service.scan_file(target, quarantine=False, use_cache=False)
    assert allowed.verdict == Verdict.MALICIOUS
    assert allowed.action == "allowlisted"
    assert any(finding.name == "Hermes.Test.Fixture" for finding in allowed.findings)


def test_execution_gate_finds_local_high_risk_arguments(tmp_path: Path) -> None:
    script = tmp_path / "downloaded.ps1"
    script.write_text("Write-Output ok", encoding="utf-8")
    ignored = tmp_path / "notes.txt"
    ignored.write_text("notes", encoding="utf-8")
    assert _candidates(f"powershell -File {script.name} {ignored.name}", tmp_path) == [script]


def test_execution_gate_returns_stable_shape_without_candidates(tmp_path: Path) -> None:
    assert preflight_command("python -c 'print(1)'", str(tmp_path)) == {
        "allowed": True,
        "blocked": [],
        "warnings": [],
        "results": [],
    }


@pytest.mark.parametrize("name", ["path with spaces.txt", "日本語の検査対象.txt"])
def test_scan_supports_spaces_and_unicode_paths(tmp_path: Path, name: str) -> None:
    target = tmp_path / name
    target.write_text("harmless", encoding="utf-8")
    result = service_for(tmp_path, CleanEngine()).scan_file(target, quarantine=False)
    assert result.verdict == Verdict.CLEAN
    assert Path(result.path).name == name


def test_directory_scan_skips_reparse_points(tmp_path: Path) -> None:
    root = tmp_path / "root"
    skipped = root / "junction"
    skipped.mkdir(parents=True)
    (root / "clean.txt").write_text("clean", encoding="utf-8")
    (skipped / "hidden.txt").write_text("must not be visited", encoding="utf-8")
    service = service_for(tmp_path, CleanEngine())
    with patch("downstream.security.service.is_reparse_point", side_effect=lambda path: path == skipped):
        results = service.scan_paths([root], quarantine=False)
    clean = next(result for result in results if Path(result.path).name == "clean.txt")
    incomplete = next(result for result in results if Path(result.path).name == "root")
    assert clean.verdict == Verdict.CLEAN
    assert incomplete.verdict == Verdict.SCAN_ERROR
    assert incomplete.error == "directory_scan_incomplete"
    assert incomplete.action == "blocked_pending_review"


def test_locked_or_unreadable_file_is_scan_error(tmp_path: Path) -> None:
    target = tmp_path / "locked.bin"
    target.write_bytes(b"locked")
    service = service_for(tmp_path, CleanEngine())
    with patch.object(service, "_hash_stable", side_effect=PermissionError("sharing violation")):
        result = service.scan_file(target, quarantine=False)
    assert result.verdict == Verdict.SCAN_ERROR
    assert "sharing violation" in str(result.error)


def test_large_file_and_archive_are_scanned_without_special_execution(tmp_path: Path) -> None:
    large = tmp_path / "large.bin"
    large.write_bytes(b"0" * (2 * 1024 * 1024))
    archive = tmp_path / "fixture.zip"
    with zipfile.ZipFile(archive, "w", compression=zipfile.ZIP_DEFLATED) as handle:
        handle.writestr("document.txt", "harmless")
    service = service_for(tmp_path, CleanEngine())
    results = service.scan_paths([large, archive], workers=2, quarantine=False)
    assert {Path(result.path).name for result in results} == {"large.bin", "fixture.zip"}
    assert all(result.verdict == Verdict.CLEAN for result in results)


def test_concurrent_scan_returns_each_file_once(tmp_path: Path) -> None:
    files = []
    for index in range(8):
        target = tmp_path / f"concurrent-{index}.txt"
        target.write_text(f"fixture-{index}", encoding="utf-8")
        files.append(target)
    results = service_for(tmp_path, CleanEngine()).scan_paths(files, workers=4, quarantine=False)
    assert len(results) == len(files)
    assert {result.sha256 for result in results} == {hashlib.sha256(path.read_bytes()).hexdigest() for path in files}


def test_watch_enable_reports_ready_watcher_pid(tmp_path: Path) -> None:
    service = WatchControlServiceStub(tmp_path / "security")
    with patch("downstream.security.cli.subprocess.Popen", return_value=SimpleNamespace(pid=4242)) as popen, patch(
        "downstream.security.cli.verified_watch_owner",
        return_value=SimpleNamespace(pid=4242),
    ), patch("downstream.security.cli.time.sleep"):
        result = _watch_enable(cast(SecurityService, service))
    assert result == {"ok": True, "enabled": True, "pid": 4242, "running": True}
    assert popen.call_args.args[0][3:5] == ["--interval", "7.0"]
    assert popen.call_args.args[0][5] == "--request-nonce"
    assert popen.call_args.args[0][7] == "--owner-nonce"
    assert popen.call_args.kwargs["env"]["HERMES_HOME"] == str(tmp_path.resolve())
    service.store.event.assert_called_once_with("watch", "4242", None, "enabled", {})


def test_watch_enable_timeout_cleans_up_child_and_preserves_request(tmp_path: Path) -> None:
    service = WatchControlServiceStub(tmp_path / "security")
    service._statuses = iter(({"enabled": True, "pid": None, "running": False},))
    process = SimpleNamespace(pid=1111, poll=Mock(return_value=None), terminate=Mock(), wait=Mock(), kill=Mock())
    clock = SimpleNamespace(monotonic=Mock(side_effect=(0.0, 6.0)), sleep=Mock())
    with patch("downstream.security.cli.subprocess.Popen", return_value=process), patch(
        "downstream.security.cli.time",
        clock,
    ):
        result = _watch_enable(cast(SecurityService, service))

    assert result["ok"] is False
    assert result["enabled"] is True
    process.terminate.assert_called_once_with()
    process.wait.assert_called_once_with(timeout=3)
    process.kill.assert_not_called()
    persisted = json.loads((service.store.root / "watch-state.json").read_text(encoding="utf-8"))
    assert persisted["enabled"] is True
    assert persisted["pid"] is None


def test_windows_watcher_spawn_retries_without_breakaway(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    child = SimpleNamespace(pid=4242)
    popen = Mock(side_effect=(PermissionError("breakaway denied"), child))
    monkeypatch.setattr(security_cli.sys, "platform", "win32")
    monkeypatch.setattr(security_cli.subprocess, "Popen", popen)
    monkeypatch.setattr(security_cli, "windows_detach_flags", lambda: 0x100)
    monkeypatch.setattr(security_cli, "windows_detach_flags_without_breakaway", lambda: 0x200)
    monkeypatch.setattr(security_cli, "windows_hide_flags", lambda: 0x10)

    result = security_cli._spawn_watcher([sys.executable, "-m", "downstream.security.watcher"], tmp_path)

    assert result is child
    assert popen.call_count == 2
    assert popen.call_args_list[0].kwargs["creationflags"] == 0x110
    assert popen.call_args_list[1].kwargs["creationflags"] == 0x210


def test_watch_disable_never_signals_unverified_pid(tmp_path: Path) -> None:
    service = WatchControlServiceStub(tmp_path / "security")
    process = Mock()
    with patch(
        "downstream.security.cli.prepare_watch_disable",
        return_value=({"enabled": False, "pid": 4242}, None),
    ), patch("downstream.security.cli.psutil.Process", return_value=process):
        result = _watch_disable(cast(SecurityService, service))

    assert result == {"ok": True, "enabled": False, "pid": None, "running": False}
    process.terminate.assert_not_called()


def test_resume_watch_is_noop_without_persisted_request(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    import hermes_constants

    monkeypatch.setattr(hermes_constants, "get_hermes_home", lambda: tmp_path)
    monkeypatch.setattr(
        "downstream.security.cli.SecurityService",
        lambda: pytest.fail("disabled watcher must not materialize Security Center"),
    )

    result = resume_watch_if_enabled()

    assert result == {"ok": True, "enabled": False, "pid": None, "running": False}
    assert not (tmp_path / "security").exists()


def test_resume_watch_restarts_persisted_request(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    import hermes_constants

    root = tmp_path / "security"
    watch_state.set_watch_enabled(root, True)
    service = object()
    enabled = Mock(return_value={"ok": True, "enabled": True, "pid": 7, "running": True})
    monkeypatch.setattr(hermes_constants, "get_hermes_home", lambda: tmp_path)
    monkeypatch.setattr(security_cli, "SecurityService", lambda: service)
    monkeypatch.setattr(security_cli, "_watch_enable_locked", enabled)

    result = resume_watch_if_enabled()

    assert result["running"] is True
    enabled.assert_called_once_with(service)


def test_resume_does_not_recreate_profile_deleted_before_control_lock(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    home = tmp_path / "profiles" / "research"
    root = home / "security"
    watch_state.set_watch_enabled(root, True)

    @contextmanager
    def _delete_before_lock(_root: Path):
        shutil.rmtree(home)
        yield

    monkeypatch.setattr(security_cli, "control_lock", _delete_before_lock)
    monkeypatch.setattr(
        security_cli,
        "SecurityService",
        lambda: pytest.fail("deleted profile must not materialize Security Center"),
    )

    result = resume_watch_if_enabled(home)

    assert result == {"ok": True, "enabled": False, "pid": None, "running": False}
    assert not home.exists()


def test_startup_resume_covers_default_and_named_profiles(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    from hermes_cli import profiles

    homes = {
        "default": tmp_path / "default",
        "research": tmp_path / "profiles" / "research",
    }
    for home in homes.values():
        security = home / "security"
        security.mkdir(parents=True)
        (security / "watch-state.json").write_text("{}", encoding="utf-8")
    resume = Mock(return_value={"ok": True, "enabled": True, "pid": 7, "running": True})
    monkeypatch.setattr(profiles, "list_profile_names", lambda: ["default", "research"])
    monkeypatch.setattr(profiles, "get_profile_dir", lambda name: homes[name])
    monkeypatch.setattr(security_cli, "resume_watch_if_enabled", resume)

    results = security_cli.resume_all_profile_watches()

    assert [result["profile"] for result in results] == ["default", "research"]
    assert resume.call_args_list == [call(homes["default"]), call(homes["research"])]


def test_watcher_claims_owner_before_initial_inventory(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    calls: list[str] = []

    @contextmanager
    def _runtime_lock(_root: Path):
        yield True

    class _Service:
        store = WatchStoreStub(tmp_path / "security")

    monkeypatch.setattr(security_watcher, "get_hermes_home", lambda: tmp_path)
    monkeypatch.setattr(security_watcher, "runtime_lock", _runtime_lock)
    monkeypatch.setattr(security_watcher, "SecurityService", _Service)
    monkeypatch.setattr(
        security_watcher,
        "claim_watch_owner",
        lambda _root, _request, _owner: calls.append("claim") or {"enabled": True},
    )
    monkeypatch.setattr(
        security_watcher,
        "reconcile_once",
        lambda *_args, **_kwargs: calls.append("inventory") or (_ for _ in ()).throw(RuntimeError("stop")),
    )
    monkeypatch.setattr(
        security_watcher,
        "clear_watch_owner",
        lambda _root, _request, _owner: calls.append("clear") or True,
    )
    monkeypatch.setattr(security_watcher.psutil, "Process", lambda: SimpleNamespace(nice=Mock()))
    monkeypatch.setattr(security_watcher.signal, "signal", Mock())

    with pytest.raises(RuntimeError, match="stop"):
        security_watcher.run(30, "1" * 32, "2" * 32)

    assert calls == ["claim", "inventory", "clear"]


def test_watcher_reconciles_new_and_changed_files_once(tmp_path: Path) -> None:
    existing = tmp_path / "existing.txt"
    existing.write_text("baseline", encoding="utf-8")
    service = ReconcileServiceStub(tmp_path)
    typed_service = cast(SecurityService, service)
    seen = reconcile_once(typed_service, {}, scan_changes=False)
    service.scan_file.assert_not_called()
    target = tmp_path / "watched.txt"
    target.write_text("first", encoding="utf-8")
    seen = reconcile_once(typed_service, seen)
    service.scan_file.assert_called_once_with(target)
    service.scan_file.reset_mock()
    seen = reconcile_once(typed_service, seen)
    service.scan_file.assert_not_called()
    target.write_text("changed-content", encoding="utf-8")
    reconcile_once(typed_service, seen)
    service.scan_file.assert_called_once_with(target)


def test_definition_update_retains_current_on_validation_failure(tmp_path: Path) -> None:
    store = SecurityStore(tmp_path / "security")
    updater = DefinitionUpdater(store)
    current = updater.root / "current"
    current.mkdir()
    (current / "daily.cvd").write_bytes(b"old" * 300)

    def fake_run(arguments, **_kwargs):
        staging = Path(next(item.split("=", 1)[1] for item in arguments if item.startswith("--datadir=")))
        (staging / "daily.cvd").write_bytes(b"bad")
        return SimpleNamespace(returncode=0, stdout="updated", stderr="")

    with patch("downstream.security.updates.shutil.which", return_value="freshclam"), patch(
        "downstream.security.updates.subprocess.run", side_effect=fake_run
    ):
        result = updater.update_clamav()
    assert result["ok"] is False
    assert (current / "daily.cvd").read_bytes() == b"old" * 300


def test_clamscan_uses_managed_database_and_bounded_process(tmp_path: Path) -> None:
    target = tmp_path / "fixture.bin"
    target.write_bytes(b"fixture")
    database = tmp_path / "database"
    database.mkdir()
    (database / "main.cvd").write_bytes(b"managed database fixture")
    commands = {"clamscan": "C:/ClamAV/clamscan.exe"}
    bounded_run = Mock(
        return_value=SimpleNamespace(
            returncode=1,
            stdout=f"{target}: Hermes.Test FOUND",
            stderr="",
            output_truncated=False,
        )
    )
    with patch("downstream.security.engines.shutil.which", side_effect=lambda name: commands.get(name)), patch(
        "downstream.security.engines.run_bounded", bounded_run
    ):
        findings = ClamAVEngine(database_dir=database).scan(target, hashlib.sha256(target.read_bytes()).hexdigest())
    assert findings[0].score == 90
    assert bounded_run.call_count == 1
    assert bounded_run.call_args.args[0][:2] == [commands["clamscan"], f"--database={database}"]


def test_explicit_clamav_database_never_falls_back_to_environment(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    managed = tmp_path / "selected-profile" / "feeds" / "clamav" / "current"
    other_profile = tmp_path / "other-profile" / "feeds" / "clamav" / "current"
    other_profile.mkdir(parents=True)
    monkeypatch.setenv("CLAMAV_DATABASE_DIR", str(other_profile))

    engine = ClamAVEngine(database_dir=managed)

    assert engine.database_dir == managed


def test_quarantine_tamper_is_rejected_and_metadata_is_complete(tmp_path: Path) -> None:
    target = tmp_path / "tamper.bin"
    target.write_bytes(EICAR)
    service = service_for(tmp_path, DetectionEngine())
    result = service.scan_file(target)
    item = service.vault.inspect(str(result.quarantine_id))
    assert item["original_filename"] == target.name
    assert json.loads(str(item["engine_versions_json"]))["clamav"] == "test-signatures-1"
    blob = service.vault.root / str(item["blob_name"])
    payload = bytearray(blob.read_bytes())
    payload[-1] ^= 1
    blob.write_bytes(payload)
    with pytest.raises(InvalidTag):
        service.vault.restore(str(result.quarantine_id), lambda path: service.scan_file(path, quarantine=False))
    assert not target.exists()


def test_existing_security_database_is_migrated_in_place(tmp_path: Path) -> None:
    root = tmp_path / "security"
    root.mkdir()
    database = root / "security.db"
    with sqlite3.connect(database) as con:
        con.execute("CREATE TABLE malware_hashes (sha256 TEXT PRIMARY KEY, label TEXT NOT NULL, source TEXT NOT NULL, feed_version TEXT NOT NULL, updated_at TEXT NOT NULL)")
        con.execute("CREATE TABLE quarantine_items (id TEXT PRIMARY KEY, blob_name TEXT NOT NULL UNIQUE, original_path TEXT NOT NULL, sha256 TEXT NOT NULL, size INTEGER NOT NULL, verdict TEXT NOT NULL, findings_json TEXT NOT NULL, created_at TEXT NOT NULL, restored_at TEXT, deleted_at TEXT)")
        con.execute("CREATE TABLE allowlist (kind TEXT NOT NULL, value TEXT NOT NULL, reason TEXT NOT NULL, created_at TEXT NOT NULL, PRIMARY KEY(kind, value))")
    store = SecurityStore(root)
    with store.connection() as con:
        hash_columns = {row[1] for row in con.execute("PRAGMA table_info(malware_hashes)")}
        quarantine_columns = {row[1] for row in con.execute("PRAGMA table_info(quarantine_items)")}
        allowlist_columns = {row[1] for row in con.execute("PRAGMA table_info(allowlist)")}
    assert {"malware_family", "confidence", "first_seen", "last_seen"} <= hash_columns
    assert {"original_filename", "engine_versions_json", "restore_state"} <= quarantine_columns
    assert {"created_by", "expires_at"} <= allowlist_columns


@pytest.mark.windows_only
def test_vault_key_acl_is_limited_to_owner_and_system(tmp_path: Path) -> None:
    win32api = importlib.import_module("win32api")
    win32con = importlib.import_module("win32con")
    win32security = importlib.import_module("win32security")

    service = service_for(tmp_path, CleanEngine())
    descriptor = win32security.GetFileSecurity(
        str(service.vault.root.parent / "vault-key.dpapi"),
        win32security.DACL_SECURITY_INFORMATION,
    )
    acl = descriptor.GetSecurityDescriptorDacl()
    sids = {win32security.ConvertSidToStringSid(acl.GetAce(index)[2]) for index in range(acl.GetAceCount())}
    owner = win32security.GetTokenInformation(
        win32security.OpenProcessToken(win32api.GetCurrentProcess(), win32con.TOKEN_QUERY),
        win32security.TokenUser,
    )[0]
    system = win32security.CreateWellKnownSid(win32security.WinLocalSystemSid, None)
    assert sids == {win32security.ConvertSidToStringSid(owner), win32security.ConvertSidToStringSid(system)}


@pytest.mark.windows_only
def test_real_clamav_detects_eicar_when_required(tmp_path: Path) -> None:
    command = shutil.which("clamscan")
    database_value = os.environ.get("CLAMAV_DATABASE_DIR")
    if not command and os.environ.get("HERMES_REQUIRE_CLAMAV") == "1":
        pytest.fail("HERMES_REQUIRE_CLAMAV=1 but clamscan is unavailable")
    if not command:
        pytest.skip("clamscan is not installed on this workstation")
    if not database_value:
        if os.environ.get("HERMES_REQUIRE_CLAMAV") == "1":
            pytest.fail("HERMES_REQUIRE_CLAMAV=1 but no managed ClamAV database is configured")
        pytest.skip("managed ClamAV definitions are not configured")
    database = Path(database_value)
    try:
        inventory_clamav_definitions(database)
    except DefinitionInventoryError as exc:
        if os.environ.get("HERMES_REQUIRE_CLAMAV") == "1":
            pytest.fail(f"managed ClamAV database is not valid: {exc.reason}")
        pytest.skip("managed ClamAV definitions are not valid")
    target = tmp_path / "eicar.com"
    target.write_bytes(EICAR)
    findings = ClamAVEngine(timeout=60, database_dir=database).scan(target, hashlib.sha256(EICAR).hexdigest())
    assert any(finding.score == 90 for finding in findings)
    clean = tmp_path / "clean.txt"
    clean.write_text("Hermes harmless negative control", encoding="utf-8")
    clean_findings = ClamAVEngine(timeout=60, database_dir=database).scan(clean, hashlib.sha256(clean.read_bytes()).hexdigest())
    assert all(finding.score == 0 for finding in clean_findings)


def test_bundled_yara_core_detects_eicar(tmp_path: Path) -> None:
    target = tmp_path / "eicar.com"
    target.write_bytes(EICAR)
    rules = Path(__file__).parents[2] / "downstream" / "security" / "rules"
    findings = YaraEngine(rules).scan(target, hashlib.sha256(EICAR).hexdigest())
    assert any(finding.name == "Hermes_EICAR_Antivirus_Test_File" and finding.score == 80 for finding in findings)
