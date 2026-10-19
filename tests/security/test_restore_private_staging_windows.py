"""Actual Windows restore staging has a protected DACL before plaintext writes."""
from pathlib import Path
import sys

import pytest

from downstream.security.models import Finding, Verdict
from tests.security.test_restore_scan_decision import PAYLOAD, FixtureEngine, quarantined


pytestmark = [pytest.mark.windows_only,
              pytest.mark.skipif(sys.platform != "win32", reason="Windows DACL creation-time contract")]


@pytest.mark.parametrize("write_mode", ["success", "error", "partial"])
def test_restore_staging_is_private_before_first_plaintext_write(quarantined, monkeypatch, write_mode):
    import ntsecuritycon
    import win32api
    import win32con
    import win32file
    import win32security

    service, source, item_id, blob, encrypted = quarantined
    service.engines = (FixtureEngine((Finding("yara", "no-detection", 0),)),)
    # Deliberately inherited read permission on this test-owned destination.
    descriptor = win32security.GetFileSecurity(str(source.parent), win32security.DACL_SECURITY_INFORMATION)
    acl = descriptor.GetSecurityDescriptorDacl()
    everyone = win32security.CreateWellKnownSid(win32security.WinWorldSid, None)
    acl.AddAccessAllowedAceEx(win32security.ACL_REVISION,
        win32security.CONTAINER_INHERIT_ACE | win32security.OBJECT_INHERIT_ACE,
        ntsecuritycon.FILE_GENERIC_READ | ntsecuritycon.FILE_GENERIC_EXECUTE, everyone)
    descriptor.SetSecurityDescriptorDacl(1, acl, 0)
    win32security.SetFileSecurity(str(source.parent), win32security.DACL_SECURITY_INFORMATION, descriptor)
    token = win32security.OpenProcessToken(win32api.GetCurrentProcess(), win32con.TOKEN_QUERY)
    try:
        owner = win32security.GetTokenInformation(token, win32security.TokenUser)[0]
    finally:
        token.Close()
    system = win32security.CreateWellKnownSid(win32security.WinLocalSystemSid, None)
    allowed = {win32security.ConvertSidToStringSid(owner), win32security.ConvertSidToStringSid(system)}
    observed = []

    def assert_private(path):
        descriptor = win32security.GetFileSecurity(str(path), win32security.DACL_SECURITY_INFORMATION)
        acl = descriptor.GetSecurityDescriptorDacl()
        sids = {win32security.ConvertSidToStringSid(acl.GetAce(index)[2]) for index in range(acl.GetAceCount())}
        assert sids == allowed, "Restore plaintext write began with inherited reader access"
        assert descriptor.GetSecurityDescriptorControl()[0] & win32security.SE_DACL_PROTECTED
        observed.append(str(path))

    original_path_write = Path.write_bytes
    original_handle_write = win32file.WriteFile

    def path_write(path, data):
        if path.name.startswith(".hermes-restore-") and path.parent.samefile(source.parent) and data == PAYLOAD:
            assert_private(path)
        return original_path_write(path, data)

    def handle_write(handle, data, *args):
        path = Path(win32file.GetFinalPathNameByHandle(handle, 0))
        if path.name.startswith(".hermes-restore-") and path.parent.samefile(source.parent) and data == PAYLOAD:
            assert_private(path)
            if write_mode == "error":
                raise OSError("owned restore write failure")
            if write_mode == "partial":
                return original_handle_write(handle, data[:-1], *args)
        return original_handle_write(handle, data, *args)

    monkeypatch.setattr(Path, "write_bytes", path_write)
    monkeypatch.setattr(win32file, "WriteFile", handle_write)

    scans = []

    def rescan(path):
        scans.append(path)
        result = service.scan_file(path, quarantine=False, use_cache=False)
        assert result.verdict == Verdict.CLEAN, (result.error, result.findings)
        return result

    if write_mode != "success":
        with pytest.raises(OSError, match="restore.*(write|staging)"):
            service.vault.restore(item_id, rescan)
        assert observed and not scans
        assert not source.exists() and blob.read_bytes() == encrypted
        assert service.vault.inspect(item_id)["restored_at"] is None
        assert not list(source.parent.glob(".hermes-restore-*"))
        return

    restored = service.vault.restore(item_id, rescan)
    assert observed, "No actual restore plaintext write was observed"
    assert restored == source and source.read_bytes() == PAYLOAD
    assert not list(source.parent.glob(".hermes-restore-*"))
