#Requires -Version 5.1
<#
.SYNOPSIS
  Restore classic Desktop local boot (owned serve --port 0) when CONNECTING sticks on prewarm.

.DESCRIPTION
  Stops elevated watchdog (so it cannot republish desktop-backend.json / relaunch
  elevated ghosts), quarantines the prewarm manifest, and launches Desktop via
  start-hermes-desktop.ps1 -ForceLocalSpawn (Medium IL when elevated).

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
$dataDir = Join-Path $env:LOCALAPPDATA "HermesWatchdog"
$manifest = Join-Path $dataDir "desktop-backend.json"

function Write-Restore([string]$Message) {
    Write-Host ("[{0}] {1}" -f (Get-Date -Format "HH:mm:ss"), $Message)
}

Write-Restore ("restore local boot root={0}" -f $HermesRoot)

Write-Restore "stopping Hermes + hermes-watchdog"
Get-Process -Name "Hermes","hermes-watchdog" -ErrorAction SilentlyContinue | Stop-Process -Force -ErrorAction SilentlyContinue
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
    Write-Restore ("quarantined manifest -> {0}" -f $bak)
}

Write-Restore "launching Desktop -ForceLocalSpawn"
& powershell.exe -NoProfile -ExecutionPolicy Bypass -File $desktopStart `
    -HermesRoot $HermesRoot `
    -Cwd $HermesRoot `
    -HermesHome $HermesHome `
    -ForceLocalSpawn

Write-Restore ("desktop launcher exit={0}" -f $LASTEXITCODE)
Write-Restore "Do NOT restart Go watchdog until CONNECTING clears (watchdog republishes prewarm)."
Write-Restore "RESTORE_OK: classic local boot requested"
exit 0
