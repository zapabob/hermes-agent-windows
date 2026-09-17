#Requires -Version 5.1
<#
.SYNOPSIS
  Duty-separated Desktop recovery after CONNECTING / attach flaps.

.DESCRIPTION
  Elevated operator path aligned with the single-owner contract:
  1) Clear burned recovery-budget.json
  2) Identity-bound ForceRestart of observation-only Go watchdog
     (embedding supervisor only; no managed-backend / prewarm / manifest)
  3) Relaunch packaged Desktop via start-hermes-desktop.ps1
     (Electron owns Desktop + Python backend)

  Obsolete managed-backend attach (desktop-backend.json / port 9119 prewarm)
  is intentionally not restored.

.EXAMPLE
  powershell -NoProfile -ExecutionPolicy Bypass -File scripts\windows\Recover-DesktopBackendAttach.ps1
#>
param(
    [string]$HermesRoot = "",
    [string]$HermesHome = "",
    # Accepted for old operator muscle-memory; ignored (no managed backend).
    [int]$ManagedBackendPort = 0,
    [int]$ManifestWaitSeconds = 0
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
    $argList = @(
        "-NoProfile",
        "-ExecutionPolicy", "Bypass",
        "-File", "`"$PSCommandPath`""
    )
    if (-not [string]::IsNullOrWhiteSpace($HermesRoot)) {
        $argList += @("-HermesRoot", "`"$HermesRoot`"")
    }
    if (-not [string]::IsNullOrWhiteSpace($HermesHome)) {
        $argList += @("-HermesHome", "`"$HermesHome`"")
    }
    $proc = Start-Process -FilePath "powershell.exe" -ArgumentList $argList -Verb RunAs -Wait -PassThru
    exit $proc.ExitCode
}

if ([string]::IsNullOrWhiteSpace($HermesRoot)) {
    $HermesRoot = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
}
if ([string]::IsNullOrWhiteSpace($HermesHome)) {
    if (-not [string]::IsNullOrWhiteSpace($env:HERMES_HOME)) {
        $HermesHome = $env:HERMES_HOME
    } else {
        $HermesHome = Join-Path $env:USERPROFILE ".hermes"
    }
}

$dataDir = Join-Path $env:LOCALAPPDATA "HermesWatchdog"
$budgetPath = Join-Path $dataDir "recovery-budget.json"
$staleManifest = Join-Path $dataDir "desktop-backend.json"
$goWatchdog = Join-Path $HermesRoot "scripts\windows\Start-HermesGoWatchdog.ps1"
$desktopStart = Join-Path $HermesRoot "scripts\windows\start-hermes-desktop.ps1"

function Write-Recover([string]$Message) {
    Write-Host ("[{0}] {1}" -f (Get-Date -Format "HH:mm:ss"), $Message)
}

if (-not (Test-Path -LiteralPath $goWatchdog)) {
    throw "Missing Start-HermesGoWatchdog.ps1 at $goWatchdog"
}
if (-not (Test-Path -LiteralPath $desktopStart)) {
    throw "Missing start-hermes-desktop.ps1 at $desktopStart"
}

if ($ManagedBackendPort -gt 0 -or $ManifestWaitSeconds -gt 0) {
    Write-Recover ("obsolete managed-backend args ignored (ManagedBackendPort={0} ManifestWaitSeconds={1})" -f $ManagedBackendPort, $ManifestWaitSeconds)
}

Write-Recover ("elevated duty-separated recover root={0} home={1}" -f $HermesRoot, $HermesHome)

# 1) Clear burned recovery budget
if (Test-Path -LiteralPath $budgetPath) {
    $stamp = Get-Date -Format "yyyyMMddHHmmss"
    Copy-Item -LiteralPath $budgetPath -Destination ("{0}.bak-attach-{1}" -f $budgetPath, $stamp) -Force
    Remove-Item -LiteralPath $budgetPath -Force
    Write-Recover "cleared recovery-budget.json"
}

# Quarantine stale prewarm manifest if present (never adopt as authority).
if (Test-Path -LiteralPath $staleManifest) {
    $bak = "{0}.bak-attach-{1}" -f $staleManifest, (Get-Date -Format "yyyyMMddHHmmss")
    Move-Item -LiteralPath $staleManifest -Destination $bak -Force
    Write-Recover ("quarantined obsolete desktop-backend.json -> {0}" -f $bak)
}

# 2) Identity-bound ForceRestart of observation-only Go watchdog
Write-Recover "ForceRestart observation-only Go watchdog"
& powershell.exe -NoProfile -ExecutionPolicy Bypass -File $goWatchdog `
    -HermesRoot $HermesRoot `
    -HermesHome $HermesHome `
    -ForceRestart `
    -BuildIfMissing
if ($LASTEXITCODE -ne 0 -and $null -ne $LASTEXITCODE) {
    throw "Start-HermesGoWatchdog exited $LASTEXITCODE"
}

if (Test-Path -LiteralPath $budgetPath) {
    Remove-Item -LiteralPath $budgetPath -Force -ErrorAction SilentlyContinue
    Write-Recover "re-cleared recovery-budget.json after ForceRestart"
}

# 3) Electron owns Desktop + backend — relaunch via canonical launcher
Remove-Item Env:HERMES_DESKTOP_REMOTE_URL -ErrorAction SilentlyContinue
Remove-Item Env:HERMES_DESKTOP_REMOTE_TOKEN -ErrorAction SilentlyContinue
Write-Recover "launching Desktop via start-hermes-desktop.ps1 (Electron owns backend)"
& powershell.exe -NoProfile -ExecutionPolicy Bypass -File $desktopStart `
    -HermesRoot $HermesRoot `
    -Cwd $HermesRoot `
    -HermesHome $HermesHome
Write-Recover ("desktop launcher exit={0}" -f $LASTEXITCODE)

Start-Sleep -Seconds 6
$visible = @(Get-Process -Name "Hermes" -ErrorAction SilentlyContinue | Where-Object { $_.MainWindowHandle -ne [IntPtr]::Zero })
Write-Recover ("visibleHermes={0}" -f $visible.Count)

if ($visible.Count -lt 1) {
    throw "Desktop did not show a visible window"
}

Write-Recover "RECOVER_OK: duty-separated Desktop recover complete (watchdog observation-only)"
exit 0
