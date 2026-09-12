#Requires -Version 5.1
<#
.SYNOPSIS
  Recover Desktop <-> managed backend attach when CONNECTING hangs.

.DESCRIPTION
  Elevated operator path:
  1) Clear burned recovery-budget.json
  2) Force-restart Go watchdog (kills elevated zombie :9119 occupant)
  3) Wait for %LOCALAPPDATA%\HermesWatchdog\desktop-backend.json
  4) Relaunch packaged Desktop via start-hermes-desktop.ps1 (local+prewarm)

.EXAMPLE
  powershell -NoProfile -ExecutionPolicy Bypass -File scripts\windows\Recover-DesktopBackendAttach.ps1
#>
param(
    [string]$HermesRoot = "",
    [string]$HermesHome = "",
    [int]$ManagedBackendPort = 9119,
    [int]$ManifestWaitSeconds = 90
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
    $argList += @("-ManagedBackendPort", "$ManagedBackendPort", "-ManifestWaitSeconds", "$ManifestWaitSeconds")
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
$manifestPath = Join-Path $dataDir "desktop-backend.json"
$budgetPath = Join-Path $dataDir "recovery-budget.json"
$goWatchdog = Join-Path $HermesRoot "scripts\windows\Start-HermesGoWatchdog.ps1"
$desktopStart = Join-Path $HermesRoot "scripts\windows\start-hermes-desktop.ps1"
$utf8NoBom = New-Object System.Text.UTF8Encoding $false

function Write-Recover([string]$Message) {
    Write-Host ("[{0}] {1}" -f (Get-Date -Format "HH:mm:ss"), $Message)
}

if (-not (Test-Path -LiteralPath $goWatchdog)) {
    throw "Missing Start-HermesGoWatchdog.ps1 at $goWatchdog"
}
if (-not (Test-Path -LiteralPath $desktopStart)) {
    throw "Missing start-hermes-desktop.ps1 at $desktopStart"
}

Write-Recover ("elevated recover root={0} home={1} port={2}" -f $HermesRoot, $HermesHome, $ManagedBackendPort)

function Get-ListeningPidsOnPort([int]$Port) {
    $pids = New-Object System.Collections.Generic.HashSet[int]
    try {
        $conns = Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue
        foreach ($c in @($conns)) {
            if ($c.OwningProcess -gt 0) { [void]$pids.Add([int]$c.OwningProcess) }
        }
    } catch {
        # Fallback: netstat parse when Get-NetTCPConnection is unavailable.
        $lines = netstat -ano | Select-String (":{0}\s+.*LISTENING\s+(\d+)" -f $Port)
        foreach ($m in $lines) {
            if ($m.Matches.Count -gt 0) {
                $pidText = $m.Matches[0].Groups[1].Value
                $pidVal = 0
                if ([int]::TryParse($pidText, [ref]$pidVal) -and $pidVal -gt 0) {
                    [void]$pids.Add($pidVal)
                }
            }
        }
    }
    return @($pids)
}

function Stop-PortOccupants([int]$Port) {
    # Go watchdog waitManagedPortCleared is observational only — it never
    # TerminateProcess foreign squatters. Operator recover must force-clear.
    for ($round = 1; $round -le 3; $round++) {
        $owners = @(Get-ListeningPidsOnPort -Port $Port)
        if ($owners.Count -eq 0) {
            Write-Recover ("port {0} clear (round {1})" -f $Port, $round)
            return $true
        }
        foreach ($ownerPid in $owners) {
            Write-Recover ("force-clear port {0} occupant pid={1} (round {2})" -f $Port, $ownerPid, $round)
            & taskkill.exe /F /T /PID $ownerPid 2>$null | Out-Null
            Stop-Process -Id $ownerPid -Force -ErrorAction SilentlyContinue
        }
        Start-Sleep -Seconds 2
    }
    $left = @(Get-ListeningPidsOnPort -Port $Port)
    if ($left.Count -gt 0) {
        Write-Recover ("WARN port {0} still held by pid(s)={1}" -f $Port, ($left -join ","))
        return $false
    }
    return $true
}

# 1) Clear burned recovery budget (no BOM)
if (Test-Path -LiteralPath $budgetPath) {
    $stamp = Get-Date -Format "yyyyMMddHHmmss"
    Copy-Item -LiteralPath $budgetPath -Destination ("{0}.bak-attach-{1}" -f $budgetPath, $stamp) -Force
    Remove-Item -LiteralPath $budgetPath -Force
    Write-Recover "cleared recovery-budget.json"
}

# 2) Stop visible Desktop so it re-attaches after fresh manifest
Get-Process -Name "Hermes" -ErrorAction SilentlyContinue | ForEach-Object {
    Write-Recover ("stopping Hermes pid={0}" -f $_.Id)
    Stop-Process -Id $_.Id -Force -ErrorAction SilentlyContinue
}
Start-Sleep -Seconds 2

# 2b) Force-clear managed port squatters BEFORE watchdog ForceRestart.
# Without this, EnsureHealthy logs "replacing occupant" then only waits 15s.
if (-not (Stop-PortOccupants -Port $ManagedBackendPort)) {
    throw ("Could not free managed port {0}; refuse to wait forever for desktop-backend.json" -f $ManagedBackendPort)
}

# 3) Force-restart Go watchdog (prewarm + publish desktop-backend.json)
Write-Recover "ForceRestart Go watchdog"
& powershell.exe -NoProfile -ExecutionPolicy Bypass -File $goWatchdog `
    -HermesRoot $HermesRoot `
    -HermesHome $HermesHome `
    -ManagedBackendPort $ManagedBackendPort `
    -ForceRestart `
    -BuildIfMissing
if ($LASTEXITCODE -ne 0 -and $null -ne $LASTEXITCODE) {
    throw "Start-HermesGoWatchdog exited $LASTEXITCODE"
}

# Budget may refill during ForceRestart flap — clear again before wait.
if (Test-Path -LiteralPath $budgetPath) {
    Remove-Item -LiteralPath $budgetPath -Force -ErrorAction SilentlyContinue
    Write-Recover "re-cleared recovery-budget.json after ForceRestart"
}

# 4) Wait for auth-ready manifest
$deadline = (Get-Date).AddSeconds($ManifestWaitSeconds)
$ready = $false
while ((Get-Date) -lt $deadline) {
    if (Test-Path -LiteralPath $manifestPath) {
        try {
            $raw = [System.IO.File]::ReadAllText($manifestPath, $utf8NoBom)
            $m = $raw | ConvertFrom-Json
            $base = [string]$m.baseUrl
            $token = [string]$m.token
            if (-not [string]::IsNullOrWhiteSpace($base) -and -not [string]::IsNullOrWhiteSpace($token)) {
                $sessionsUrl = $base.TrimEnd("/") + "/api/sessions"
                $resp = Invoke-WebRequest -Uri $sessionsUrl -Headers @{
                    Authorization = ("Bearer " + $token)
                    "X-Hermes-Session-Token" = $token
                } -UseBasicParsing -TimeoutSec 5
                if ($resp.StatusCode -ge 200 -and $resp.StatusCode -lt 300) {
                    Write-Recover ("manifest auth-ok url={0}" -f $base)
                    $ready = $true
                    break
                }
            }
        } catch {
            Write-Recover ("manifest present but not auth-ready yet: {0}" -f $_.Exception.Message)
        }
    } else {
        Write-Recover "waiting for desktop-backend.json..."
    }
    Start-Sleep -Seconds 2
}

if (-not $ready) {
    throw "Timed out waiting for auth-ready desktop-backend.json (${ManifestWaitSeconds}s)"
}

# 5) Strip sticky Remote env and relaunch Desktop local+prewarm
Remove-Item Env:HERMES_DESKTOP_REMOTE_URL -ErrorAction SilentlyContinue
Remove-Item Env:HERMES_DESKTOP_REMOTE_TOKEN -ErrorAction SilentlyContinue
Write-Recover "launching Desktop via start-hermes-desktop.ps1"
& powershell.exe -NoProfile -ExecutionPolicy Bypass -File $desktopStart `
    -HermesRoot $HermesRoot `
    -Cwd $HermesRoot `
    -HermesHome $HermesHome
Write-Recover ("desktop launcher exit={0}" -f $LASTEXITCODE)

Start-Sleep -Seconds 6
$visible = @(Get-Process -Name "Hermes" -ErrorAction SilentlyContinue | Where-Object { $_.MainWindowHandle -ne [IntPtr]::Zero })
$port0 = @(Get-CimInstance Win32_Process -ErrorAction SilentlyContinue | Where-Object {
    $_.CommandLine -and $_.CommandLine -match 'serve --host 127\.0\.0\.1 --port 0'
})
Write-Recover ("visibleHermes={0} port0Serve={1} manifestExists={2}" -f $visible.Count, $port0.Count, (Test-Path -LiteralPath $manifestPath))

if ($visible.Count -lt 1) {
    throw "Desktop did not show a visible window"
}
if ($port0.Count -gt 0) {
    Write-Warning "Desktop still owns a port-0 serve; CONNECTING may persist. Re-run this script."
    exit 2
}

Write-Recover "RECOVER_OK: managed backend attach path ready"
exit 0
