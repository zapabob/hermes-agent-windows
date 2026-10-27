param(
    [string]$OutputDirectory = 'C:\Users\downl\Documents\New project\hermes-agent\output\reports'
)

$ErrorActionPreference = 'Continue'
$ProgressPreference = 'SilentlyContinue'
$timestamp = Get-Date
$runId = $timestamp.ToString('yyyyMMdd-HHmmss')
New-Item -ItemType Directory -Force -Path $OutputDirectory | Out-Null

function Test-HttpEndpoint([string]$Uri) {
    try {
        $response = Invoke-WebRequest -UseBasicParsing -Uri $Uri -TimeoutSec 5
        return [ordered]@{ ok = ($response.StatusCode -eq 200); status = $response.StatusCode; error = $null }
    } catch {
        return [ordered]@{ ok = $false; status = $null; error = $_.Exception.Message }
    }
}

function Get-HermesConfigValue([string]$Key) {
    try {
        $value = (& hermes config get $Key 2>$null | Out-String).Trim()
        if ($LASTEXITCODE -eq 0) { return $value }
    } catch {}
    return $null
}

$defender = $null
try {
    $mp = Get-MpComputerStatus
    $defender = [ordered]@{
        antivirus_enabled = $mp.AntivirusEnabled
        antispyware_enabled = $mp.AntispywareEnabled
        real_time_protection_enabled = $mp.RealTimeProtectionEnabled
        behavior_monitor_enabled = $mp.BehaviorMonitorEnabled
        ioav_protection_enabled = $mp.IoavProtectionEnabled
        signatures_last_updated = $mp.AntivirusSignatureLastUpdated
        quick_scan_age_days = $mp.QuickScanAge
        full_scan_age_days = $mp.FullScanAge
    }
} catch {
    $defender = [ordered]@{ error = $_.Exception.Message }
}

$firewall = @()
try {
    $firewall = @(Get-NetFirewallProfile | ForEach-Object {
        [ordered]@{
            name = $_.Name
            enabled = $_.Enabled
            default_inbound_action = [string]$_.DefaultInboundAction
            default_outbound_action = [string]$_.DefaultOutboundAction
        }
    })
} catch {
    $firewall = @([ordered]@{ error = $_.Exception.Message })
}

$listeners = @()
try {
    $listeners = @(Get-NetTCPConnection -State Listen | Sort-Object LocalPort | ForEach-Object {
        $processName = $null
        try { $processName = (Get-Process -Id $_.OwningProcess -ErrorAction Stop).ProcessName } catch {}
        [ordered]@{
            address = $_.LocalAddress
            port = $_.LocalPort
            pid = $_.OwningProcess
            process = $processName
            exposure = if ($_.LocalAddress -in @('127.0.0.1', '::1')) { 'loopback' } else { 'network' }
        }
    })
} catch {
    $listeners = @([ordered]@{ error = $_.Exception.Message })
}

$dockerContainers = @()
try {
    $rows = & docker ps --format '{{json .}}' 2>$null
    if ($LASTEXITCODE -eq 0) {
        $dockerContainers = @($rows | ForEach-Object { $_ | ConvertFrom-Json })
    }
} catch {}

$supplyChain = $null
try {
    $auditRaw = & hermes security audit --json 2>$null | Out-String
    if (-not [string]::IsNullOrWhiteSpace($auditRaw)) {
        $supplyChain = $auditRaw | ConvertFrom-Json
    }
} catch {
    $supplyChain = [ordered]@{ error = $_.Exception.Message }
}

$startupShortcut = Join-Path $env:APPDATA 'Microsoft\Windows\Start Menu\Programs\Startup\ARTEX-Auto.lnk'
$report = [ordered]@{
    schema = 'hermes-blue-team-local-v1'
    run_id = $runId
    timestamp = $timestamp.ToString('o')
    scope = 'local-machine-only'
    constraints = @('no remote scanning', 'no exploitation', 'no persistence changes', 'no credential output')
    integration = [ordered]@{
        hermes_gateway = Test-HttpEndpoint 'http://127.0.0.1:8642/health'
        artex = Test-HttpEndpoint 'http://127.0.0.1:8788/api/health'
        hikari_backend = Test-HttpEndpoint 'http://127.0.0.1:8080/v1/models'
        moa_provider = Get-HermesConfigValue 'model.provider'
        moa_preset = Get-HermesConfigValue 'model.default'
        approvals_mode = Get-HermesConfigValue 'approvals.mode'
        startup_shortcut_present = Test-Path -LiteralPath $startupShortcut
    }
    endpoint_protection = $defender
    firewall_profiles = $firewall
    tcp_listeners = $listeners
    docker_containers = $dockerContainers
    supply_chain = $supplyChain
}

