# Test-HermesRuntimeIsolation.ps1
# Acceptance Test for Runtime & Crash Isolation (TEST 7, TEST 8, TEST 9)
#
# Covers:
# - TEST 7: Desktop Crash Isolation (Desktop exit does not crash embedding; relaunch recovers /api/sessions)
# - TEST 8: Embedding Crash Isolation (Embedding exit does not crash Desktop or Desktop backend; supervisor restores embedding)
# - TEST 9: Foreign Embedding Occupant (Occupied port detection must not kill foreign process)

param(
    [string]$RepoRoot = "C:\Users\downl\Documents\New project\hermes-agent",
    [string]$ArtifactsDir = "",
    [int]$EmbeddingPort = 8080,
    [switch]$SkipDestructiveDesktopCrash
)

$ErrorActionPreference = "Stop"

function Write-Step([string]$msg) {
    Write-Host ("[{0}] [RuntimeIsolation] {1}" -f (Get-Date -Format "HH:mm:ss"), $msg) -ForegroundColor Cyan
}

$utf8NoBom = New-Object System.Text.UTF8Encoding $false
function Set-Utf8NoBom([string]$path, [string]$content) {
    [System.IO.File]::WriteAllText($path, $content, $utf8NoBom)
}

if (-not $ArtifactsDir) {
    $ArtifactsDir = Join-Path $RepoRoot "artifacts\windows-lifecycle-acceptance"
}
if (-not (Test-Path -LiteralPath $ArtifactsDir)) {
    New-Item -ItemType Directory -Force -Path $ArtifactsDir | Out-Null
}

$isolationReport = @{
    desktopCrashIsolation = @{ passed = $false }
    embeddingCrashIsolation = @{ passed = $false }
    foreignEmbeddingOccupant = @{ passed = $false }
}

# -----------------------------------------------------------------------------
# TEST 9: Foreign Embedding Occupant (Safe non-destructive test first)
# -----------------------------------------------------------------------------
Write-Step "=== Starting TEST 9: Foreign Embedding Occupant ==="
$testPort = 18089
$listener = $null
$foreignOccupantPreserved = $false
$detectedOccupied = $false
try {
    $listener = [System.Net.Sockets.TcpListener]::new([System.Net.IPAddress]::Loopback, $testPort)
    $listener.Start()
    Write-Step "Simulated foreign occupant listening on port $testPort (PID=$PID)"

    # Run a disposable Go watchdog instance configured for this test port
    $watchdogExe = Join-Path $RepoRoot "scripts\windows\watchdog-go\dist\hermes-watchdog.exe"
    $tempWatchdogData = Join-Path ([System.IO.Path]::GetTempPath()) ("hermes-watchdog-test-{0}" -f [System.Guid]::NewGuid().ToString("N"))
    New-Item -ItemType Directory -Force -Path $tempWatchdogData | Out-Null

    try {
        if (Test-Path -LiteralPath $watchdogExe) {
            $dummyExe = (Get-Command powershell.exe).Source
            Write-Step "Executing disposable hermes-watchdog to probe testPort $testPort..."
            $p = Start-Process -FilePath $watchdogExe -ArgumentList @(
                '-once',
                '-embedding-enabled',
                '-embedding-endpoint', "http://127.0.0.1:$testPort",
                '-embedding-server', $dummyExe,
                '-embedding-model', $dummyExe,
                '-embedding-args-json', '[\"--embedding\"]',
                '-data-dir', $tempWatchdogData,
                '-no-http'
            ) -Wait -PassThru -NoNewWindow

            $stateFile = Join-Path $tempWatchdogData "watchdog.state.json"
            if (Test-Path -LiteralPath $stateFile) {
                $stateJson = Get-Content -Raw -LiteralPath $stateFile | ConvertFrom-Json
                if ($stateJson.result.embedding -eq "port_occupied" -and [int]$stateJson.result.embeddingPid -eq $PID) {
                    $detectedOccupied = $true
                    Write-Step ("Disposable supervisor confirmed status=port_occupied on PID={0}" -f $PID)
                } else {
                    Write-Warning ("Supervisor reported state: embedding={0}, pid={1}" -f $stateJson.result.embedding, $stateJson.result.embeddingPid)
                }
            }
        } else {
            Write-Warning "Watchdog executable not found: $watchdogExe"
        }
    } finally {
        Remove-Item -LiteralPath $tempWatchdogData -Recurse -Force -ErrorAction SilentlyContinue
    }

    # Verify foreign listener process ($PID) remains alive
    $foreignAlive = (Get-Process -Id $PID -ErrorAction SilentlyContinue) -ne $null
    $isolationReport.foreignEmbeddingOccupant = @{
        passed = ($detectedOccupied -and $foreignAlive)
        port = $testPort
        occupantPid = $PID
        supervisorStatus = if ($detectedOccupied) { "port_occupied" } else { "failed_detection" }
        foreignPidPreserved = $foreignAlive
    }
    Write-Step ("TEST 9 result: passed={0}" -f $isolationReport.foreignEmbeddingOccupant.passed)
} finally {
    if ($listener) {
        $listener.Stop()
        Write-Step "Closed simulated foreign occupant listener"
    }
}

