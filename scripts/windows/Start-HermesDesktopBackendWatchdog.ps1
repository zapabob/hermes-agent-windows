# Compatibility shim for installations whose scheduled task still references
# the former PowerShell watchdog. The Go watchdog is observation-only for
# Desktop/backend and owns embedding supervision only; this script may
# bootstrap it, but never probes, kills, or restarts Desktop/backend itself.

[CmdletBinding()]
param(
    [int]$IntervalSec = 20,
    [switch]$Once,
    [string]$HermesRoot = "",
    [string]$HermesHome = "",
    # Accepted for backward compatibility with old task registrations; ignored.
    [int]$FailThreshold = 0,
    [int]$StartupGraceSec = 0,
    [int]$ManagedBackendPort = 0
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$RepoRootCandidate = if ($HermesRoot) { $HermesRoot } else { Join-Path $ScriptDir "..\.." }
$RepoRoot = (Resolve-Path -LiteralPath $RepoRootCandidate -ErrorAction Stop).Path
if (-not $HermesHome) { $HermesHome = Join-Path $env:USERPROFILE ".hermes" }

$LogDir = Join-Path $HermesHome "logs"
New-Item -ItemType Directory -Force -Path $LogDir | Out-Null
$LogPath = Join-Path $LogDir "desktop-backend-watchdog.log"

function Write-WdLog([string]$Message) {
    $line = "[{0}] {1}" -f (Get-Date -Format "yyyy-MM-dd HH:mm:ss"), $Message
    Add-Content -LiteralPath $LogPath -Value $line -Encoding UTF8
    Write-Host $line
}

if ($FailThreshold -gt 0 -or $StartupGraceSec -gt 0 -or $ManagedBackendPort -gt 0) {
    Write-WdLog ("obsolete managed-backend args ignored (FailThreshold={0} StartupGraceSec={1} ManagedBackendPort={2})" -f $FailThreshold, $StartupGraceSec, $ManagedBackendPort)
}

$GoLauncher = Join-Path $ScriptDir "Start-HermesGoWatchdog.ps1"
if (-not (Test-Path -LiteralPath $GoLauncher)) {
    throw "Go watchdog launcher is missing: $GoLauncher"
}

$launcherArgs = @{
    IntervalSec    = $IntervalSec
    HermesRoot     = $RepoRoot
    HermesHome     = $HermesHome
    BuildIfMissing = $true
}
if ($Once) { $launcherArgs.Once = $true }

Write-WdLog "legacy PowerShell watchdog delegated to observation-only Go watchdog (embedding supervisor)"
& $GoLauncher @launcherArgs
