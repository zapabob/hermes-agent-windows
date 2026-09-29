# Start the Go-based Hermes Windows recovery watchdog (operator-only; NOT agent-reachable).
param(
    [int]$IntervalSec = 20,
    [switch]$Once,
    [switch]$NoTsnet,
    [string]$Listen = "127.0.0.1:9920",
    [string]$HermesRoot = "",
    [string]$HermesHome = "",
    [switch]$BuildIfMissing,
    [switch]$ForceRestart,
    [switch]$Stop,
    # Bound go build so restart-hermes-stack never hangs on go mod tidy / network.
    [int]$BuildTimeoutSec = 180,
    # Default skip go test for operator start path (full test via Build-HermesGoWatchdog.ps1).
    [switch]$RunBuildTests
)

$ErrorActionPreference = "Stop"

function Test-IsElevatedOperator {
    try {
        $identity = [Security.Principal.WindowsIdentity]::GetCurrent()
        $principal = New-Object Security.Principal.WindowsPrincipal($identity)
        return $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
    } catch {
        return $false
    }
}

# The launcher is intentionally operator-only. Starting it elevated also gives
# the independent watchdog an OS boundary from a normal Hermes Agent process.
# Maintenance automation uses a separate fenced lifecycle path.
if (-not (Test-IsElevatedOperator)) {
    throw "Operator-only Go watchdog launcher requires an elevated PowerShell session."
}

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$RepoRootCandidate = if ($HermesRoot) { $HermesRoot } else { Join-Path $ScriptDir "..\.." }
$RepoRoot = (Resolve-Path -LiteralPath $RepoRootCandidate -ErrorAction Stop).Path
if (-not $HermesHome) { $HermesHome = Join-Path $env:USERPROFILE ".hermes" }
$env:HERMES_HOME = $HermesHome

$Exe = Join-Path $ScriptDir "watchdog-go\dist\hermes-watchdog.exe"

function Invoke-GoWatchdogBuildBounded {
    param(
        [string]$BuildScript,
        [int]$TimeoutSec,
        [switch]$SkipTest
    )
    $argList = @()
    if ($SkipTest) { $argList += "-SkipTest" }
    Write-Host ("Building Go watchdog (timeout={0}s, SkipTest={1})..." -f $TimeoutSec, [bool]$SkipTest)
    $quotedBuildScript = '"{0}"' -f $BuildScript.Replace('"', '\"')
    $processArgs = @("-NoProfile", "-ExecutionPolicy", "Bypass", "-File", $quotedBuildScript) + $argList
    $proc = Start-Process -FilePath "powershell.exe" `
        -ArgumentList ($processArgs -join " ") `
        -WorkingDirectory $ScriptDir `
        -PassThru `
        -WindowStyle Hidden
    if (-not $proc) {
        throw "Failed to start Build-HermesGoWatchdog.ps1"
    }
    $finished = $proc.WaitForExit($TimeoutSec * 1000)
    if (-not $finished) {
        try { $proc.Kill() } catch {}
        throw "Go watchdog build timed out after ${TimeoutSec}s"
    }
    if ($proc.ExitCode -ne 0) {
        throw "Go watchdog build failed (exit $($proc.ExitCode))"
    }
}

$DataDir = Join-Path $env:LOCALAPPDATA "HermesWatchdog"
$LockPath = Join-Path $DataDir "watchdog.lock"

