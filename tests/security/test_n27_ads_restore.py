from __future__ import annotations

import sys
import sqlite3
from contextlib import contextmanager
from pathlib import Path

import pytest

from downstream.security.models import Finding
from downstream.security.service import SecurityService
from downstream.security.store import SecurityStore
from downstream.security.vault import QuarantineVault, VaultKey


pytestmark = pytest.mark.skipif(sys.platform != "win32", reason="NTFS ADS native contract")


def _quarantined_ads(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    base = tmp_path / "inert-ads-restore-base.bin"
    base_bytes = b"ordinary inert base"
    stream_bytes = b"distinct inert stream"
    base.write_bytes(base_bytes)
    stream = Path(f"{base}:detected")
    try:
        stream.write_bytes(stream_bytes)
    except OSError as exc:
        pytest.skip(f"BLOCKED_NATIVE_PATH: ADS creation denied: {type(exc).__name__}")
    monkeypatch.setattr(VaultKey, "load_or_create", lambda _self: b"\x27" * 32)
    service = SecurityService(
        SecurityStore(tmp_path / "security"),
        {"security": {"malware": {"auto_quarantine": True}}},
    )

    class DetectionEngine:
        name = "yara"

        def version(self) -> str:
            return "inert-ads-restore-fixture-1"

        def scan(self, _path: Path, _sha256: str) -> list[Finding]:
            return [Finding(self.name, "synthetic-inert-detection", 90)]

    service.engines = (DetectionEngine(),)
    result = service.scan_file(stream, use_cache=False)
    assert result.action == "quarantined"
    assert not stream.exists()
    assert base.read_bytes() == base_bytes
    return service, base, stream, base_bytes, stream_bytes, str(result.quarantine_id)


def _rescan(service: SecurityService):
    return lambda path: service.scan_file(path, quarantine=False, use_cache=False)


def test_native_ads_restore_preserves_base_and_records_stream(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    service, base, stream, base_bytes, stream_bytes, item_id = _quarantined_ads(monkeypatch, tmp_path)
    before = base.stat()

    restored = service.vault.restore(item_id, _rescan(service), destination=stream, force=True)

    assert restored == stream
    assert stream.read_bytes() == stream_bytes
    assert base.read_bytes() == base_bytes
    assert base.stat().st_ino == before.st_ino
    assert base.stat().st_size == before.st_size
    assert base.stat().st_ctime_ns == before.st_ctime_ns
    item = service.vault.inspect(item_id)
    assert item["restore_state"] == "restored"
    assert item["restored_at"] is not None
    assert item["restore_target"] == str(stream)


def test_native_ads_restore_refuses_existing_stream_without_changing_blob(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    service, base, stream, base_bytes, _, item_id = _quarantined_ads(monkeypatch, tmp_path)
    stream.write_bytes(b"replacement stream")

    with pytest.raises(FileExistsError):
        service.vault.restore(item_id, _rescan(service), destination=stream, force=True)

    assert base.read_bytes() == base_bytes
    assert stream.read_bytes() == b"replacement stream"
    item = service.vault.inspect(item_id)
    assert item["restore_state"] == "quarantined"
    assert item["blob_present"] is True
    assert item["restore_target"] is None


def test_native_ads_restore_create_new_refuses_a_racing_stream(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    import win32file

    service, base, stream, base_bytes, _, item_id = _quarantined_ads(monkeypatch, tmp_path)
    real_create = win32file.CreateFile
    raced = False

    def create_after_race(path: str, *args: object):
        nonlocal raced
        if str(path) == str(stream) and not raced:
            raced = True
            stream.write_bytes(b"racing replacement")
        return real_create(path, *args)

    monkeypatch.setattr(win32file, "CreateFile", create_after_race)
    with pytest.raises(FileExistsError):
        service.vault.restore(item_id, _rescan(service), destination=stream, force=True)

    assert raced
    assert base.read_bytes() == base_bytes
    assert stream.read_bytes() == b"racing replacement"
    item = service.vault.inspect(item_id)
    assert item["restore_state"] == "quarantined"
    assert item["blob_present"] is True
    assert item["restore_target"] is None


def test_native_ads_restore_write_failure_keeps_blob_and_removes_owned_partial_stream(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    import win32file

    service, base, stream, base_bytes, _, item_id = _quarantined_ads(monkeypatch, tmp_path)
    real_write = win32file.WriteFile

    def fail_after_prefix(handle: object, data: bytes):
        real_write(handle, data[:3])
        raise OSError("synthetic ADS write failure")

    monkeypatch.setattr(win32file, "WriteFile", fail_after_prefix)
    with pytest.raises(OSError, match="synthetic ADS write failure"):
        service.vault.restore(item_id, _rescan(service), destination=stream, force=True)

    assert base.read_bytes() == base_bytes
    assert not stream.exists()
    item = service.vault.inspect(item_id)
    assert item["restore_state"] == "quarantined"
    assert item["blob_present"] is True


@pytest.mark.asyncio
async def test_native_ads_restore_uses_the_confirmed_api_caller(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    from hermes_cli import web_server

    service, base, stream, base_bytes, stream_bytes, item_id = _quarantined_ads(monkeypatch, tmp_path)
    monkeypatch.setattr(
        web_server, "_call_security_for_profile", lambda _profile, operation: operation(service),
    )

    response = await web_server.security_quarantine_restore(
        item_id,
        web_server.SecurityRestoreRequest(destination=str(stream), force=True, confirmed=True),
    )

    assert response == {"ok": True, "path": str(stream.resolve())}
    assert stream.read_bytes() == stream_bytes
    assert base.read_bytes() == base_bytes
    assert service.vault.inspect(item_id)["restore_state"] == "restored"


def test_native_ads_restore_cleanup_failure_stays_pending_and_retains_blob(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    import win32file

    service, base, stream, base_bytes, stream_bytes, item_id = _quarantined_ads(monkeypatch, tmp_path)
    real_write = win32file.WriteFile

    def fail_after_prefix(handle: object, data: bytes):
        real_write(handle, data[:3])
        raise OSError("synthetic ADS write failure")

    def fail_cleanup(*_args: object):
        raise OSError("synthetic ADS cleanup failure")

    monkeypatch.setattr(win32file, "WriteFile", fail_after_prefix)
    monkeypatch.setattr(win32file, "SetFileInformationByHandle", fail_cleanup)
    with pytest.raises(RuntimeError, match="outcome unknown"):
        service.vault.restore(item_id, _rescan(service), destination=stream, force=True)

    assert base.read_bytes() == base_bytes
    assert stream.read_bytes() == stream_bytes[:3]
    item = service.vault.inspect(item_id)
    assert item["restore_state"] == "pending_restore_outcome"
    assert item["blob_present"] is True
    assert item["restore_target"] == str(stream)
    assert service.store.status_summary()["quarantine_pending_count"] == 1
    reopened = QuarantineVault(SecurityStore(tmp_path / "security", read_only=True), read_only=True)
    assert reopened.inspect(item_id)["restore_state"] == "pending_restore_outcome"
    assert reopened.inspect(item_id)["restore_target"] == str(stream)
    with pytest.raises(ValueError, match="pending"):
        service.vault.restore(item_id, _rescan(service), destination=stream, force=True)
    with pytest.raises(ValueError, match="pending"):
        service.vault.delete(item_id)


def test_native_ads_restore_final_db_failure_stays_pending_after_landed_stream(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    service, base, stream, base_bytes, stream_bytes, item_id = _quarantined_ads(monkeypatch, tmp_path)
    intended_base = tmp_path / "inert-intended-base.bin"
    intended_base.write_bytes(b"other inert base")
    destination = Path(f"{intended_base}:recovered")
    real_connection = service.store.connection

    @contextmanager
    def fail_final_record():
        with real_connection() as connection:
            class ConnectionProxy:
                def execute(self, sql: str, *args: object):
                    if "UPDATE quarantine_items SET restored_at" in sql:
                        raise sqlite3.OperationalError("synthetic final record failure")
                    return connection.execute(sql, *args)

            yield ConnectionProxy()

    monkeypatch.setattr(service.store, "connection", fail_final_record)
    with pytest.raises(sqlite3.OperationalError, match="synthetic final record failure"):
        service.vault.restore(item_id, _rescan(service), destination=destination, force=True)
    monkeypatch.setattr(service.store, "connection", real_connection)

    assert base.read_bytes() == base_bytes
    assert not stream.exists()
    assert intended_base.read_bytes() == b"other inert base"
    assert destination.read_bytes() == stream_bytes
    item = service.vault.inspect(item_id)
    assert item["restore_state"] == "pending_restore_outcome"
    assert item["blob_present"] is True
    assert item["restore_target"] == str(destination)
    reopened = QuarantineVault(SecurityStore(tmp_path / "security", read_only=True), read_only=True)
    assert reopened.inspect(item_id)["restore_state"] == "pending_restore_outcome"
    assert reopened.inspect(item_id)["restore_target"] == str(destination)


def test_delete_rechecks_pending_restore_after_a_stale_client_read(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    service, _, _, _, _, item_id = _quarantined_ads(monkeypatch, tmp_path)
    assert service.vault.inspect(item_id)["restore_state"] == "quarantined"
    with service.store.connection() as connection:
        connection.execute(
            "UPDATE quarantine_items SET restore_state='pending_restore_outcome' WHERE id=?",
            (item_id,),
        )
    with pytest.raises(ValueError, match="pending"):
        service.vault.delete(item_id)
    item = service.vault.inspect(item_id)
    assert item["restore_state"] == "pending_restore_outcome"
    assert item["blob_present"] is True


def test_delete_rejects_corrupt_quarantine_evidence_before_unlink(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    service, _, _, _, _, item_id = _quarantined_ads(monkeypatch, tmp_path)
    blob_name = str(service.vault.inspect(item_id)["blob_name"])
    blob = service.vault.root / blob_name
    with service.store.connection() as connection:
        connection.execute(
            "UPDATE quarantine_items SET findings_json='not-json' WHERE id=?", (item_id,),
        )

    with pytest.raises(sqlite3.DatabaseError, match="invalid quarantine findings"):
        service.vault.delete(item_id)

    assert blob.is_file()
    with service.store.connection() as connection:
        row = connection.execute(
            "SELECT restore_state,deleted_at FROM quarantine_items WHERE id=?", (item_id,),
        ).fetchone()
    assert row is not None and row["restore_state"] == "quarantined"
    assert row["deleted_at"] is None
