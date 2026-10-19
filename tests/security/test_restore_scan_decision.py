"""Restoration observes the existing scan decision on real inert vault data."""
from __future__ import annotations

import asyncio
import hashlib
from pathlib import Path
from argparse import Namespace

import pytest
from cryptography.exceptions import InvalidTag

from downstream.security.engines import HashReputationEngine
from downstream.security.models import EngineState, ExecutionDecision, Finding
from downstream.security.service import SecurityService
from downstream.security.store import SecurityStore


PAYLOAD = b"Hermes inert quarantine roundtrip fixture\x00\xff"


class FixtureEngine:
    name = "yara"

    def __init__(self, findings: tuple[Finding, ...]):
        self.findings = findings

    def version(self) -> str:
        return "owned-inert-fixture-1"

    def scan(self, path: Path, _sha256: str) -> list[Finding]:
        assert path.read_bytes() == PAYLOAD
        return list(self.findings)


@pytest.fixture
def quarantined(tmp_path):
    source = tmp_path / "original 日本語.bin"
    source.write_bytes(PAYLOAD)
    service = SecurityService(SecurityStore(tmp_path / "security"),
                              {"security": {"malware": {"auto_quarantine": True}}})
    sha256 = hashlib.sha256(PAYLOAD).hexdigest()
    service.store.upsert_malware_hash(sha256, source="owned-test", malware_family="inert-fixture",
                                     confidence=100, feed_version="fixture-1")
    service.engines = (HashReputationEngine(service.store),)
    result = service.scan_file(source)
    assert result.action == "quarantined" and result.quarantine_id
    assert not source.exists()
    item = service.vault.inspect(result.quarantine_id)
    blob = service.vault.root / str(item["blob_name"])
    encrypted = blob.read_bytes()
    assert encrypted.startswith(b"HERMESQ1") and PAYLOAD not in encrypted
    return service, source, result.quarantine_id, blob, encrypted


REVIEW_FINDINGS = [
    (),
    (Finding("yara", "unavailable", 0, EngineState.SCANNER_UNAVAILABLE),),
    (Finding("yara", "timeout", 0, EngineState.SCAN_TIMEOUT),),
    (Finding("yara", "stale", 0, EngineState.DATABASE_STALE),),
    (Finding("yara", "database-error", 0, EngineState.DATABASE_ERROR),),
    (Finding("yara", "engine-error", 0, EngineState.ENGINE_ERROR),),
    (Finding("yara", "suspicious", 40), Finding("clamav", "timeout", 0, EngineState.SCAN_TIMEOUT)),
]


@pytest.mark.parametrize("findings", REVIEW_FINDINGS,
                         ids=["unknown", "unavailable", "timeout", "stale", "database-error",
                              "engine-error", "suspicious-with-error"])
@pytest.mark.parametrize("force", [False, True], ids=["normal", "force"])
def test_restore_requires_review_when_rescan_requires_review(quarantined, findings, force):
    service, source, item_id, blob, encrypted = quarantined
    service.engines = (FixtureEngine(findings),)
    seen = []

    def rescan(path):
        result = service.scan_file(path, quarantine=False, use_cache=False)
        seen.append(result)
        assert result.execution_decision == ExecutionDecision.REVIEW
        return result

    with pytest.raises(PermissionError, match="review"):
        service.vault.restore(item_id, rescan, force=force)
    assert len(seen) == 1
    assert not source.exists() and blob.read_bytes() == encrypted
    assert not list(source.parent.glob(".hermes-restore-*"))
    item = service.vault.inspect(item_id)
    assert item["restored_at"] is None
    assert not any(row["event_type"] == "restore" for row in service.store.status_rows("detection_events", 100))


@pytest.mark.parametrize("score, decision", [(0, ExecutionDecision.ALLOW), (40, ExecutionDecision.WARN)])
def test_restore_preserves_successful_clean_and_warning_decisions(quarantined, score, decision):
    service, source, item_id, blob, encrypted = quarantined
    service.engines = (FixtureEngine((Finding("yara", "fixture-verdict", score),)),)

    def rescan(path):
        result = service.scan_file(path, quarantine=False, use_cache=False)
        assert result.execution_decision == decision
        return result

    restored = service.vault.restore(item_id, rescan)
    assert restored == source and source.read_bytes() == PAYLOAD
    assert blob.read_bytes() == encrypted
    assert service.vault.inspect(item_id)["restore_state"] == "restored"
    assert not list(source.parent.glob(".hermes-restore-*"))