if (-not ("HermesWatchdog.NativeProcess" -as [type])) {
    Add-Type -TypeDefinition @'
using System;
using System.Runtime.InteropServices;
using System.Text;

namespace HermesWatchdog {
    public static class NativeProcess {
        [DllImport("kernel32.dll", SetLastError = true)]
        public static extern IntPtr OpenProcess(uint access, bool inheritHandle, uint processId);

        [DllImport("kernel32.dll", SetLastError = true)]
        [return: MarshalAs(UnmanagedType.Bool)]
        public static extern bool GetProcessTimes(
            IntPtr process, out long creation, out long exit, out long kernel, out long user);

        [DllImport("kernel32.dll", CharSet = CharSet.Unicode, SetLastError = true)]
        [return: MarshalAs(UnmanagedType.Bool)]
        public static extern bool QueryFullProcessImageName(
            IntPtr process, uint flags, StringBuilder path, ref uint size);

        [DllImport("kernel32.dll", SetLastError = true)]
        [return: MarshalAs(UnmanagedType.Bool)]
        public static extern bool TerminateProcess(IntPtr process, uint exitCode);

        [DllImport("kernel32.dll", SetLastError = true)]
        public static extern uint WaitForSingleObject(IntPtr handle, uint milliseconds);

        [DllImport("kernel32.dll", SetLastError = true)]
        [return: MarshalAs(UnmanagedType.Bool)]
        public static extern bool CloseHandle(IntPtr handle);

        [StructLayout(LayoutKind.Sequential)]
        private struct Luid { public uint LowPart; public int HighPart; }
        [StructLayout(LayoutKind.Sequential)]
        private struct TokenPrivileges {
            public uint PrivilegeCount;
            public Luid Luid;
            public uint Attributes;
        }
        [DllImport("kernel32.dll")]
        private static extern IntPtr GetCurrentProcess();
        [DllImport("advapi32.dll", SetLastError = true)]
        [return: MarshalAs(UnmanagedType.Bool)]
        private static extern bool OpenProcessToken(IntPtr process, uint access, out IntPtr token);
        [DllImport("advapi32.dll", CharSet = CharSet.Unicode, SetLastError = true)]
        [return: MarshalAs(UnmanagedType.Bool)]
        private static extern bool LookupPrivilegeValue(string system, string name, out Luid luid);
        [DllImport("advapi32.dll", SetLastError = true)]
        [return: MarshalAs(UnmanagedType.Bool)]
        private static extern bool AdjustTokenPrivileges(IntPtr token, bool disableAll,
            ref TokenPrivileges next, uint length, out TokenPrivileges previous, out uint returned);
        [DllImport("advapi32.dll", EntryPoint = "AdjustTokenPrivileges", SetLastError = true)]
        [return: MarshalAs(UnmanagedType.Bool)]
        private static extern bool RestoreTokenPrivileges(IntPtr token, bool disableAll,
            ref TokenPrivileges previous, uint length, IntPtr unusedPrevious, IntPtr unusedLength);
        private static readonly object PrivilegeGate = new object();

        // Error 87 proves a missing PID only when returned by OpenProcess.
        // Privilege APIs can return the same number for unrelated failures.
        private static int UnverifiedAuthorityError(int error) {
            return error == 0 || error == 87 ? 5 : error;
        }

        // Session 0 recovery may need an already-held administrator privilege.
        // Enable it only around OpenProcess, restore its exact prior state, then
        // let the caller validate creation time and image on the returned handle.
        // A lock file or SessionId never substitutes for this live evidence.
        public static IntPtr OpenProcessForAuthority(uint access, uint processId, out int error) {
            IntPtr handle = OpenProcess(access, false, processId);
            error = handle == IntPtr.Zero ? Marshal.GetLastWin32Error() : 0;
            if (handle != IntPtr.Zero || error != 5) { return handle; }
            lock (PrivilegeGate) {
                IntPtr token;
                if (!OpenProcessToken(GetCurrentProcess(), 0x20 | 0x8, out token)) {
                    error = UnverifiedAuthorityError(Marshal.GetLastWin32Error());
                    return IntPtr.Zero;
                }
                TokenPrivileges previous = new TokenPrivileges();
                bool changed = false;
                try {
                    Luid luid;
                    if (!LookupPrivilegeValue(null, "SeDebugPrivilege", out luid)) {
                        error = UnverifiedAuthorityError(Marshal.GetLastWin32Error());
                    } else {
                        TokenPrivileges next = new TokenPrivileges {
                            PrivilegeCount = 1, Luid = luid, Attributes = 2
                        };
                        uint returned;
                        bool adjusted = AdjustTokenPrivileges(token, false, ref next,
                            (uint)Marshal.SizeOf(typeof(TokenPrivileges)), out previous, out returned);
                        int adjustError = Marshal.GetLastWin32Error();
                        changed = adjusted && previous.PrivilegeCount != 0;
                        if (adjusted && adjustError == 0) {
                            handle = OpenProcess(access, false, processId);
                            error = handle == IntPtr.Zero ? Marshal.GetLastWin32Error() : 0;
                        } else {
                            // TRUE plus ERROR_NOT_ALL_ASSIGNED (1300) is not success.
                            error = UnverifiedAuthorityError(adjustError);
                        }
                    }
                } finally {
                    if (changed) {
                        bool restored = RestoreTokenPrivileges(token, false, ref previous,
                            0, IntPtr.Zero, IntPtr.Zero);
                        int restoreError = Marshal.GetLastWin32Error();
                        if (!restored || restoreError != 0) {
                            if (handle != IntPtr.Zero) { CloseHandle(handle); }
                            handle = IntPtr.Zero;
                            error = UnverifiedAuthorityError(restoreError);
                        }
                    }
                    CloseHandle(token);
                }
            }
            return handle;
        }
    }
}
'@
}

