# Reconcile the Hermes boot/logon tasks with this canonical checkout.
#
# This script only replaces the named Hermes tasks. It does not remove other
# scheduled tasks, change the current service processes, or touch user files.

[CmdletBinding()]
param(
    [string]$HermesHome = "",
    [switch]$VerifyOnly,
    [switch]$StartNow
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

function Test-IsAdmin {
    $identity = [Security.Principal.WindowsIdentity]::GetCurrent()
    $principal = [Security.Principal.WindowsPrincipal]::new($identity)
    return $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
}

if (-not $VerifyOnly -and -not (Test-IsAdmin)) {
    $arguments = @(
        "-NoProfile",
        "-ExecutionPolicy", "Bypass",
        "-File", "`"$PSCommandPath`""
    )
    if ($HermesHome) {
        $arguments += @("-HermesHome", "`"$HermesHome`"")
    }
    if ($StartNow) {
        $arguments += "-StartNow"
    }

    $elevated = Start-Process -FilePath "powershell.exe" -ArgumentList $arguments -Verb RunAs -Wait -PassThru
    exit $elevated.ExitCode
}

$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$repoRoot = (Resolve-Path (Join-Path $scriptDir "..\..")).Path
if (-not $HermesHome) {
    $HermesHome = Join-Path $env:USERPROFILE ".hermes"
}
$currentUser = [Security.Principal.WindowsIdentity]::GetCurrent().Name
$pythonExe = Join-Path $repoRoot ".venv\Scripts\python.exe"
if (-not (Test-Path -LiteralPath $pythonExe)) {
    $pythonExe = Join-Path $repoRoot "venv\Scripts\python.exe"
}

$paths = @{
    GoWatchdog = Join-Path $scriptDir "Start-HermesGoWatchdog.ps1"
    Gateway = Join-Path $scriptDir "start-hermes-gateway.ps1"
    Dashboard = Join-Path $scriptDir "start-hermes-dashboard.ps1"
    MemoryGraph = Join-Path $scriptDir "start-obsidian-memory-graph-server.ps1"
    Desktop = Join-Path $scriptDir "start-hermes-desktop.ps1"
}
foreach ($path in $paths.Values) {
    if (-not (Test-Path -LiteralPath $path -PathType Leaf)) {
        throw "Required Hermes launcher not found: $path"
    }
}
if (-not (Test-Path -LiteralPath $pythonExe -PathType Leaf)) {
    throw "Repository Python runtime not found under $repoRoot"
}

function Escape-PowerShellLiteral {
    param([Parameter(Mandatory = $true)][string]$Value)
    return $Value -replace "'", "''"
}

function New-TaskSettings {
    New-ScheduledTaskSettingsSet `
        -AllowStartIfOnBatteries `
        -DontStopIfGoingOnBatteries `
        -StartWhenAvailable `
        -MultipleInstances IgnoreNew `
        -ExecutionTimeLimit ([TimeSpan]::Zero)
}

function Register-HermesTask {
    param(
        [Parameter(Mandatory = $true)][string]$TaskName,
        [Parameter(Mandatory = $true)][string]$Description,
        [Parameter(Mandatory = $true)][string]$Command,
        [Parameter(Mandatory = $true)][string]$WorkingDirectory,
        [ValidateSet("Boot", "Logon")][string]$TriggerKind,
        [int]$DelaySeconds,
        [ValidateSet("Limited", "Highest")][string]$RunLevel = "Limited"
    )

    $action = New-ScheduledTaskAction `
        -Execute "powershell.exe" `
        -Argument "-NoProfile -WindowStyle Hidden -ExecutionPolicy Bypass -Command $Command" `
        -WorkingDirectory $WorkingDirectory
    if ($TriggerKind -eq "Boot") {
        $trigger = New-ScheduledTaskTrigger -AtStartup
        $principal = New-ScheduledTaskPrincipal -UserId $currentUser -LogonType S4U -RunLevel Highest
    } else {
        $trigger = New-ScheduledTaskTrigger -AtLogOn -User $currentUser
        $principal = New-ScheduledTaskPrincipal -UserId $currentUser -LogonType Interactive -RunLevel $RunLevel
    }
    if ($DelaySeconds -gt 0) {
        $trigger.Delay = "PT${DelaySeconds}S"
    }

    Register-ScheduledTask `
        -TaskName $TaskName `
        -Action $action `
        -Trigger $trigger `
        -Principal $principal `
        -Settings (New-TaskSettings) `
        -Description $Description `
        -Force | Out-Null
    Write-Host "Registered $TriggerKind task: $TaskName (RunLevel=$($principal.RunLevel))"
}

$homeLiteral = Escape-PowerShellLiteral $HermesHome
$rootLiteral = Escape-PowerShellLiteral $repoRoot
$goLiteral = Escape-PowerShellLiteral $paths.GoWatchdog
$gatewayLiteral = Escape-PowerShellLiteral $paths.Gateway
$dashboardLiteral = Escape-PowerShellLiteral $paths.Dashboard
$memoryLiteral = Escape-PowerShellLiteral $paths.MemoryGraph
$desktopLiteral = Escape-PowerShellLiteral $paths.Desktop
$pythonLiteral = Escape-PowerShellLiteral $pythonExe

$envPrefix = "`$env:HERMES_HOME='$homeLiteral'; "
$gatewayEnvPrefix = "$envPrefix`$env:HERMES_STARTUP_DELAY_SECONDS='20'; `$env:HERMES_GATEWAY_WINDOW_STYLE='Hidden'; "

$taskCommands = @{
    HermesGoWatchdogBootAutoStart = "$envPrefix& '$goLiteral' -HermesRoot '$rootLiteral' -HermesHome '$homeLiteral' -ManagedBackendPort 9119"
    HermesGoWatchdogLogonAutoStart = "$envPrefix& '$goLiteral' -HermesRoot '$rootLiteral' -HermesHome '$homeLiteral' -ManagedBackendPort 9119"
    HermesGatewayBootAutoStart = "$gatewayEnvPrefix& '$gatewayLiteral'"
    HermesHypuraHarnessBootAutoStart = "$envPrefix& '$pythonLiteral' -m hermes_cli.main harness start"
    HermesMemoryGraphBootAutoStart = "$envPrefix& '$memoryLiteral'"
    HermesDashboardBootAutoStart = "$envPrefix& '$dashboardLiteral' -HermesRoot '$rootLiteral' -HermesHome '$homeLiteral' -HostName '127.0.0.1' -Port 9120"
    HermesDesktopAutoStart = "$envPrefix& '$desktopLiteral' -HermesRoot '$rootLiteral' -Cwd '$rootLiteral' -HermesHome '$homeLiteral'"
    HermesDashboardAutoStart = "$envPrefix& '$dashboardLiteral' -HermesRoot '$rootLiteral' -HermesHome '$homeLiteral' -HostName '127.0.0.1' -Port 9120"
    HermesMemoryGraphAutoStart = "$envPrefix& '$memoryLiteral'"
}

$taskSpecs = @(
    @{Name = "HermesGoWatchdogBootAutoStart"; Kind = "Boot"; Delay = 15; RunLevel = "Highest"; Description = "Boot auto-start Hermes Go watchdog from the canonical checkout"; WorkingDirectory = $repoRoot},
    @{Name = "HermesGoWatchdogLogonAutoStart"; Kind = "Logon"; Delay = 20; RunLevel = "Highest"; Description = "Logon displace Session 0 Go watchdog into the interactive desktop session"; WorkingDirectory = $repoRoot},
    @{Name = "HermesGatewayBootAutoStart"; Kind = "Boot"; Delay = 20; RunLevel = "Highest"; Description = "Boot auto-start Hermes Gateway from the canonical checkout"; WorkingDirectory = $repoRoot},
    @{Name = "HermesHypuraHarnessBootAutoStart"; Kind = "Boot"; Delay = 40; RunLevel = "Highest"; Description = "Boot auto-start Hypura Harness from the canonical checkout"; WorkingDirectory = $repoRoot},
    @{Name = "HermesMemoryGraphBootAutoStart"; Kind = "Boot"; Delay = 55; RunLevel = "Highest"; Description = "Boot auto-start Hermes MemoryGraph from the canonical checkout"; WorkingDirectory = $repoRoot},
    @{Name = "HermesDashboardBootAutoStart"; Kind = "Boot"; Delay = 70; RunLevel = "Highest"; Description = "Boot auto-start Hermes Dashboard from the canonical checkout"; WorkingDirectory = $repoRoot},
    @{Name = "HermesDesktopAutoStart"; Kind = "Logon"; Delay = 90; RunLevel = "Limited"; Description = "Logon auto-start Hermes Desktop through the canonical launcher"; WorkingDirectory = $repoRoot},
    @{Name = "HermesDashboardAutoStart"; Kind = "Logon"; Delay = 75; RunLevel = "Limited"; Description = "Logon auto-start Hermes Dashboard from the canonical checkout"; WorkingDirectory = $repoRoot},
    @{Name = "HermesMemoryGraphAutoStart"; Kind = "Logon"; Delay = 78; RunLevel = "Limited"; Description = "Logon auto-start Hermes MemoryGraph from the canonical checkout"; WorkingDirectory = $repoRoot}
)

if (-not $VerifyOnly) {
    foreach ($spec in $taskSpecs) {
        Register-HermesTask `
            -TaskName $spec.Name `
            -Description $spec.Description `
            -Command $taskCommands[$spec.Name] `
            -WorkingDirectory $spec.WorkingDirectory `
            -TriggerKind $spec.Kind `
            -DelaySeconds $spec.Delay `
            -RunLevel $spec.RunLevel
    }
}

if ($StartNow) {
    foreach ($spec in $taskSpecs) {
        Start-ScheduledTask -TaskName $spec.Name
        Start-Sleep -Seconds 3
        $info = Get-ScheduledTaskInfo -TaskName $spec.Name
        Write-Host ("Started {0}: result={1}, lastRun={2}" -f $spec.Name, $info.LastTaskResult, $info.LastRunTime)
    }
}

$oldRoot = "hermes-agent-hakua-production"
$report = foreach ($spec in $taskSpecs) {
    $task = Get-ScheduledTask -TaskName $spec.Name -ErrorAction Stop
    $info = Get-ScheduledTaskInfo -TaskName $spec.Name -ErrorAction Stop
    $actionText = @($task.Actions | ForEach-Object { "$($_.Execute) $($_.Arguments) $($_.WorkingDirectory)" }) -join " | "
    [pscustomobject]@{
        TaskName = $spec.Name
        State = [string]$task.State
        Trigger = $spec.Kind
        OldRootReferenced = $actionText -match [regex]::Escape($oldRoot)
        LastTaskResult = $info.LastTaskResult
        LastRunTime = $info.LastRunTime
        Action = $actionText
    }
}
$report | Format-Table -Wrap -AutoSize
if (@($report | Where-Object { $_.OldRootReferenced }).Count -gt 0) {
    throw "At least one repaired task still references the legacy checkout."
}