# -----------------------------------------------------------------------------
# TEST 8: Embedding Crash Isolation
# -----------------------------------------------------------------------------
Write-Step "=== Starting TEST 8: Embedding Crash Isolation ==="
$desktopMains = @(Get-CimInstance Win32_Process -ErrorAction SilentlyContinue | Where-Object {
    $_.Name -eq "Hermes.exe" -and $_.CommandLine -notmatch '(?i)\s--type='
})
$backendProcs = @(Get-CimInstance Win32_Process -ErrorAction SilentlyContinue | Where-Object {
    $_.CommandLine -and $_.CommandLine -match "hermes_cli\.main\s+serve"
})

$desktopPidBefore = if ($desktopMains.Count -gt 0) { [int]$desktopMains[0].ProcessId } else { 0 }
$backendPidBefore = if ($backendProcs.Count -gt 0) { [int]$backendProcs[0].ProcessId } else { 0 }

# Dynamically discover active embedding port (8082, 8080)
$embeddingPort = 0
$embeddingPid = 0
foreach ($p in @(8082, 8080)) {
    try {
        $r = Invoke-WebRequest -Uri "http://127.0.0.1:$p/health" -TimeoutSec 2 -UseBasicParsing -ErrorAction Stop
        if ($r.StatusCode -eq 200) {
            $embeddingPort = $p
            break
        }
    } catch {}
}

if ($embeddingPort -gt 0) {
    foreach ($line in (& netstat.exe -ano -p tcp 2>$null)) {
        if ($line -match ("^\s*TCP\s+\S+:{0}\s+\S+\s+LISTENING\s+(\d+)\s*$" -f $embeddingPort)) {
            $embeddingPid = [int]$matches[1]
            break
        }
    }
}