# Add-Type definitions persist in an interactive PowerShell session. Never fall
# back to the old PID-only stop policy when an operator reused an old session.
if (-not ([HermesWatchdog.NativeProcess].GetMethod('OpenProcessForAuthority'))) {
    throw "Open a fresh elevated PowerShell session to load updated watchdog process authority."
}

function Get-NormalizedPath {
    param([AllowEmptyString()][string]$Path)
    if ([string]::IsNullOrWhiteSpace($Path)) { return "" }
    try {
        return [System.IO.Path]::GetFullPath($Path).TrimEnd('\')
    } catch {
        return ""
    }
}

function Test-SamePath {
    param([string]$Left, [string]$Right)
    $leftPath = Get-NormalizedPath $Left
    $rightPath = Get-NormalizedPath $Right
    if (-not $leftPath -or -not $rightPath) { return $false }
    return [string]::Equals($leftPath, $rightPath, [System.StringComparison]::OrdinalIgnoreCase)
}

function Get-WindowsProcessIdentity {
    param([int]$ProcessId)
    $script:WatchdogIdentityProbeError = 0
    if ($ProcessId -le 0) { return $null }
    [int]$nativeError = 0
    $handle = [HermesWatchdog.NativeProcess]::OpenProcessForAuthority(
        (0x1000 -bor 0x00100000), [uint32]$ProcessId, [ref]$nativeError
    )
    if ($handle -eq [IntPtr]::Zero) {
        $script:WatchdogIdentityProbeError = $nativeError
        return $null
    }
    try {
        $identity = Get-WindowsProcessIdentityFromHandle -Handle $handle -ProcessId $ProcessId
        if (-not $identity) {
            # Only a signalled process handle proves death. Query denial is unknown.
            $script:WatchdogIdentityProbeError = 5
            if ([HermesWatchdog.NativeProcess]::WaitForSingleObject($handle, 0) -eq 0) {
                $script:WatchdogIdentityProbeError = 87
            }
        }
        return $identity
    } finally {
        [void][HermesWatchdog.NativeProcess]::CloseHandle($handle)
    }
}

function Get-WindowsProcessIdentityFromHandle {
    param([IntPtr]$Handle, [int]$ProcessId)
    [long]$created = 0
    [long]$exited = 0
    [long]$kernel = 0
    [long]$user = 0
    if (-not [HermesWatchdog.NativeProcess]::GetProcessTimes(
        $Handle, [ref]$created, [ref]$exited, [ref]$kernel, [ref]$user
    )) { return $null }
    if ($exited -ne 0) { return $null }
    $path = New-Object System.Text.StringBuilder 32768
    [uint32]$pathLength = $path.Capacity
    if (-not [HermesWatchdog.NativeProcess]::QueryFullProcessImageName(
        $Handle, 0, $path, [ref]$pathLength
    )) { return $null }
    return [pscustomobject]@{
        Pid = $ProcessId
        ProcessCreated = [uint64]$created
        ExecutablePath = Get-NormalizedPath $path.ToString()
    }
}

function Get-GoWatchdogLockState {
    if (-not (Test-Path -LiteralPath $LockPath)) {
        return [pscustomobject]@{ Status = "missing"; Pid = 0; Reason = "lock missing" }
    }
    try {
        $obj = Get-Content -LiteralPath $LockPath -Raw -Encoding utf8 | ConvertFrom-Json -ErrorAction Stop
        $pidLock = [int]$obj.pid
    } catch {
        return [pscustomobject]@{ Status = "foreign"; Pid = 0; Reason = "lock is unreadable" }
    }
    if ($pidLock -le 0) {
        return [pscustomobject]@{ Status = "stale"; Pid = $pidLock; Reason = "lock has no valid PID" }
    }
    $identity = Get-WindowsProcessIdentity -ProcessId $pidLock
    if (-not $identity) {
        if ($script:WatchdogIdentityProbeError -eq 87) {
            return [pscustomobject]@{ Status = "stale"; Pid = $pidLock; Reason = "process is absent or exited" }
        }
        return [pscustomobject]@{
            Status = "foreign"; Pid = $pidLock
            Reason = "process identity is unverified (Win32 error $script:WatchdogIdentityProbeError)"
        }
    }
    if (-not (Test-SamePath ([string]$obj.repoRoot) $RepoRoot)) {
        return [pscustomobject]@{ Status = "foreign"; Pid = $pidLock; Reason = "repository root mismatch" }
    }
    if (-not (Test-SamePath $identity.ExecutablePath $Exe)) {
        return [pscustomobject]@{ Status = "foreign"; Pid = $pidLock; Reason = "process executable mismatch" }
    }
    if ($obj.executablePath -and -not (Test-SamePath ([string]$obj.executablePath) $identity.ExecutablePath)) {
        return [pscustomobject]@{ Status = "foreign"; Pid = $pidLock; Reason = "lock executable mismatch" }
    }

    $creationMatches = $false
    try {
        $creationMatches = (
            $null -ne $obj.processCreated -and
            [uint64]$obj.processCreated -eq [uint64]$identity.ProcessCreated
        )
    } catch { $creationMatches = $false }
    if (-not $creationMatches) {
        return [pscustomobject]@{ Status = "foreign"; Pid = $pidLock; Reason = "process creation time mismatch" }
    }
    $sessionId = -1
    try { $sessionId = [int](Get-Process -Id $pidLock -ErrorAction Stop).SessionId } catch { $sessionId = -1 }
    return [pscustomobject]@{
        Status = "owned"
        Pid = $pidLock
        ProcessCreated = [uint64]$identity.ProcessCreated
        ExecutablePath = $identity.ExecutablePath
        RepoRoot = Get-NormalizedPath ([string]$obj.repoRoot)
        SessionId = $sessionId
        Reason = "full identity matched"
    }
}

function Test-GoWatchdogAlive {
    $state = Get-GoWatchdogLockState
    return $state.Status -eq "owned"
}

function Stop-GoWatchdog {
    $state = Get-GoWatchdogLockState
    if ($state.Status -eq "owned") {
        $access = 0x1000 -bor 0x0001 -bor 0x00100000
        [int]$nativeError = 0
        $handle = [HermesWatchdog.NativeProcess]::OpenProcessForAuthority(
            $access, [uint32]$state.Pid, [ref]$nativeError
        )
        if ($handle -eq [IntPtr]::Zero) {
            Write-Warning "Could not open the validated watchdog process (Win32 error $nativeError); preserving its lock."
            return $false
        }
        try {
            $current = Get-WindowsProcessIdentityFromHandle -Handle $handle -ProcessId $state.Pid
            if (
                -not $current -or
                [uint64]$current.ProcessCreated -ne [uint64]$state.ProcessCreated -or
                -not (Test-SamePath $current.ExecutablePath $state.ExecutablePath) -or
                -not (Test-SamePath $state.RepoRoot $RepoRoot)
            ) {
                Write-Warning "Watchdog identity changed before stop; preserving its lock."
                return $false
            }
            if (-not [HermesWatchdog.NativeProcess]::TerminateProcess($handle, 1)) {
                Write-Warning "Exact watchdog process handle could not be terminated; preserving its lock."
                return $false
            }
            if ([HermesWatchdog.NativeProcess]::WaitForSingleObject($handle, 2000) -ne 0) {
                Write-Warning "Exact watchdog process has not finished stopping; preserving its lock."
                return $false
            }
        } finally {
            [void][HermesWatchdog.NativeProcess]::CloseHandle($handle)
        }
        $state = Get-GoWatchdogLockState
    }
    if ($state.Status -eq "stale") {
        Remove-Item -LiteralPath $LockPath -Force -ErrorAction Stop
    } elseif ($state.Status -eq "foreign") {
        Write-Warning "Go watchdog lock identity is foreign ($($state.Reason)); refusing to stop or remove its lock."
        return $false
    } elseif ($state.Status -eq "owned") {
        Write-Warning "Go watchdog still owned after stop attempt; preserving its lock."
        return $false
    }
    return $true
}

function Stop-PsDesktopBackendWatchdog {
    # The legacy entry point is now a non-resident compatibility shim that
    # delegates to this launcher.  Command-line matching is not process
    # identity and must never authorize killing a PowerShell process.  Old
    # lock files are deliberately preserved: only their proven owner may
    # remove them, and the Go watchdog never consumes that lock namespace.
    Write-Verbose "Legacy Desktop/backend watchdog shim has no restart authority."
}

if ($Stop) {
    if (Stop-GoWatchdog) {
        Write-Host "Go watchdog stopped or was not running."
        exit 0
    }
    exit 1
}

if (-not (Test-Path -LiteralPath $Exe)) {
    if ($BuildIfMissing) {
        $buildScript = Join-Path $ScriptDir "Build-HermesGoWatchdog.ps1"
        try {
            Invoke-GoWatchdogBuildBounded -BuildScript $buildScript -TimeoutSec $BuildTimeoutSec -SkipTest:(-not $RunBuildTests)
        } catch {
            Write-Warning $_.Exception.Message
            Write-Warning "Skipping Go watchdog start; run Build-HermesGoWatchdog.ps1 manually when ready."
            exit 0
        }
        if (-not (Test-Path -LiteralPath $Exe)) {
            Write-Warning "Build finished but missing $Exe; skipping Go watchdog start."
            exit 0
        }
    } else {
        throw "Missing $Exe; run Build-HermesGoWatchdog.ps1 first or pass -BuildIfMissing"
    }
}

function Get-EmbeddingWatchdogArguments {
    param(
        [Parameter(Mandatory = $true)][string]$Root
    )

    $pythonCandidates = @(
        (Join-Path $Root ".venv\Scripts\python.exe"),
        (Join-Path $Root "venv\Scripts\python.exe"),
        (Join-Path $env:USERPROFILE ".hermes\hermes-agent\venv\Scripts\python.exe")
    )
    $pythonExe = $pythonCandidates | Where-Object { Test-Path -LiteralPath $_ } | Select-Object -First 1
    if (-not $pythonExe) {
        Write-Warning "Embedding supervision skipped: no repository Python runtime was found."
        return @()
    }

    $configCode = @'
import json
import sys

from hermes_cli.config import load_config_readonly

config = load_config_readonly() or {}
entries = ((config.get("plugins") or {}).get("entries") or {})
entry = entries.get("semantic-graph") or entries.get("semantic_graph") or {}
plugin_config = entry.get("config") if isinstance(entry, dict) else {}
plugin_config = plugin_config if isinstance(plugin_config, dict) else {}
embedding = plugin_config.get("embedding") or {}
embedding = embedding if isinstance(embedding, dict) else {}
runtime = embedding.get("runtime") or {}
runtime = runtime if isinstance(runtime, dict) else {}
arguments = runtime.get("arguments") or []
payload = {
    "enabled": bool(runtime.get("enabled", False)),
    "endpoint": str(embedding.get("endpoint") or ""),
    "executable": str(runtime.get("executable") or ""),
    "model_path": str(runtime.get("model_path") or ""),
    "arguments": arguments if isinstance(arguments, list) else [],
    "startup_timeout_seconds": runtime.get("startup_timeout_seconds", 180),
}
json.dump(payload, sys.stdout, ensure_ascii=False)
'@
    $raw = $null
    $configExitCode = 1
    Push-Location -LiteralPath $Root
    try {
        # Windows PowerShell's legacy native argument marshalling corrupts
        # quotes in multi-line ``python -c`` source. Feed this local snippet
        # over stdin so both Windows PowerShell and pwsh preserve it exactly.
        $raw = $configCode | & $pythonExe - 2>$null
        $configExitCode = $LASTEXITCODE
    } finally {
        Pop-Location
    }
    if ($configExitCode -ne 0) {
        Write-Warning "Embedding supervision skipped: config.yaml could not be read by the repository runtime."
        return @()
    }
    try {
        $runtime = $raw | ConvertFrom-Json -ErrorAction Stop
    } catch {
        Write-Warning "Embedding supervision skipped: config.yaml produced invalid runtime data."
        return @()
    }
    if (-not [bool]$runtime.enabled) {
        return @()
    }
    foreach ($name in @("endpoint", "executable", "model_path")) {
        if ([string]::IsNullOrWhiteSpace([string]$runtime.$name)) {
            Write-Warning "Embedding supervision skipped: embedding.runtime.$name is required when enabled."
            return @()
        }
    }
    $argumentValues = @($runtime.arguments | ForEach-Object { [string]$_ })
    if ($argumentValues | Where-Object { [string]::IsNullOrWhiteSpace($_) }) {
        Write-Warning "Embedding supervision skipped: embedding.runtime.arguments contains an empty item."
        return @()
    }
    try {
        $startTimeout = [int]$runtime.startup_timeout_seconds
    } catch {
        $startTimeout = 180
    }
    if ($startTimeout -le 0) { $startTimeout = 180 }
    $argumentsJson = if ($argumentValues.Count -eq 0) {
        "[]"
    } else {
        ConvertTo-Json -InputObject ([object[]]$argumentValues) -Compress
    }
    return @(
        "-embedding-enabled=true",
        "-embedding-endpoint", [string]$runtime.endpoint,
        "-embedding-server", [string]$runtime.executable,
        "-embedding-model", [string]$runtime.model_path,
        "-embedding-args-json", $argumentsJson,
        "-embedding-start-timeout=$startTimeout"
    )
}

function Get-CurrentProcessSessionId {
    try {
        return [int](Get-Process -Id $PID -ErrorAction Stop).SessionId
    } catch {
        return -1
    }
}

function Get-GoWatchdogSessionId {
    $state = Get-GoWatchdogLockState
    if ($state.Status -ne "owned" -or -not $state.Pid) {
        return $null
    }
    if ($null -ne $state.PSObject.Properties["SessionId"] -and $null -ne $state.SessionId -and [int]$state.SessionId -ge 0) {
        return [int]$state.SessionId
    }
    try {
        return [int](Get-Process -Id ([int]$state.Pid) -ErrorAction Stop).SessionId
    } catch {
        return $null
    }
}

# Boot S4U tasks park hermes-watchdog.exe in Session 0. The observation-only
# watchdog must run in the interactive session for operator visibility; an
# Interactive elevated launcher displaces Session 0 instead of "already running".
$launcherSessionId = Get-CurrentProcessSessionId
$existingWatchdogSessionId = Get-GoWatchdogSessionId
$replaceSession0Owner = (
    -not $ForceRestart -and
    -not $Once -and
    -not $Stop -and
    $null -ne $existingWatchdogSessionId -and
    [int]$existingWatchdogSessionId -eq 0 -and
    [int]$launcherSessionId -gt 0
)
if ($replaceSession0Owner) {
    Write-Warning ("Replacing Session 0 Go watchdog (pid session={0}) with interactive-session owner (launcher session={1})." -f $existingWatchdogSessionId, $launcherSessionId)
    $ForceRestart = $true
}

if ($ForceRestart -or $Once) {
    if (-not (Stop-GoWatchdog)) {
        throw "Cannot replace a watchdog whose full process identity is not owned by this launcher."
    }
} else {
    $startupState = Get-GoWatchdogLockState
    if ($startupState.Status -eq "foreign") {
        throw "Go watchdog lock identity is foreign ($($startupState.Reason)); refusing to start a second owner."
    }
}
Stop-PsDesktopBackendWatchdog

# Recovery budgets survive reboot and can suppress recovery attempts. Interactive
# logon starts with a clean outer-recovery budget so scheduled Desktop autostart
# is not undone by a stale circuit from the previous boot flap.
if ((Get-CurrentProcessSessionId) -gt 0 -and -not $Stop) {
    $recoveryBudgetPath = Join-Path $DataDir "recovery-budget.json"
    if (Test-Path -LiteralPath $recoveryBudgetPath) {
        $stamp = Get-Date -Format "yyyyMMddHHmmss"
        Copy-Item -LiteralPath $recoveryBudgetPath -Destination ("{0}.bak-logon-{1}" -f $recoveryBudgetPath, $stamp) -Force -ErrorAction SilentlyContinue
        Remove-Item -LiteralPath $recoveryBudgetPath -Force -ErrorAction SilentlyContinue
        Write-Host "Cleared recovery-budget.json for interactive logon start"
    }
}

if (Test-GoWatchdogAlive) {
    Write-Host "Go watchdog already running (lock=$LockPath)"
    exit 0
}

# Quote values with whitespace for the UseShellExecute fallback only.
function Format-WatchdogArg([string]$Name, [string]$Value) {
    if ($null -eq $Value) { $Value = "" }
    if ($Value -match '[\s"]') {
        $escaped = $Value.Replace('"', '\"')
        return ('{0}="{1}"' -f $Name, $escaped)
    }
    return ('{0}={1}' -f $Name, $Value)
}

function Quote-WatchdogArgument([string]$Value) {
    if ($null -eq $Value) { $Value = "" }
    if ($Value -match '[\s"]') {
        return ('"{0}"' -f $Value.Replace('"', '\"'))
    }
    return $Value
}

# Build one safely quoted Windows command line. Start-Process joins an array
# before CreateProcess, so passing a raw array splits a root such as
# "...\\New project\\..." and makes Go's flag parser ignore every later flag.
# Go's flag package accepts both -name=value and -name value.
$embeddingWatchdogArgs = @(Get-EmbeddingWatchdogArguments -Root $RepoRoot)
$argList = @(
    "-interval=$IntervalSec",
    "-hermes-root", $RepoRoot,
    "-hermes-home", $HermesHome,
    "-listen=$Listen"
)
if ($Once) { $argList += "-once" }
if ($embeddingWatchdogArgs.Count -gt 0) { $argList += $embeddingWatchdogArgs }
if (-not $NoTsnet -and ($env:HERMES_WATCHDOG_TS_AUTHKEY -or $env:TS_AUTHKEY)) {
    $argList += "-tsnet"
}

$workDir = Split-Path -Parent $Exe
$quotedArgList = @($argList | ForEach-Object { Quote-WatchdogArgument ([string]$_) })
Write-Host "Starting Go watchdog detached: $Exe $($quotedArgList -join ' ')"

$launched = $false
try {
    $proc = Start-Process -FilePath $Exe -ArgumentList ($quotedArgList -join ' ') -WorkingDirectory $workDir -WindowStyle Hidden -PassThru
    if ($proc) { $launched = $true }
} catch {
    Write-Warning "Start-Process ArgumentList failed: $($_.Exception.Message); trying UseShellExecute"
}
if (-not $launched) {
    # ShellExecute fallback: quote only values that contain whitespace.
    $shellArgs = @(
        "-interval=$IntervalSec",
        (Format-WatchdogArg "-hermes-root" $RepoRoot),
        (Format-WatchdogArg "-hermes-home" $HermesHome),
        "-listen=$Listen"
    )
    if ($Once) { $shellArgs += "-once" }
    foreach ($argument in $embeddingWatchdogArgs) {
        $shellArgs += (Quote-WatchdogArgument ([string]$argument))
    }
    if (-not $NoTsnet -and ($env:HERMES_WATCHDOG_TS_AUTHKEY -or $env:TS_AUTHKEY)) {
        $shellArgs += "-tsnet"
    }
    $startInfo = New-Object System.Diagnostics.ProcessStartInfo
    $startInfo.FileName = $Exe
    $startInfo.WorkingDirectory = $workDir
    $startInfo.Arguments = ($shellArgs -join ' ')
    $startInfo.WindowStyle = [System.Diagnostics.ProcessWindowStyle]::Hidden
    $startInfo.UseShellExecute = $true
    [void][System.Diagnostics.Process]::Start($startInfo)
}

Start-Sleep -Seconds 2
if (Test-GoWatchdogAlive) {
    Write-Host "Go watchdog launched (logs: $(Join-Path $HermesHome 'logs\hermes-go-watchdog.log'))"
} else {
    Write-Warning "Go watchdog may still be starting; check $(Join-Path $HermesHome 'logs\hermes-go-watchdog.log')"
}