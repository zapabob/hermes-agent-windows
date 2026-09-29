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
    # Bound go build so restart-hermes-stack never hangs on go mod tidy / network.
    [int]$BuildTimeoutSec = 180,
    # Default skip go test for operator start path (full test via Build-HermesGoWatchdog.ps1).
    [switch]$RunBuildTests,
    # Watchdog-managed hermes serve port; 9120/8787/9920 remain reserved ops ports.
    # Desktop connects via desktop-backend.json / HERMES_DESKTOP_REMOTE_*; default 9119.
    [int]$ManagedBackendPort = 9119
)

$ErrorActionPreference = "Stop"
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$RepoRoot = if ($HermesRoot) { $HermesRoot } else { (Resolve-Path (Join-Path $ScriptDir "..\..")).Path }
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
    $proc = Start-Process -FilePath "powershell.exe" `
        -ArgumentList (@("-NoProfile", "-ExecutionPolicy", "Bypass", "-File", $BuildScript) + $argList) `
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

if (-not (Test-Path -LiteralPath $Exe)) {
    if ($BuildIfMissing) {
        $buildScript = Join-Path $ScriptDir "Build-HermesGoWatchdog.ps1"
        try {
            Invoke-GoWatchdogBuildBounded -BuildScript $buildScript -TimeoutSec $BuildTimeoutSec -SkipTest:(-not $RunBuildTests)
        } catch {
            Write-Warning $_.Exception.Message
            Write-Warning "Skipping Go watchdog start — run Build-HermesGoWatchdog.ps1 manually when ready."
            exit 0
        }
        if (-not (Test-Path -LiteralPath $Exe)) {
            Write-Warning "Build finished but missing $Exe — skipping Go watchdog start."
            exit 0
        }
    } else {
        throw "Missing $Exe — run Build-HermesGoWatchdog.ps1 first or pass -BuildIfMissing"
    }
}

$DataDir = Join-Path $env:LOCALAPPDATA "HermesWatchdog"
$LockPath = Join-Path $DataDir "watchdog.lock"

function Test-GoWatchdogAlive {
    if (-not (Test-Path -LiteralPath $LockPath)) { return $false }
    try {
        $obj = Get-Content -LiteralPath $LockPath -Raw | ConvertFrom-Json
        $pidLock = [int]$obj.pid
        if ($pidLock -le 0) { return $false }
        $proc = Get-Process -Id $pidLock -ErrorAction SilentlyContinue
        return [bool]$proc
    } catch {
        return $false
    }
}

function Stop-GoWatchdog {
    if (Test-GoWatchdogAlive) {
        try {
            $obj = Get-Content -LiteralPath $LockPath -Raw | ConvertFrom-Json
            Stop-Process -Id ([int]$obj.pid) -Force -ErrorAction SilentlyContinue
            Start-Sleep -Seconds 1
        } catch {}
    }
    Get-Process -Name hermes-watchdog -ErrorAction SilentlyContinue | ForEach-Object {
        Stop-Process -Id $_.Id -Force -ErrorAction SilentlyContinue
    }
    Remove-Item -LiteralPath $LockPath -Force -ErrorAction SilentlyContinue
}

function Stop-PsDesktopBackendWatchdog {
    # PS and Go watchdogs use different lock files — running both causes dual
    # Hermes.exe relaunch loops. Prefer Go; stop the legacy PS mutual watchdog.
    $psLock = Join-Path $HermesHome "logs\desktop-backend-watchdog.lock"
    if (Test-Path -LiteralPath $psLock) {
        try {
            $obj = Get-Content -LiteralPath $psLock -Raw | ConvertFrom-Json
            if ($obj.pid) {
                Stop-Process -Id ([int]$obj.pid) -Force -ErrorAction SilentlyContinue
            }
        } catch {}
        Remove-Item -LiteralPath $psLock -Force -ErrorAction SilentlyContinue
    }
    Get-CimInstance Win32_Process -Property ProcessId, CommandLine -OperationTimeoutSec 8 -ErrorAction SilentlyContinue | Where-Object {
        $_.CommandLine -and $_.CommandLine -match 'Start-HermesDesktopBackendWatchdog\.ps1'
    } | ForEach-Object {
        Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue
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

Stop-PsDesktopBackendWatchdog

if ($ForceRestart -or $Once) {
    Stop-GoWatchdog
} elseif (Test-GoWatchdogAlive) {
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
    Write-Warning "Go watchdog may still be starting — check $(Join-Path $HermesHome 'logs\hermes-go-watchdog.log')"
}
