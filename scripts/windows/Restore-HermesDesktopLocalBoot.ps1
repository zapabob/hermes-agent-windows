#Requires -Version 5.1
<#
.SYNOPSIS
  Restore classic Desktop local boot (Electron-owned serve) when CONNECTING sticks.

.DESCRIPTION
  Identity-bound stop of the observation-only Go watchdog, quarantines any
  stale desktop-backend.json leftover from the removed prewarm path, and
  launches Desktop via start-hermes-desktop.ps1 -ForceLocalSpawn.
  After Desktop is up, restarts the observation-only Go watchdog (embedding
  supervisor only — it does not republish managed-backend manifests).

.EXAMPLE
  powershell -NoProfile -ExecutionPolicy Bypass -File scripts\windows\Restore-HermesDesktopLocalBoot.ps1
#>
param(
    [string]$HermesRoot = "",
    [string]$HermesHome = ""
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

if (-not (Test-IsElevatedOperator)) {
    Write-Host "Not elevated; re-launching with UAC (click Yes)..."
    $argList = @("-NoProfile", "-ExecutionPolicy", "Bypass", "-File", "`"$PSCommandPath`"")
    if (-not [string]::IsNullOrWhiteSpace($HermesRoot)) { $argList += @("-HermesRoot", "`"$HermesRoot`"") }
    if (-not [string]::IsNullOrWhiteSpace($HermesHome)) { $argList += @("-HermesHome", "`"$HermesHome`"") }
    $proc = Start-Process -FilePath "powershell.exe" -ArgumentList $argList -Verb RunAs -Wait -PassThru
    exit $proc.ExitCode
}

if ([string]::IsNullOrWhiteSpace($HermesRoot)) {
    $HermesRoot = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
}
if ([string]::IsNullOrWhiteSpace($HermesHome)) {
    $HermesHome = if ($env:HERMES_HOME) { $env:HERMES_HOME } else { Join-Path $env:USERPROFILE ".hermes" }
}

$desktopStart = Join-Path $HermesRoot "scripts\windows\start-hermes-desktop.ps1"
$goWatchdog = Join-Path $HermesRoot "scripts\windows\Start-HermesGoWatchdog.ps1"
$dataDir = Join-Path $env:LOCALAPPDATA "HermesWatchdog"
$manifest = Join-Path $dataDir "desktop-backend.json"

function Write-Restore([string]$Message) {
    Write-Host ("[{0}] {1}" -f (Get-Date -Format "HH:mm:ss"), $Message)
}

Write-Restore ("restore local boot root={0}" -f $HermesRoot)

if (Test-Path -LiteralPath $goWatchdog) {
    Write-Restore "identity-bound stop of observation-only Go watchdog"
    & powershell.exe -NoProfile -ExecutionPolicy Bypass -File $goWatchdog `
        -HermesRoot $HermesRoot `
        -HermesHome $HermesHome `
        -Stop
} else {
    Write-Restore "WARN: Start-HermesGoWatchdog.ps1 missing; skipping watchdog stop"
}

Write-Restore "stopping visible Hermes Desktop (operator recover)"
Get-Process -Name "Hermes" -ErrorAction SilentlyContinue | ForEach-Object {
    Stop-Process -Id $_.Id -Force -ErrorAction SilentlyContinue
}
Start-Sleep -Seconds 2

# Clear burned recovery so a later watchdog start is not circuit-open.
$budget = Join-Path $dataDir "recovery-budget.json"
if (Test-Path -LiteralPath $budget) {
    Remove-Item -LiteralPath $budget -Force -ErrorAction SilentlyContinue
    Write-Restore "cleared recovery-budget.json"
}

if (Test-Path -LiteralPath $manifest) {
    $bak = "{0}.bak-restorelocal-{1}" -f $manifest, (Get-Date -Format "yyyyMMddHHmmss")
    Move-Item -LiteralPath $manifest -Destination $bak -Force
    Write-Restore ("quarantined obsolete manifest -> {0}" -f $bak)
}

Write-Restore "launching Desktop -ForceLocalSpawn (Electron owns backend)"
& powershell.exe -NoProfile -ExecutionPolicy Bypass -File $desktopStart `
    -HermesRoot $HermesRoot `
    -Cwd $HermesRoot `
    -HermesHome $HermesHome `
    -ForceLocalSpawn

Write-Restore ("desktop launcher exit={0}" -f $LASTEXITCODE)

if (Test-Path -LiteralPath $goWatchdog) {
    Write-Restore "restarting observation-only Go watchdog (embedding supervisor)"
    & powershell.exe -NoProfile -ExecutionPolicy Bypass -File $goWatchdog `
        -HermesRoot $HermesRoot `
        -HermesHome $HermesHome `
        -BuildIfMissing
}

Write-Restore "RESTORE_OK: classic local boot requested"
exit 0
