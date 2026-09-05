# Operator-approved lifecycle bridge for planned Hermes installation removal.
[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [ValidateSet("Uninstall")]
    [string]$Action,

    [Parameter(Mandatory = $true)]
    [string]$MaintenanceFile,

    [Parameter(Mandatory = $true)]
    [string]$MaintenanceNonce,

    [Parameter(Mandatory = $true)]
    [string]$HermesRoot,

    [Parameter(Mandatory = $true)]
    [string]$HermesHome
)

Set-StrictMode -Version Latest
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

function Get-NormalizedPath {
    param([Parameter(Mandatory = $true)][string]$Path)
    return [System.IO.Path]::GetFullPath($Path).TrimEnd('\')
}

function Test-SamePath {
    param(
        [Parameter(Mandatory = $true)][string]$Left,
        [Parameter(Mandatory = $true)][string]$Right
    )
    return [string]::Equals(
        (Get-NormalizedPath $Left),
        (Get-NormalizedPath $Right),
        [System.StringComparison]::OrdinalIgnoreCase
    )
}

if (-not (Test-IsElevatedOperator)) {
    throw "Operator approval is required for the Go watchdog lifecycle path."
}

$maintenancePath = (Resolve-Path -LiteralPath $MaintenanceFile -ErrorAction Stop).Path
$rootPath = (Resolve-Path -LiteralPath $HermesRoot -ErrorAction Stop).Path
$homePath = Get-NormalizedPath $HermesHome
$state = Get-Content -LiteralPath $maintenancePath -Raw -Encoding utf8 | ConvertFrom-Json -ErrorAction Stop

if ([string]$state.state -ne "UPDATE") {
    throw "Watchdog lifecycle requires an active UPDATE maintenance state."
}
if (-not [string]::Equals(
    [string]$state.nonce,
    $MaintenanceNonce,
    [System.StringComparison]::Ordinal
)) {
    throw "Watchdog maintenance nonce does not match the lifecycle request."
}
if (-not (Test-SamePath ([string]$state.repoRoot) $rootPath)) {
    throw "Watchdog maintenance repository identity does not match."
}

$expiresAt = [DateTimeOffset]::Parse(
    [string]$state.leaseExpiresAt,
    [Globalization.CultureInfo]::InvariantCulture,
    [Globalization.DateTimeStyles]::RoundtripKind
)
if ($expiresAt -le [DateTimeOffset]::UtcNow) {
    throw "Watchdog maintenance lease expired before lifecycle execution."
}

$ownerPid = [int]$state.pid
if ($ownerPid -le 0 -or [string]$state.owner -ne ("hermes-update:{0}" -f $ownerPid)) {
    throw "Watchdog maintenance owner identity is invalid."
}
$ownerProcess = Get-Process -Id $ownerPid -ErrorAction Stop
$epoch = [DateTimeOffset]::UnixEpoch
$ownerStarted = [DateTimeOffset]$ownerProcess.StartTime.ToUniversalTime()
$ownerStartSeconds = ($ownerStarted - $epoch).TotalSeconds
if ([math]::Abs($ownerStartSeconds - [double]$state.processStartTime) -gt 0.1) {
    throw "Watchdog maintenance owner process identity changed."
}

$launcher = Join-Path $rootPath "scripts\windows\Start-HermesGoWatchdog.ps1"
if (-not (Test-Path -LiteralPath $launcher -PathType Leaf)) {
    throw "Missing operator Go watchdog launcher: $launcher"
}

$taskName = "HermesGoWatchdogBootAutoStart"
$task = Get-ScheduledTask -TaskName $taskName -ErrorAction SilentlyContinue
if ($task) {
    $actionText = @($task.Actions | ForEach-Object {
        "{0} {1}" -f [string]$_.Execute, [string]$_.Arguments
    }) -join " "
    if (
        $actionText.IndexOf(
            $launcher,
            [System.StringComparison]::OrdinalIgnoreCase
        ) -lt 0
    ) {
        throw "Refusing to alter a foreign scheduled task named $taskName."
    }
    Disable-ScheduledTask -TaskName $taskName -ErrorAction Stop | Out-Null
}

& $launcher -Stop -HermesRoot $rootPath -HermesHome $homePath
if ($LASTEXITCODE -ne 0) {
    throw "Operator Go watchdog launcher refused the planned stop."
}

if ($task) {
    Unregister-ScheduledTask -TaskName $taskName -Confirm:$false -ErrorAction Stop
}
if (Get-ScheduledTask -TaskName $taskName -ErrorAction SilentlyContinue) {
    throw "Go watchdog startup task still exists after uninstall decommission."
}

[pscustomobject]@{
    action = $Action
    watchdogStopped = $true
    startupTaskRemoved = $true
    maintenanceOwner = [string]$state.owner
} | ConvertTo-Json -Compress
