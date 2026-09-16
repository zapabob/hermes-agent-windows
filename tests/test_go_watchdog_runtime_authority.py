"""Exercise production launcher functions, not a reimplementation of their policy."""
from __future__ import annotations

import os
from pathlib import Path
import shutil
import subprocess

import pytest

ROOT = Path(__file__).resolve().parents[1]
LAUNCHER = ROOT / "scripts/windows/Start-HermesGoWatchdog.ps1"

# Only function definitions and (for the native case) the interop declaration
# are loaded. The operator launcher itself is NEVER executed. All lock files
# live in pytest's temp directory. Synthetic cases cannot touch real processes;
# the native case owns one harmless sleeper via a retained Process object.
HARNESS = r'''
param([string]$Launcher, [string]$Scratch, [string]$Scenario)
$ErrorActionPreference = "Stop"
$source = [IO.File]::ReadAllText($Launcher)
$tokens = $null
$errors = $null
$ast = [Management.Automation.Language.Parser]::ParseInput($source, [ref]$tokens, [ref]$errors)
if ($errors.Count) { throw ($errors | Out-String) }
$wanted = @(
    'Get-NormalizedPath', 'Test-SamePath', 'Get-WindowsProcessIdentity',
    'Get-WindowsProcessIdentityFromHandle', 'Get-GoWatchdogLockState', 'Stop-GoWatchdog'
)
$functions = $ast.FindAll({
    param($node)
    $node -is [Management.Automation.Language.FunctionDefinitionAst] -and $node.Name -in $wanted
}, $true)
if ($functions.Count -ne $wanted.Count) { throw 'Missing production authority functions' }
foreach ($function in $functions) { Invoke-Expression $function.Extent.Text }
$RepoRoot = $Scratch
$Exe = Join-Path $Scratch 'hermes-watchdog.exe'
$LockPath = Join-Path $Scratch 'watchdog.lock'
function Write-FixtureLock([int]$ProcessId, [uint64]$Created) {
    $payload = @{ pid=$ProcessId; processCreated=$Created; executablePath=$Exe; repoRoot=$RepoRoot }
    [IO.File]::WriteAllText($LockPath, ($payload | ConvertTo-Json), (New-Object Text.UTF8Encoding $false))
}
function Assert-Authority([bool]$Value, [string]$Message) {
    if (-not $Value) { throw $Message }
}

if ($Scenario -eq 'native') {
    $interop = [regex]::Match($source, "(?s)Add-Type -TypeDefinition @'\r?\n(.*?)\r?\n'@")
    if (-not $interop.Success) { throw 'Missing production native interop' }
    Add-Type -TypeDefinition $interop.Groups[1].Value
    $shell = (Get-Process -Id $PID).Path
    $child = Start-Process -FilePath $shell -ArgumentList @(
        '-NoProfile', '-NonInteractive', '-Command', 'Start-Sleep -Seconds 60'
    ) -WindowStyle Hidden -PassThru
    try {
        $identity = Get-WindowsProcessIdentity -ProcessId $child.Id
        Assert-Authority ($null -ne $identity) 'Could not query retained test child'
        $Exe = $identity.ExecutablePath
        [uint64]$wrongCreated = $identity.ProcessCreated
        $wrongCreated++
        Write-FixtureLock $child.Id $wrongCreated
        Assert-Authority (-not (Stop-GoWatchdog)) 'Wrong incarnation was accepted'
        Assert-Authority (-not $child.HasExited) 'Foreign incarnation test killed child'
        Assert-Authority (Test-Path -LiteralPath $LockPath) 'Foreign lock was removed'
        Write-FixtureLock $child.Id $identity.ProcessCreated
        Assert-Authority (Stop-GoWatchdog) 'Matching live owner did not stop'
        Assert-Authority ($child.WaitForExit(5000)) 'Retained child did not exit'
        Assert-Authority (-not (Test-Path -LiteralPath $LockPath)) 'Verified dead lock remained'
        Write-Output 'NATIVE_EXACT_HANDLE_OK'
    } finally {
        if (-not $child.HasExited) { $child.Kill(); $child.WaitForExit() }
        $child.Dispose()
    }
    exit 0
}

Add-Type -TypeDefinition @'
using System;
namespace HermesWatchdog {
    public static class NativeProcess {
        public static IntPtr ResultHandle = new IntPtr(123);
        public static IntPtr ValidatedHandle;
        public static IntPtr TerminatedHandle;
        public static IntPtr ClosedHandle;
        public static bool Terminated;
        public static uint WaitResult;
        public static IntPtr OpenProcess(uint access, bool inherit, uint pid) { return ResultHandle; }
        public static IntPtr OpenProcessForAuthority(uint access, uint pid, out int error) {
            error = ResultHandle == IntPtr.Zero ? 5 : 0;
            return ResultHandle;
        }
        public static bool TerminateProcess(IntPtr handle, uint exitCode) {
            TerminatedHandle = handle; Terminated = true; return true;
        }
        public static uint WaitForSingleObject(IntPtr handle, uint ms) { return WaitResult; }
        public static bool CloseHandle(IntPtr handle) { ClosedHandle = handle; return true; }
    }
}
'@
$script:NumericStopCalls = 0
function Get-Process {
    [CmdletBinding()] param([int]$Id)
    if (-not [HermesWatchdog.NativeProcess]::Terminated -and $Scenario -ne 'denied_invisible') {
        [pscustomobject]@{ Id=$Id; SessionId=0 }
    }
}
function Stop-Process {
    [CmdletBinding()] param([int]$Id, [switch]$Force)
    $script:NumericStopCalls++
}
function Start-Process {
    [CmdletBinding()] param($FilePath, $ArgumentList, [switch]$Wait, [switch]$PassThru, $WindowStyle)
    $script:NumericStopCalls++
    [pscustomobject]@{ ExitCode=0 }
}
function Start-Sleep { param($Milliseconds, $Seconds) }
function Get-WindowsProcessIdentity {
    param([int]$ProcessId)
    if ([HermesWatchdog.NativeProcess]::Terminated) {
        $script:WatchdogIdentityProbeError = 87
        return $null
    }
    if ($Scenario -in @('denied_query', 'denied_invisible')) {
        $script:WatchdogIdentityProbeError = 5
        return $null
    }
    $script:WatchdogIdentityProbeError = 0
    [pscustomobject]@{ Pid=$ProcessId; ProcessCreated=[uint64]100; ExecutablePath=$Exe }
}
function Get-WindowsProcessIdentityFromHandle {
    param([IntPtr]$Handle, [int]$ProcessId)
    [HermesWatchdog.NativeProcess]::ValidatedHandle = $Handle
    $created = if ($Scenario -eq 'pid_reuse') { [uint64]101 } else { [uint64]100 }
    $actualExe = if ($Scenario -eq 'exe_changed') { Join-Path $Scratch 'foreign.exe' } else { $Exe }
    [pscustomobject]@{ Pid=$ProcessId; ProcessCreated=$created; ExecutablePath=$actualExe }
}
Write-FixtureLock 42424 100
$before = [IO.File]::ReadAllText($LockPath)
if ($Scenario -in @('denied_query', 'denied_invisible', 'denied_stop')) {
    [HermesWatchdog.NativeProcess]::ResultHandle = [IntPtr]::Zero
}
if ($Scenario -eq 'wait_timeout') { [HermesWatchdog.NativeProcess]::WaitResult = 258 }
$result = Stop-GoWatchdog
Assert-Authority ($script:NumericStopCalls -eq 0) 'Unverified numeric PID stop was attempted'
if ($Scenario -eq 'same_identity') {
    Assert-Authority $result 'Verified Session 0 identity could not be displaced'
    Assert-Authority ([HermesWatchdog.NativeProcess]::ValidatedHandle -eq [IntPtr]123) 'Wrong validation handle'
    Assert-Authority ([HermesWatchdog.NativeProcess]::TerminatedHandle -eq [IntPtr]123) 'Termination changed handle'
    Assert-Authority ([HermesWatchdog.NativeProcess]::ClosedHandle -eq [IntPtr]123) 'Handle leaked'
    Assert-Authority (-not (Test-Path -LiteralPath $LockPath)) 'Verified dead lock remained'
} else {
    Assert-Authority (-not $result) 'Unverified/unfinished stop reported success'
    Assert-Authority (Test-Path -LiteralPath $LockPath) 'Unverified lock was deleted'
    Assert-Authority ([IO.File]::ReadAllText($LockPath) -eq $before) 'Unverified lock was changed'
    if ($Scenario -ne 'wait_timeout') {
        Assert-Authority (-not [HermesWatchdog.NativeProcess]::Terminated) 'Unverified handle was terminated'
    }
}
Write-Output ('AUTHORITY_OK ' + $Scenario)
'''