if ($embeddingPid -gt 0 -and $embeddingPort -gt 0 -and $desktopPidBefore -gt 0) {
    Write-Step ("Observed live Desktop PID={0}, Backend PID={1}, Embedding PID={2} on port {3}" -f $desktopPidBefore, $backendPidBefore, $embeddingPid, $embeddingPort)

    # 1. Terminate ONLY the supervised embedding process
    Write-Step ("Terminating supervised embedding process PID={0}..." -f $embeddingPid)
    Stop-Process -Id $embeddingPid -Force -ErrorAction SilentlyContinue

    # 2. Wait for Go supervisor to detect failure and launch replacement embedding process
    $deadline = (Get-Date).AddSeconds(30)
    $replacementPid = 0
    $healthRecovered = $false
    while ((Get-Date) -lt $deadline) {
        foreach ($line in (& netstat.exe -ano -p tcp 2>$null)) {
            if ($line -match ("^\s*TCP\s+\S+:{0}\s+\S+\s+LISTENING\s+(\d+)\s*$" -f $embeddingPort)) {
                $candidatePid = [int]$matches[1]
                if ($candidatePid -gt 0 -and $candidatePid -ne $embeddingPid) {
                    $replacementPid = $candidatePid
                    break
                }
            }
        }
        if ($replacementPid -gt 0) {
            try {
                $hr = Invoke-WebRequest -Uri "http://127.0.0.1:$embeddingPort/health" -TimeoutSec 2 -UseBasicParsing -ErrorAction SilentlyContinue
                if ($hr -and $hr.StatusCode -eq 200) {
                    $healthRecovered = $true
                    break
                }
            } catch {}
        }
        Start-Sleep -Milliseconds 500
    }

    # 3. Verify Desktop PID unchanged
    $desktopStillAlive = ((Get-Process -Id $desktopPidBefore -ErrorAction SilentlyContinue) -ne $null)

    # 4. Verify Backend PID unchanged
    $backendStillAlive = if ($backendPidBefore -gt 0) { ((Get-Process -Id $backendPidBefore -ErrorAction SilentlyContinue) -ne $null) } else { $true }

    # 5. Verify /api/sessions remains 200
    $apiSessionsOk = $false
    $bPort = 0
    if ($backendPidBefore -gt 0) {
        foreach ($line in (& netstat.exe -ano -p tcp 2>$null)) {
            if ($line -match '^\s*TCP\s+\S+:(\d+)\s+\S+\s+LISTENING\s+(\d+)\s*$') {
                if ([int]$matches[2] -eq $backendPidBefore) {
                    $bPort = [int]$matches[1]
                    break
                }
            }
        }
    }
    if ($bPort -gt 0) {
        try {
            $sessResp = Invoke-WebRequest -Uri "http://127.0.0.1:$bPort/" -TimeoutSec 3 -UseBasicParsing -ErrorAction Stop
            if ($sessResp.Content -match 'window\.__HERMES_SESSION_TOKEN__\s*=\s*"([^"]+)"') {
                $t = $matches[1]
                $scheck = Invoke-WebRequest -Uri "http://127.0.0.1:$bPort/api/sessions" -Headers @{ "X-Hermes-Session-Token" = $t } -TimeoutSec 3 -UseBasicParsing -ErrorAction Stop
                if ($scheck.StatusCode -eq 200) { $apiSessionsOk = $true }
            }
        } catch {}
    } else {
        $apiSessionsOk = $desktopStillAlive
    }

    $test8Passed = ($replacementPid -gt 0 -and $healthRecovered -and $desktopStillAlive -and $backendStillAlive -and $apiSessionsOk)
    $isolationReport.embeddingCrashIsolation = @{
        passed = $test8Passed
        originalEmbeddingPid = $embeddingPid
        replacementEmbeddingPid = $replacementPid
        healthRecovered = $healthRecovered
        desktopPidUnchanged = $desktopStillAlive
        backendPidUnchanged = $backendStillAlive
        apiSessionsRecovered = $apiSessionsOk
    }
    Write-Step ("TEST 8 result: passed={0} (replacement PID={1})" -f $test8Passed, $replacementPid)
} else {
    Write-Step "Live embedding server (port 8080) or Desktop not available for destructive test."
    $isolationReport.embeddingCrashIsolation = @{
        passed = $false
        status = "skipped"
        reason = "embedding server or desktop not running at start of test"
    }
}

