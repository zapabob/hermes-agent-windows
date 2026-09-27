"""N26: a disposition error must retain a recoverable, visibly pending vault row."""
from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from downstream.security.models import ScanResult, Verdict
from downstream.security.store import SecurityStore
from downstream.security.vault import QuarantineVault, VaultKey


@pytest.mark.windows_only
def test_native_disposition_completes_before_vault_row_is_quarantined(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(VaultKey, "load_or_create", lambda _self: b"\x07" * 32)
    store = SecurityStore(tmp_path / "security")
    vault = QuarantineVault(store)
    source = tmp_path / "inert-quarantine-success.bin"
    payload = b"inert quarantine success fixture"
    source.write_bytes(payload)
    result = ScanResult(str(source), hashlib.sha256(payload).hexdigest(), len(payload),
                        Verdict.MALICIOUS, 90, "quarantine", (), {})

    item_id = vault.quarantine(source, result)

    assert not source.exists()
    item = vault.inspect(item_id)
    assert item["restore_state"] == "quarantined"
    assert item["blob_present"] is True
    assert vault._decrypt(vault.root / item["blob_name"], result.sha256) == payload
    assert store.status_summary()["quarantine_count"] == 1
    assert store.status_summary()["quarantine_pending_count"] == 0


@pytest.mark.windows_only
@pytest.mark.parametrize("landed", [False, True], ids=["refused", "landed_then_raised"])
def test_disposition_error_keeps_pending_blob_and_source_outcome(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, landed: bool,
) -> None:
    import win32file

    # Exercise the native held-handle and ACL path without requiring DPAPI setup.
    monkeypatch.setattr(VaultKey, "load_or_create", lambda _self: b"\x07" * 32)
    store = SecurityStore(tmp_path / "security")
    vault = QuarantineVault(store)
    source = tmp_path / "inert-quarantine.bin"
    payload = b"inert quarantine disposition fixture"
    source.write_bytes(payload)
    result = ScanResult(str(source), hashlib.sha256(payload).hexdigest(), len(payload),
                        Verdict.MALICIOUS, 90, "quarantine", (), {})
    real_disposition = win32file.SetFileInformationByHandle
    observed_states = []

    def uncertain_disposition(handle, info, value):
        with store.connection() as con:
            observed_states.append(con.execute(
                "SELECT restore_state FROM quarantine_items"
            ).fetchone()[0])
        if landed:
            real_disposition(handle, info, value)
        raise OSError("synthetic acknowledgement loss")

    monkeypatch.setattr(win32file, "SetFileInformationByHandle", uncertain_disposition)
    with pytest.raises(OSError, match="acknowledgement loss"):
        vault.quarantine(source, result)

    assert observed_states == ["pending_source_disposition"]
    with store.connection() as con:
        row = con.execute("SELECT id, restore_state FROM quarantine_items").fetchone()
    assert row is not None and row["restore_state"] == "pending_source_disposition"
    item = vault.inspect(row["id"])
    assert item["blob_present"] is True
    assert vault._decrypt(vault.root / item["blob_name"], result.sha256) == payload
    assert store.status_summary()["quarantine_count"] == 0
    assert store.status_summary()["quarantine_pending_count"] == 1
    assert source.exists() is not landed
    if not landed:
        assert source.read_bytes() == payload
    with pytest.raises(ValueError, match="pending"):
        vault.delete(row["id"])
    with pytest.raises(ValueError, match="pending"):
        vault.restore(row["id"], lambda _path: result)
