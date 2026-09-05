# Start Go-based Hermes Desktop<->backend watchdog (operator-only; NOT agent-reachable).
param(
    [int]$IntervalSec = 20,
    [int]$FailThreshold = 2,
    [switch]$Once,
    [switch]$NoPrewarm,
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
    [switch]$RunBuildTests,
    # Watchdog-managed hermes serve port; 9120/8787/9920 remain reserved ops ports.
    # Desktop connects via desktop-backend.json / HERMES_DESKTOP_REMOTE_*; default 9119.
    [int]$ManagedBackendPort = 9119
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
        try { Stop-Process -Id $proc.Id -Force -ErrorAction SilentlyContinue } catch {}
        # Also kill orphaned go children from the timed-out build.
        Get-CimInstance Win32_Process -ErrorAction SilentlyContinue | Where-Object {
            $_.CommandLine -and $_.CommandLine -match 'watchdog-go' -and $_.Name -match '^(go|compile|link)\.exe$'
        } | ForEach-Object {
            Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue
        }
        throw "Go watchdog build timed out after ${TimeoutSec}s"
    }
    if ($proc.ExitCode -ne 0) {
        throw "Go watchdog build failed (exit $($proc.ExitCode))"
    }
}

$DataDir = Join-Path $env:LOCALAPPDATA "HermesWatchdog"
$LockPath = Join-Path $DataDir "watchdog.lock"

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
    if ($ProcessId -le 0) { return $null }
    try {
        $proc = Get-Process -Id $ProcessId -ErrorAction Stop
        $processPath = [string]$proc.Path
        $startedUtc = $proc.StartTime.ToUniversalTime()
        if ([string]::IsNullOrWhiteSpace($processPath)) { return $null }
        return [pscustomobject]@{
            Pid = [int]$proc.Id
            ProcessCreated = [uint64]($startedUtc.ToFileTimeUtc())
            ExecutablePath = Get-NormalizedPath $processPath
            StartedUtc = $startedUtc
        }
    } catch {
        return $null
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
        return [pscustomobject]@{ Status = "stale"; Pid = $pidLock; Reason = "process is absent" }
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
    if ($obj.processCreated) {
        try {
            $creationMatches = ([uint64]$obj.processCreated -eq [uint64]$identity.ProcessCreated)
        } catch {
            $creationMatches = $false
        }
    } elseif ($obj.startedAt) {
        try {
            $lockedStart = [DateTimeOffset]::Parse(
                [string]$obj.startedAt,
                [Globalization.CultureInfo]::InvariantCulture,
                [Globalization.DateTimeStyles]::RoundtripKind
            ).UtcDateTime
            $creationMatches = ([math]::Abs(($lockedStart - $identity.StartedUtc).TotalSeconds) -le 10)
        } catch {
            $creationMatches = $false
        }
    }
    if (-not $creationMatches) {
        return [pscustomobject]@{ Status = "foreign"; Pid = $pidLock; Reason = "process creation time mismatch" }
    }
    return [pscustomobject]@{ Status = "owned"; Pid = $pidLock; Reason = "full identity matched" }
}

function Test-GoWatchdogAlive {
    $state = Get-GoWatchdogLockState
    return $state.Status -eq "owned"
}

function Stop-GoWatchdog {
    $state = Get-GoWatchdogLockState
    if ($state.Status -eq "owned") {
        Stop-Process -Id $state.Pid -Force -ErrorAction Stop
        for ($attempt = 0; $attempt -lt 20; $attempt++) {
            if (-not (Get-Process -Id $state.Pid -ErrorAction SilentlyContinue)) { break }
            Start-Sleep -Milliseconds 100
        }
        if (Get-Process -Id $state.Pid -ErrorAction SilentlyContinue) {
            Write-Warning "Go watchdog pid $($state.Pid) did not exit; preserving its lock."
            return $false
        }
        $state = Get-GoWatchdogLockState
    }
    if ($state.Status -eq "stale") {
        Remove-Item -LiteralPath $LockPath -Force -ErrorAction Stop
    } elseif ($state.Status -eq "foreign") {
        Write-Warning "Go watchdog lock identity is foreign ($($state.Reason)); refusing to stop or remove its lock."
        return $false
    }
    return $true
}

function Stop-PsDesktopBackendWatchdog {
    # PS and Go watchdogs use different lock files; running both causes dual
    # Hermes.exe relaunch loops. Prefer Go; stop the legacy PS mutual watchdog.
    $psLock = Join-Path $HermesHome "logs\desktop-backend-watchdog.lock"
    $LegacyWatchdogScript = (Resolve-Path -LiteralPath (Join-Path $ScriptDir "Start-HermesDesktopBackendWatchdog.ps1") -ErrorAction Stop).Path
    $legacyScriptPattern = [regex]::Escape($LegacyWatchdogScript)
    Get-CimInstance Win32_Process -Property ProcessId, CommandLine -OperationTimeoutSec 8 -ErrorAction SilentlyContinue | Where-Object {
        $_.CommandLine -and $_.CommandLine -match $legacyScriptPattern
    } | ForEach-Object {
        Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue
    }
    Remove-Item -LiteralPath $psLock -Force -ErrorAction SilentlyContinue
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
    "-fail-threshold=$FailThreshold",
    "-hermes-root", $RepoRoot,
    "-hermes-home", $HermesHome,
    "-listen=$Listen"
)
if ($Once) { $argList += "-once" }
if ($NoPrewarm) { $argList += "-prewarm-backend=false" }
if ($ManagedBackendPort -gt 0) { $argList += "-managed-backend-port=$ManagedBackendPort" }
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
        "-fail-threshold=$FailThreshold",
        (Format-WatchdogArg "-hermes-root" $RepoRoot),
        (Format-WatchdogArg "-hermes-home" $HermesHome),
        "-listen=$Listen"
    )
    if ($Once) { $shellArgs += "-once" }
    if ($NoPrewarm) { $shellArgs += "-prewarm-backend=false" }
    if ($ManagedBackendPort -gt 0) { $shellArgs += "-managed-backend-port=$ManagedBackendPort" }
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