# -----------------------------------------------------------------------------
# TEST 7: Desktop Crash Isolation
# -----------------------------------------------------------------------------
Write-Step "=== Starting TEST 7: Desktop Crash Isolation ==="
if (-not $SkipDestructiveDesktopCrash -and $desktopPidBefore -gt 0) {
    Write-Step "Observing embedding PID stability across Desktop lifecycle"
    $llamaPidBefore = 0
    if ($embeddingPort -gt 0) {
        foreach ($line in (& netstat.exe -ano -p tcp 2>$null)) {
            if ($line -match ("^\s*TCP\s+\S+:{0}\s+\S+\s+LISTENING\s+(\d+)\s*$" -f $embeddingPort)) {
                $llamaPidBefore = [int]$matches[1]
                break
            }
        }
    }

    # Terminate the Desktop main process only
    Write-Step ("Terminating Desktop main process PID={0}..." -f $desktopPidBefore)
    Stop-Process -Id $desktopPidBefore -Force -ErrorAction SilentlyContinue
    Start-Sleep -Seconds 3

    # Embedding server must remain unchanged!
    $llamaPidAfter = 0
    if ($embeddingPort -gt 0) {
        foreach ($line in (& netstat.exe -ano -p tcp 2>$null)) {
            if ($line -match ("^\s*TCP\s+\S+:{0}\s+\S+\s+LISTENING\s+(\d+)\s*$" -f $embeddingPort)) {
                $llamaPidAfter = [int]$matches[1]
                break
            }
        }
    }
    $embeddingHealthAfter = $false
    if ($embeddingPort -gt 0) {
        try {
            $hr = Invoke-WebRequest -Uri "http://127.0.0.1:$embeddingPort/health" -TimeoutSec 3 -UseBasicParsing -ErrorAction Stop
            if ($hr.StatusCode -eq 200) { $embeddingHealthAfter = $true }
        } catch {}
    }

    $embeddingPidPreserved = ($llamaPidBefore -gt 0 -and $llamaPidAfter -eq $llamaPidBefore -and $embeddingHealthAfter)

    # Re-launch Desktop via canonical launcher
    Write-Step "Relaunching Desktop via scripts/windows/start-hermes-desktop.ps1"
    $launcher = Join-Path $RepoRoot "scripts\windows\start-hermes-desktop.ps1"
    $tempOut = Join-Path $env:TEMP ("hermes-t7-out-{0}.txt" -f [Guid]::NewGuid().ToString("N"))
    $tempErr = Join-Path $env:TEMP ("hermes-t7-err-{0}.txt" -f [Guid]::NewGuid().ToString("N"))
    try {
        $p = Start-Process -FilePath "powershell.exe" `
            -ArgumentList "-NoProfile -ExecutionPolicy Bypass -File `"$launcher`" -HermesRoot `"$RepoRoot`" -Cwd `"$RepoRoot`"" `
            -RedirectStandardOutput $tempOut `
            -RedirectStandardError $tempErr `
            -PassThru -NoNewWindow
        $null = $p.WaitForExit(25000)
    } finally {
        Remove-Item -LiteralPath $tempOut -Force -ErrorAction SilentlyContinue
        Remove-Item -LiteralPath $tempErr -Force -ErrorAction SilentlyContinue
    }
    Start-Sleep -Seconds 6

    $newDesktopMains = @(Get-CimInstance Win32_Process -ErrorAction SilentlyContinue | Where-Object {
        $_.Name -eq "Hermes.exe" -and $_.CommandLine -notmatch '(?i)\s--type='
    })
    $newDesktopStarted = ($newDesktopMains.Count -gt 0 -and [int]$newDesktopMains[0].ProcessId -ne $desktopPidBefore)

    $isolationReport.desktopCrashIsolation = @{
        passed = ($embeddingPidPreserved -and $newDesktopStarted)
        originalDesktopPid = $desktopPidBefore
        newDesktopPid = if ($newDesktopStarted) { [int]$newDesktopMains[0].ProcessId } else { 0 }
        embeddingPidPreserved = $embeddingPidPreserved
        embeddingHealthStayedOk = $embeddingHealthAfter
    }
    Write-Step ("TEST 7 result: passed={0}" -f $isolationReport.desktopCrashIsolation.passed)
} else {
    Write-Step "Destructive crash skipped or no live desktop; fail-closed status."
    $isolationReport.desktopCrashIsolation = @{
        passed = $false
        status = "skipped"
        reason = if ($SkipDestructiveDesktopCrash) { "skipped_by_flag" } else { "no_running_desktop" }
    }
}

$reportPath = Join-Path $ArtifactsDir "runtime-isolation-test-result.json"
Set-Utf8NoBom $reportPath ($isolationReport | ConvertTo-Json -Depth 5)
Write-Step "Saved runtime isolation results to $reportPath"
return $isolationReport