$findings = [System.Collections.Generic.List[object]]::new()
if ($report.integration.hermes_gateway.ok -ne $true) {
    $findings.Add([ordered]@{ severity = 'high'; control = 'integration'; finding = 'Hermes Gateway API is unavailable.' })
}
if ($report.integration.artex.ok -ne $true) {
    $findings.Add([ordered]@{ severity = 'high'; control = 'integration'; finding = 'ARTEX health endpoint is unavailable.' })
}
if ($report.integration.hikari_backend.ok -ne $true) {
    $findings.Add([ordered]@{ severity = 'high'; control = 'model'; finding = 'Hikari local model backend is unavailable.' })
}
if ($report.integration.moa_provider -ne 'moa') {
    $findings.Add([ordered]@{ severity = 'medium'; control = 'model'; finding = 'Hermes default provider is not MoA.' })
}
if ($report.integration.approvals_mode -eq 'off') {
    $findings.Add([ordered]@{ severity = 'high'; control = 'approvals'; finding = 'Hermes dangerous-command approvals are disabled.' })
}
if ($defender.real_time_protection_enabled -ne $true) {
    $findings.Add([ordered]@{ severity = 'critical'; control = 'endpoint'; finding = 'Microsoft Defender real-time protection is not enabled.' })
}
foreach ($profile in $firewall) {
    if ($profile.enabled -eq $false) {
        $findings.Add([ordered]@{ severity = 'high'; control = 'firewall'; finding = "Firewall profile $($profile.name) is disabled." })
    }
}
$networkListeners = @($listeners | Where-Object { $_.exposure -eq 'network' })
if ($networkListeners.Count -gt 0) {
    $findings.Add([ordered]@{ severity = 'info'; control = 'exposure'; finding = "$($networkListeners.Count) TCP listeners are bound beyond loopback; review the report." })
}
$report.findings = @($findings)

$jsonPath = Join-Path $OutputDirectory "blue-team-$runId.json"
$mdPath = Join-Path $OutputDirectory "blue-team-$runId.md"
$report | ConvertTo-Json -Depth 12 | Set-Content -LiteralPath $jsonPath -Encoding UTF8

$lines = [System.Collections.Generic.List[string]]::new()
$lines.Add('# Hermes Local Blue-Team Exercise')
$lines.Add('')
$lines.Add("- Run: `$runId`")
$lines.Add("- Time: `$($timestamp.ToString('o'))`")
$lines.Add('- Scope: local machine only; no remote scanning or exploitation')
$lines.Add('')
$lines.Add('## Integration')
$lines.Add("- Hermes Gateway: $($report.integration.hermes_gateway.ok)")
$lines.Add("- ARTEX: $($report.integration.artex.ok)")
$lines.Add("- Hikari backend: $($report.integration.hikari_backend.ok)")
$lines.Add("- Hermes provider/preset: $($report.integration.moa_provider) / $($report.integration.moa_preset)")
$lines.Add("- Startup shortcut: $($report.integration.startup_shortcut_present)")
$lines.Add('')
$lines.Add('## Findings')
if ($findings.Count -eq 0) {
    $lines.Add('- No findings from the checks executed.')
} else {
    foreach ($finding in $findings) {
        $lines.Add("- **$($finding.severity.ToUpperInvariant())** [$($finding.control)] $($finding.finding)")
    }
}
$lines.Add('')
$lines.Add('## Evidence')
$lines.Add("- Full machine-readable evidence: `$jsonPath`")
$lines.Add("- TCP listeners observed: $($listeners.Count)")
$lines.Add("- Network-bound listeners: $($networkListeners.Count)")
$lines.Add("- Docker containers observed: $($dockerContainers.Count)")
$lines | Set-Content -LiteralPath $mdPath -Encoding UTF8

[ordered]@{
    ok = ($findings | Where-Object { $_.severity -in @('critical', 'high') }).Count -eq 0
    run_id = $runId
    report = $mdPath
    evidence = $jsonPath
    findings = @($findings)
} | ConvertTo-Json -Depth 6
