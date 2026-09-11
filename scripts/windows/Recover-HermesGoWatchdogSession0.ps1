# Operator recovery: displace Session 0 Go watchdog into the interactive session.
$ErrorActionPreference = "Stop"
$root = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
$log = Join-Path $env:TEMP "hermes-watchdog-session0-recover.log"
$go = Join-Path $root "scripts\windows\Start-HermesGoWatchdog.ps1"
if (-not [string]::IsNullOrWhiteSpace($env:HERMES_HOME)) {
    $HermesHome = $env:HERMES_HOME
} else {
    $HermesHome = Join-Path $env:USERPROFILE ".hermes"
}
$data = Join-Path $env:LOCALAPPDATA "HermesWatchdog"

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
    $proc = Start-Process -FilePath "powershell.exe" -ArgumentList $argList -Verb RunAs -Wait -PassThru
    exit $proc.ExitCode
}

function Write-Recover([string]$Message) {
    $line = "[{0}] {1}" -f (Get-Date -Format o), $Message
    Add-Content -LiteralPath $log -Value $line
    Write-Host $line
}

Remove-Item -LiteralPath $log -Force -ErrorAction SilentlyContinue
Write-Recover ("session={0} elevated={1}" -f (Get-Process -Id $PID).SessionId, ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator))

$budget = Join-Path $data "recovery-budget.json"
if (Test-Path -LiteralPath $budget) {
    Copy-Item -LiteralPath $budget -Destination ("{0}.bak-{1}" -f $budget, (Get-Date -Format yyyyMMddHHmmss)) -Force
    Remove-Item -LiteralPath $budget -Force
    Write-Recover "cleared recovery-budget.json"
}

$user = [Security.Principal.WindowsIdentity]::GetCurrent().Name
$settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -StartWhenAvailable -MultipleInstances IgnoreNew -ExecutionTimeLimit ([TimeSpan]::Zero)

# One-shot S4U stopper: same session class as the boot-time owner, so Terminate works.
$stopCmd = "`$env:HERMES_HOME='$HermesHome'; & '$go' -Stop -HermesRoot '$root' -HermesHome '$HermesHome'"
$stopAction = New-ScheduledTaskAction -Execute "powershell.exe" -Argument "-NoProfile -WindowStyle Hidden -ExecutionPolicy Bypass -Command $stopCmd" -WorkingDirectory $root
$stopPrincipal = New-ScheduledTaskPrincipal -UserId $user -LogonType S4U -RunLevel Highest
Register-ScheduledTask -TaskName "HermesGoWatchdogSession0StopOnce" -Action $stopAction -Principal $stopPrincipal -Settings $settings -Description "One-shot S4U stop for Session 0 Go watchdog displace" -Force | Out-Null
Write-Recover "registered HermesGoWatchdogSession0StopOnce"
Start-ScheduledTask -TaskName "HermesGoWatchdogSession0StopOnce"
Start-Sleep -Seconds 5
$stopInfo = Get-ScheduledTaskInfo -TaskName "HermesGoWatchdogSession0StopOnce"
Write-Recover ("S4U stop result={0}" -f $stopInfo.LastTaskResult)

$alive = Get-Process -Name "hermes-watchdog" -ErrorAction SilentlyContinue
if ($alive) {
    Write-Recover ("watchdog still alive pid={0} session={1}; trying elevated Stop-Process" -f $alive.Id, $alive.SessionId)
    Stop-Process -Id $alive.Id -Force -ErrorAction SilentlyContinue
    Start-Sleep -Seconds 2
}
$alive = Get-Process -Name "hermes-watchdog" -ErrorAction SilentlyContinue
if ($alive) {
    Write-Recover ("RECOVER_FAIL: watchdog still alive pid={0}" -f $alive.Id)
    exit 1
}
Write-Recover "Session 0 watchdog stopped"

$lock = Join-Path $data "watchdog.lock"
if (Test-Path -LiteralPath $lock) {
    Remove-Item -LiteralPath $lock -Force -ErrorAction SilentlyContinue
    Write-Recover "removed stale lock"
}

$logonCmd = "`$env:HERMES_HOME='$HermesHome'; & '$go' -HermesRoot '$root' -HermesHome '$HermesHome' -ManagedBackendPort 9119"
$logonAction = New-ScheduledTaskAction -Execute "powershell.exe" -Argument "-NoProfile -WindowStyle Hidden -ExecutionPolicy Bypass -Command $logonCmd" -WorkingDirectory $root
$logonTrigger = New-ScheduledTaskTrigger -AtLogOn -User $user
$logonTrigger.Delay = "PT20S"
$logonPrincipal = New-ScheduledTaskPrincipal -UserId $user -LogonType Interactive -RunLevel Highest
Register-ScheduledTask -TaskName "HermesGoWatchdogLogonAutoStart" -Action $logonAction -Trigger $logonTrigger -Principal $logonPrincipal -Settings $settings -Description "Logon displace Session 0 Go watchdog into the interactive desktop session" -Force | Out-Null

& $go -HermesRoot $root -HermesHome $HermesHome -ManagedBackendPort 9119
Start-Sleep -Seconds 4
$wd = Get-Process -Name "hermes-watchdog" -ErrorAction SilentlyContinue | Select-Object -First 1
if (-not $wd) {
    Write-Recover "RECOVER_FAIL: interactive watchdog did not start"
    exit 1
}
Write-Recover ("watchdog pid={0} session={1}" -f $wd.Id, $wd.SessionId)
if ([int]$wd.SessionId -eq 0) {
    Write-Recover "RECOVER_FAIL: watchdog still Session 0"
    exit 1
}

if (-not (Get-Process -Name "Hermes" -ErrorAction SilentlyContinue)) {
    Start-ScheduledTask -TaskName "HermesDesktopAutoStart"
    Start-Sleep -Seconds 8
}
$desk = @(Get-Process -Name "Hermes" -ErrorAction SilentlyContinue)
Write-Recover ("desktop count={0}" -f $desk.Count)

$maint = Join-Path $data "maintenance.json"
if (Test-Path -LiteralPath $maint) {
    $now = Get-Date
    $cleared = @{
        schemaVersion = 1
        state = "NORMAL"
        owner = "hermes-operator-session0-displace"
        nonce = ([guid]::NewGuid().ToString("N"))
        epoch = [int64]([DateTimeOffset]$now.ToUniversalTime()).ToUnixTimeMilliseconds() * 1000
        timestamp = $now.ToUniversalTime().ToString("o")
        reason = "Session 0 displace completed; resume watchdog supervision"
        leaseSeconds = 0
        leaseExpiresAt = $now.ToUniversalTime().ToString("o")
        pid = $PID
        processStartTime = $null
        repoRoot = $root
    }
    $json = ($cleared | ConvertTo-Json -Depth 5) + "`n"
    [System.IO.File]::WriteAllText($maint, $json, [System.Text.UTF8Encoding]::new($false))
    Write-Recover "cleared OPERATOR_SESSION0_DISPLACE maintenance fence"
}

Unregister-ScheduledTask -TaskName "HermesGoWatchdogSession0StopOnce" -Confirm:$false -ErrorAction SilentlyContinue
Write-Recover "RECOVER_OK"
exit 0