@pytest.mark.parametrize("allowlisted", [False, True], ids=["detected", "allowlisted-detected"])
def test_restore_preserves_explicit_force_and_never_overwrites(quarantined, allowlisted):
    service, source, item_id, blob, encrypted = quarantined
    if allowlisted:
        with service.store.connection() as connection:
            connection.execute(
                "INSERT INTO allowlist(kind,value,reason,created_by,created_at) "
                "VALUES('sha256',?,'owned test','test',datetime('now'))",
                (hashlib.sha256(PAYLOAD).hexdigest(),))
    service.engines = (FixtureEngine((Finding("yara", "still-detected", 90),)),)

    def rescan(path):
        result = service.scan_file(path, quarantine=False, use_cache=False)
        assert result.action == ("allowlisted" if allowlisted else "quarantine")
        return result

    source.write_bytes(b"existing user data")
    with pytest.raises(FileExistsError):
        service.vault.restore(item_id, rescan, force=True)
    assert source.read_bytes() == b"existing user data"
    source.unlink()
    with pytest.raises(PermissionError, match="malicious"):
        service.vault.restore(item_id, rescan)
    assert not source.exists()
    assert service.vault.restore(item_id, rescan, force=True).read_bytes() == PAYLOAD
    assert blob.read_bytes() == encrypted


def test_restore_force_cannot_bypass_tampered_blob(quarantined):
    service, source, item_id, blob, encrypted = quarantined
    blob.write_bytes(encrypted[:-1] + bytes([encrypted[-1] ^ 1]))
    with pytest.raises(InvalidTag):
        service.vault.restore(item_id, lambda _path: pytest.fail("Unauthenticated bytes reached rescan"), force=True)
    assert not source.exists()
    assert service.vault.inspect(item_id)["restored_at"] is None


def test_restore_force_cannot_bypass_deleted_item(quarantined):
    service, source, item_id, _blob, _encrypted = quarantined
    service.vault.delete(item_id)
    with pytest.raises(ValueError, match="deleted"):
        service.vault.restore(item_id, lambda _path: pytest.fail("Deleted item reached rescan"), force=True)
    assert not source.exists()


def test_restore_rescan_exception_removes_temporary_and_preserves_vault(quarantined):
    service, source, item_id, blob, encrypted = quarantined

    def failed_rescan(_path):
        raise RuntimeError("owned scanner failure")

    with pytest.raises(RuntimeError, match="owned scanner failure"):
        service.vault.restore(item_id, failed_rescan, force=True)
    assert not source.exists() and blob.read_bytes() == encrypted
    assert not list(source.parent.glob(".hermes-restore-*"))
    assert service.vault.inspect(item_id)["restored_at"] is None


def test_restore_cli_returns_error_and_can_retry_after_recovery(quarantined, monkeypatch, capsys):
    from downstream.security import cli

    service, source, item_id, blob, encrypted = quarantined
    service.engines = (FixtureEngine((Finding("yara", "timeout", 0, EngineState.SCAN_TIMEOUT),)),)
    monkeypatch.setattr(cli, "SecurityService", lambda: service)
    args = Namespace(security_command="quarantine", quarantine_command="restore",
                     item_id=item_id, destination=None, force=True, json=True)
    assert cli.command(args) == 2
    assert '"ok": false' in capsys.readouterr().out
    assert not source.exists() and blob.read_bytes() == encrypted
    service.engines = (FixtureEngine((Finding("yara", "no-detection", 0),)),)
    assert cli.command(args) == 0
    assert '"ok": true' in capsys.readouterr().out
    assert source.read_bytes() == PAYLOAD


def test_restore_api_reports_review_failure_and_can_retry_after_recovery(quarantined, monkeypatch):
    from hermes_cli import web_server

    service, source, item_id, blob, encrypted = quarantined
    service.engines = (FixtureEngine((Finding("yara", "unavailable", 0, EngineState.SCANNER_UNAVAILABLE),)),)
    # Profile dispatch is outside this test's scope; real service/vault/scan remain.
    monkeypatch.setattr(web_server, "_security_service", lambda **_kwargs: service)
    with pytest.raises(web_server.HTTPException) as unconfirmed:
        asyncio.run(web_server.security_quarantine_restore(item_id, web_server.SecurityRestoreRequest()))
    assert unconfirmed.value.status_code == 409
    with pytest.raises(web_server.HTTPException) as review:
        asyncio.run(web_server.security_quarantine_restore(
            item_id, web_server.SecurityRestoreRequest(confirmed=True)))
    assert review.value.status_code == 409 and "review" in review.value.detail
    assert not source.exists() and blob.read_bytes() == encrypted
    service.engines = (FixtureEngine((Finding("yara", "no-detection", 0),)),)
    response = asyncio.run(web_server.security_quarantine_restore(
        item_id, web_server.SecurityRestoreRequest(confirmed=True)))
    assert response == {"ok": True, "path": str(source)}
    assert source.read_bytes() == PAYLOAD
