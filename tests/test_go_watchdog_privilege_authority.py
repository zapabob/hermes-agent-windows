"""Exercise the production C# authority method with deterministic native-call doubles."""
from __future__ import annotations

import json
import os
from pathlib import Path
import shutil
import subprocess

import pytest

LAUNCHER = Path(__file__).resolve().parents[1] / "scripts/windows/Start-HermesGoWatchdog.ps1"


def _method(source: str, signature: str) -> str:
    start = source.index(signature)
    opening = source.index("{", start)
    depth = 1
    for end in range(opening + 1, len(source)):
        depth += (source[end] == "{") - (source[end] == "}")
        if depth == 0:
            return source[start:end + 1]
    raise AssertionError("Production method is incomplete")


FAKES = r'''
using System;
using System.Collections.Generic;
using System.Runtime.InteropServices;
public static class AuthorityProbe {
    private struct Luid { public uint LowPart; public int HighPart; }
    private struct TokenPrivileges { public uint PrivilegeCount; public Luid Luid; public uint Attributes; }
    private static readonly object PrivilegeGate = new object();
    public static string Scenario;
    public static int LastError;
    public static int Opens;
    public static bool Restored;
    public static List<long> Closed = new List<long>();
    private static int GetTestError() { return LastError; }
    private static IntPtr GetCurrentProcess() { return new IntPtr(7); }
    private static IntPtr OpenProcess(uint access, bool inherit, uint pid) {
        Opens++;
        if (inherit || access != 0x101001 || pid != 42424) { throw new Exception("OpenProcess arguments changed"); }
        if (Scenario == "absent" || (Opens == 2 && Scenario == "second_absent")) {
            LastError = 87; return IntPtr.Zero;
        }
        if (Opens == 1 && Scenario != "direct") { LastError = 5; return IntPtr.Zero; }
        LastError = 0; return new IntPtr(101);
    }
    private static bool OpenProcessToken(IntPtr process, uint access, out IntPtr token) {
        token = Scenario == "token_error" ? IntPtr.Zero : new IntPtr(202);
        LastError = Scenario == "token_error" ? 87 : 0;
        return token != IntPtr.Zero;
    }
    private static bool LookupPrivilegeValue(string system, string name, out Luid luid) {
        if (name != "SeDebugPrivilege") { throw new Exception("Unexpected privilege"); }
        luid = new Luid { LowPart = 20, HighPart = 0 };
        LastError = Scenario == "lookup_error" ? 87 : 0;
        return LastError == 0;
    }
    private static bool AdjustTokenPrivileges(IntPtr token, bool disableAll,
        ref TokenPrivileges next, uint length, out TokenPrivileges previous, out uint returned) {
        previous = new TokenPrivileges(); returned = 0;
        if (Scenario == "adjust_error") { LastError = 87; return false; }
        if (Scenario == "not_assigned") { LastError = 1300; return true; }
        previous = new TokenPrivileges { PrivilegeCount = 1, Luid = next.Luid, Attributes = 0 };
        returned = length; LastError = 0; return true;
    }
    private static bool RestoreTokenPrivileges(IntPtr token, bool disableAll,
        ref TokenPrivileges previous, uint length, IntPtr unusedPrevious, IntPtr unusedLength) {
        if (previous.PrivilegeCount != 1 || previous.Attributes != 0) { throw new Exception("Previous privilege state lost"); }
        LastError = Scenario == "restore_error" ? 87 : 0;
        Restored = LastError == 0;
        return Restored;
    }
    private static bool CloseHandle(IntPtr handle) { Closed.Add(handle.ToInt64()); return true; }
'''


@pytest.mark.windows_only
@pytest.mark.skipif(os.name != "nt", reason="C# interop runs in both native Windows shells")
@pytest.mark.parametrize("shell_name", ["powershell.exe", "pwsh.exe"])
@pytest.mark.parametrize("scenario", [
    "token_error", "lookup_error", "adjust_error", "restore_error",
    "not_assigned", "absent", "second_absent", "direct", "privileged",
])
def test_privilege_failure_never_means_process_absent(tmp_path: Path, shell_name: str, scenario: str) -> None:
    source = LAUNCHER.read_text(encoding="utf-8")
    body = _method(source, "public static IntPtr OpenProcessForAuthority(")
    # Only the native-error read is injected. The production decision logic is
    # compiled verbatim; no process/token API reaches the real operating system.
    body = body.replace("Marshal.GetLastWin32Error()", "GetTestError()")
    helper = ""
    if "private static int UnverifiedAuthorityError(" in source:
        helper = _method(source, "private static int UnverifiedAuthorityError(")
    code = tmp_path / "authority.cs"
    code.write_text(FAKES + helper + body + "\n}\n", encoding="ascii")
    script = tmp_path / "probe.ps1"
    script.write_text(
        'param([string]$Code, [string]$Scenario)\n'
        '$ErrorActionPreference = "Stop"\n'
        'Add-Type -TypeDefinition ([IO.File]::ReadAllText($Code))\n'
        '[AuthorityProbe]::Scenario = $Scenario\n'
        '[int]$nativeError = 0\n'
        '$handle = [AuthorityProbe]::OpenProcessForAuthority(0x101001, 42424, [ref]$nativeError)\n'
        '@{ handle=$handle.ToInt64(); error=$nativeError; restored=[AuthorityProbe]::Restored; '
        'closed=@([AuthorityProbe]::Closed.ToArray()) } | ConvertTo-Json -Compress\n',
        encoding="ascii",
    )
    shell = shutil.which(shell_name)
    assert shell, f"Required regression shell missing: {shell_name}"
    result = subprocess.run(
        [shell, "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass",
         "-File", str(script), "-Code", str(code), "-Scenario", scenario],
        capture_output=True, text=True, encoding="utf-8", errors="replace",
        timeout=60, check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    actual = json.loads(result.stdout.strip())
    if scenario in {"direct", "privileged"}:
        assert actual["handle"] == 101 and actual["error"] == 0
        assert 101 not in actual["closed"], "Successful caller must retain the process handle"
    elif scenario in {"absent", "second_absent"}:
        assert actual["handle"] == 0 and actual["error"] == 87
    else:
        assert actual["handle"] == 0
        assert actual["error"] not in {0, 87}, "Privilege API failure must preserve the unverified lock"
    if scenario not in {"token_error", "absent", "direct"}:
        assert 202 in actual["closed"], "Token handle leaked"
    if scenario in {"privileged", "second_absent"}:
        assert actual["restored"] is True
    if scenario == "restore_error":
        assert 101 in actual["closed"], "Process handle leaked after restoration failure"