def test_watchdog_does_not_treat_denied_query_as_live_ownership() -> None:
    source = LAUNCHER.read_text(encoding="utf-8")
    assert "lock matched visible process without OpenProcess query" not in source
    stop_body = source.split("function Stop-GoWatchdog", 1)[1].split(
        "function Stop-PsDesktopBackendWatchdog", 1
    )[0]
    assert "Stop-Process" not in stop_body
    assert "taskkill" not in stop_body


@pytest.mark.windows_only
@pytest.mark.skipif(os.name != "nt", reason="Native Windows process authority")
@pytest.mark.parametrize("shell_name", ["powershell.exe", "pwsh.exe"])
@pytest.mark.parametrize("scenario", [
    "denied_query", "denied_invisible", "denied_stop", "pid_reuse",
    "exe_changed", "same_identity", "wait_timeout", "native",
])
def test_watchdog_process_authority_behavior(tmp_path: Path, shell_name: str, scenario: str) -> None:
    shell = shutil.which(shell_name)
    assert shell, f"Required Windows regression shell is missing: {shell_name}"
    harness = tmp_path / "authority.ps1"
    harness.write_text(HARNESS, encoding="ascii")
    result = subprocess.run(
        [shell, "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass",
         "-File", str(harness), "-Launcher", str(LAUNCHER),
         "-Scratch", str(tmp_path), "-Scenario", scenario],
        capture_output=True, text=True, encoding="utf-8", errors="replace",
        timeout=90, check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    expected = "NATIVE_EXACT_HANDLE_OK" if scenario == "native" else f"AUTHORITY_OK {scenario}"
    assert expected in result.stdout
