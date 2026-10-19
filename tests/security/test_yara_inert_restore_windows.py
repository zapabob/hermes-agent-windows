"""Real installed YARA and Windows vault roundtrip using only inert bytes."""
import hashlib
import importlib.metadata
from pathlib import Path
import sys

import pytest
from cryptography.exceptions import InvalidTag

from downstream.security.engines import YaraEngine
from downstream.security.models import EngineHealth, ExecutionDecision, Verdict
from downstream.security.service import SecurityService
from downstream.security.store import SecurityStore


pytestmark = [pytest.mark.windows_only,
              pytest.mark.skipif(sys.platform != "win32", reason="Native Windows YARA/vault qualification")]
INERT = b"Hermes owned inert YARA restore fixture 6f24a8a2\x00\xff"
RULE = '''rule Hermes_Owned_Inert_Fixture {
    meta:
        hermes_tier = "core"
    strings:
        $owned = "Hermes owned inert YARA restore fixture 6f24a8a2"
    condition:
        $owned at 0
}
'''
RECOVERED_RULE = RULE.replace("6f24a8a2", "no-longer-matches")


def real_service(tmp_path: Path, record_property):
    import yara
    record_property("yara_version", importlib.metadata.version("yara-python"))
    record_property("yara_binary_sha256", hashlib.sha256(Path(yara.__file__).read_bytes()).hexdigest())
    store = SecurityStore(tmp_path / "security")
    rules = store.root / "feeds" / "yara"
    rules.mkdir(parents=True)
    rule = rules / "owned-inert.yar"
    rule.write_text(RULE, encoding="utf-8")
    service = SecurityService(store, {"security": {"malware": {"auto_quarantine": True}}})
    # Deliberately qualify this real detector, without claiming ClamAV coverage.
    service.engines = (YaraEngine(rules),)
    return service, rule


def test_real_yara_clean_detection_quarantine_and_current_rescan_recovery(tmp_path, record_property):
    service, rule = real_service(tmp_path, record_property)
    clean = tmp_path / "clean 日本語.txt"
    clean.write_bytes(b"Owned harmless negative control")
    negative = service.scan_file(clean, quarantine=True)
    assert negative.verdict == Verdict.CLEAN, (negative.error, negative.findings)
    assert negative.engine_health == EngineHealth.HEALTHY
    assert negative.execution_decision == ExecutionDecision.ALLOW
    assert clean.read_bytes() == b"Owned harmless negative control"
    source = tmp_path / "inert 日本語.bin"
    source.write_bytes(INERT)
    detected = service.scan_file(source)
    assert detected.verdict == Verdict.MALICIOUS and detected.action == "quarantined"
    assert detected.engine_health == EngineHealth.HEALTHY
    assert detected.execution_decision == ExecutionDecision.BLOCK
    assert any(row.name == "Hermes_Owned_Inert_Fixture" for row in detected.findings)
    assert not source.exists()
    item = service.vault.inspect(detected.quarantine_id)
    blob = service.vault.root / item["blob_name"]
    ciphertext = blob.read_bytes()
    assert ciphertext.startswith(b"HERMESQ1") and INERT not in ciphertext
    assert item["sha256"] == hashlib.sha256(INERT).hexdigest()
    scans = []

    def current_rescan(path):
        result = service.scan_file(path, quarantine=False, use_cache=False)
        scans.append(result)
        return result

    with pytest.raises(PermissionError, match="malicious"):
        service.vault.restore(detected.quarantine_id, current_rescan)
    assert scans[-1].verdict == Verdict.MALICIOUS and not scans[-1].cached
    rule.write_text("rule broken { condition: syntax is invalid }", encoding="utf-8")
    with pytest.raises(PermissionError, match="review"):
        service.vault.restore(detected.quarantine_id, current_rescan, force=True)
    assert scans[-1].verdict == Verdict.SCAN_ERROR
    assert scans[-1].execution_decision == ExecutionDecision.REVIEW
    assert scans[-1].engine_health == EngineHealth.ERROR
    assert not source.exists() and blob.read_bytes() == ciphertext
    assert service.vault.inspect(detected.quarantine_id)["restored_at"] is None
    rule.write_text(RECOVERED_RULE, encoding="utf-8")
    restored = service.vault.restore(detected.quarantine_id, current_rescan)
    assert scans[-1].verdict == Verdict.CLEAN and not scans[-1].cached
    assert scans[-1].engine_health == EngineHealth.HEALTHY
    assert restored == source and source.read_bytes() == INERT
    assert service.vault.inspect(detected.quarantine_id)["restore_state"] == "restored"
    assert blob.read_bytes() == ciphertext
    assert not list(tmp_path.glob(".hermes-restore-*"))


def test_real_yara_force_preserves_authenticated_bytes_and_existing_destination(tmp_path, record_property):
    service, _rule = real_service(tmp_path, record_property)
    source = tmp_path / "inert.bin"
    source.write_bytes(INERT)
    detected = service.scan_file(source)
    assert detected.action == "quarantined"
    destination = tmp_path / "requested destination.bin"
    destination.write_bytes(b"existing user data")
    scan = lambda path: service.scan_file(path, quarantine=False, use_cache=False)
    with pytest.raises(FileExistsError):
        service.vault.restore(detected.quarantine_id, scan, destination, force=True)
    assert destination.read_bytes() == b"existing user data" and not source.exists()
    restored = service.vault.restore(detected.quarantine_id, scan, force=True)
    assert restored == source and source.read_bytes() == INERT


def test_real_yara_cannot_restore_tampered_vault_even_with_force(tmp_path, record_property):
    service, rule = real_service(tmp_path, record_property)
    source = tmp_path / "tamper-control.bin"
    source.write_bytes(INERT)
    detected = service.scan_file(source)
    assert detected.action == "quarantined"
    item = service.vault.inspect(detected.quarantine_id)
    blob = service.vault.root / item["blob_name"]
    ciphertext = blob.read_bytes()
    blob.write_bytes(ciphertext[:-1] + bytes([ciphertext[-1] ^ 1]))
    rule.write_text(RECOVERED_RULE, encoding="utf-8")
    with pytest.raises(InvalidTag):
        service.vault.restore(detected.quarantine_id,
            lambda path: service.scan_file(path, quarantine=False, use_cache=False), force=True)
    assert not source.exists()
    assert service.vault.inspect(detected.quarantine_id)["restored_at"] is None


@pytest.mark.parametrize("parent,name,payload,detected", [
    ("日本語", "ordinary.bin", INERT, True),
    ("ordinary", "日本語.bin", b"Owned clean bytes", False),
    ("空", "空.bin", b"", False),
    ("ordinary", "ordinary.bin", INERT, True),
    ("nested-ascii/" * 12, "ordinary.bin", INERT, True),
], ids=["unicode-parent", "unicode-name", "unicode-empty", "ascii-positive", "long-ascii"])
def test_real_yara_paths_without_full_file_bytes_copy(tmp_path, monkeypatch, record_property,
                                                    parent, name, payload, detected):
    service, _rule = real_service(tmp_path, record_property)
    folder = tmp_path / parent
    folder.mkdir(parents=True)
    target = folder / name
    target.write_bytes(payload)
    original = Path.read_bytes

    def no_payload_copy(path):
        if path == target:
            pytest.fail("Scanner must not copy the complete payload into a second bytes allocation")
        return original(path)

    monkeypatch.setattr(Path, "read_bytes", no_payload_copy)
    findings = service.engines[0].scan(target, hashlib.sha256(payload).hexdigest())
    assert all(row.state.value == "available" for row in findings), findings
    assert any(row.score == 80 for row in findings) == detected
    # Successful rename and deletion prove scanner mappings/handles were released.
    renamed = folder / "after-scan.bin"
    target.rename(renamed)
    assert renamed.read_bytes() == payload
    renamed.unlink()


def test_real_yara_empty_file_can_match_a_rule(tmp_path, record_property):
    service, rule = real_service(tmp_path, record_property)
    rule.write_text("rule Empty_Owned_File { condition: filesize == 0 }", encoding="utf-8")
    target = tmp_path / "empty 日本語.bin"
    target.write_bytes(b"")
    findings = service.engines[0].scan(target, hashlib.sha256(b"").hexdigest())
    assert any(row.name == "Empty_Owned_File" and row.score == 80 for row in findings), findings
    assert all(row.state.value == "available" for row in findings)
    target.unlink()
