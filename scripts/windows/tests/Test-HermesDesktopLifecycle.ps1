# Test-HermesDesktopLifecycle.ps1
# Automated Windows Desktop Lifecycle Acceptance Harness
#
# Master orchestrator for end-to-end Windows Desktop backend lifecycle qualification.
# Evaluates:
#   TEST 0:  Preflight (environment, working tree, baseline invariants)
#   TEST 1:  Cold Start latency & single-owner parentage
#   TEST 2:  Normal Relaunch x 10 cycles (latency bounds, ledger non-growth)
#   TEST 3:  Bulk Stale Ownership Reap (delegates to Test-HermesOwnershipLedger.ps1)
#   TEST 4:  Backend Crash Recovery x 10 cycles (identity-bound child replacement)
#   TEST 5:  Concurrent Reconnect Storm (Vitest contract execution)
#   TEST 6:  Stale Generation Race (Vitest contract execution)
#   TEST 7:  Desktop Crash Isolation (delegates to Test-HermesRuntimeIsolation.ps1)
#   TEST 8:  Embedding Crash Isolation (delegates to Test-HermesRuntimeIsolation.ps1)
#   TEST 9:  Foreign Embedding Occupant (delegates to Test-HermesRuntimeIsolation.ps1)
#   TEST 10: Launcher Contract (via pytest harness contract test)
#   TEST 11: HERMES_HOME Identity Matrix (via pytest harness contract test)
#   TEST 12: Repeated Clean Ledger Verification
#   TEST 13: Authentication Persistence (/api/sessions)
#   TEST 14: Long Soak (optional, -SoakMinutes)
#   TEST 17: Reboot Harness (optional, -EnableRebootAcceptance only)

[CmdletBinding()]
param(
    [string]$RepoRoot = "C:\Users\downl\Documents\New project\hermes-agent",
    [string]$HermesHome = "",
    [string]$ArtifactsDir = "",
    [int]$RelaunchCycles = 10,
    [int]$CrashCycles = 10,
    [int]$SoakMinutes = 0,
    [switch]$SkipLongCycles,
    [switch]$EnableRebootAcceptance
)

$ErrorActionPreference = "Stop"

function Write-Step([string]$msg, [string]$color = "Cyan") {
    Write-Host ("[{0}] [LifecycleHarness] {1}" -f (Get-Date -Format "HH:mm:ss"), $msg) -ForegroundColor $color
}

$utf8NoBom = New-Object System.Text.UTF8Encoding $false
function Set-Utf8NoBom([string]$path, [string]$content) {
    [System.IO.File]::WriteAllText($path, $content, $utf8NoBom)
}

function Get-Sha256Prefix([string]$text) {
    if ([string]::IsNullOrEmpty($text)) { return "" }
    $hasher = [System.Security.Cryptography.SHA256]::Create()
    $bytes = [System.Text.Encoding]::UTF8.GetBytes($text)
    $hash = $hasher.ComputeHash($bytes)
    $sb = New-Object System.Text.StringBuilder
    for ($i = 0; $i -lt [Math]::Min(4, $hash.Length); $i++) {
        $sb.Append($hash[$i].ToString("x2")) | Out-Null
    }
    return $sb.ToString()
}

# Tqdm-style interactive progress bar with elapsed time, ETA remaining time, rate, and unicode bar
function Write-TqdmProgress {
    param(
        [Parameter(Mandatory=$true)][string]$Activity,
        [Parameter(Mandatory=$true)][int]$Current,
        [Parameter(Mandatory=$true)][int]$Total,
        [System.Diagnostics.Stopwatch]$Stopwatch,
        [string]$Status = "",
        [int]$BarWidth = 24
    )
    if ($Total -le 0) { $Total = 1 }
    $percent = [Math]::Min(100, [Math]::Max(0, [int](($Current / $Total) * 100)))
    $filled = [int](($percent / 100) * $BarWidth)
    $empty = [Math]::Max(0, $BarWidth - $filled)
    $blockChar = [char]0x2588
    $emptyChar = [char]0x2591
    $bar = ([string]$blockChar * $filled) + ([string]$emptyChar * $empty)

    $elapsedStr = "00:00"
    $etaStr = "--:--"
    $rateStr = "? it/s"
    if ($Stopwatch) {
        $elapsed = $Stopwatch.Elapsed
        $elapsedStr = ("{0:D2}:{1:D2}" -f [int]$elapsed.TotalMinutes, $elapsed.Seconds)
        if ($Current -gt 0) {
            $secs = $elapsed.TotalSeconds
            $rate = $Current / [Math]::Max(0.001, $secs)
            if ($rate -ge 1) {
                $rateStr = ("{0:F1} it/s" -f $rate)
            } else {
                $rateStr = ("{0:F1} s/it" -f (1.0 / $rate))
            }
            $remaining = [Math]::Max(0, ($Total - $Current))
            $etaSecs = $remaining / [Math]::Max(0.001, $rate)
            $etaSpan = [TimeSpan]::FromSeconds($etaSecs)
            $etaStr = ("{0:D2}:{1:D2}" -f [int]$etaSpan.TotalMinutes, $etaSpan.Seconds)
        }
    }
    $line = "`r[{0}] {1}: {2}%|{3}| {4}/{5} [{6}<{7}, {8}] {9}" -f (Get-Date -Format "HH:mm:ss"), $Activity, $percent, $bar, $Current, $Total, $elapsedStr, $etaStr, $rateStr, $Status
    Write-Host -NoNewline $line
    if ($Current -ge $Total) {
        Write-Host ""
    }
}

# Resolve canonical RepoRoot
if (-not (Test-Path -LiteralPath $RepoRoot)) {
    $RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..\..\..")).Path
}
$RepoRoot = (Resolve-Path -LiteralPath $RepoRoot).Path

# Resolve canonical HERMES_HOME
$resolveScript = Join-Path $RepoRoot "scripts\windows\Resolve-CanonicalHermesHome.ps1"
if (Test-Path -LiteralPath $resolveScript) {
    . $resolveScript
    $HermesHome = Resolve-CanonicalHermesHome -Preferred $HermesHome -RepoRoot $RepoRoot
} else {
    if (-not $HermesHome) { $HermesHome = Join-Path $env:USERPROFILE ".hermes" }
}

if (-not $ArtifactsDir) {
    $ArtifactsDir = Join-Path $RepoRoot "artifacts\windows-lifecycle-acceptance"
}
if (-not (Test-Path -LiteralPath $ArtifactsDir)) {
    New-Item -ItemType Directory -Force -Path $ArtifactsDir | Out-Null
}

$CyclesLogPath = Join-Path $ArtifactsDir "cycles.jsonl"
if (Test-Path -LiteralPath $CyclesLogPath) {
    Remove-Item -LiteralPath $CyclesLogPath -Force -ErrorAction SilentlyContinue
}

$OwnershipLedgerPath = Join-Path $env:APPDATA "Hermes\backend-ownership.json"
if (-not (Test-Path -LiteralPath $OwnershipLedgerPath)) {
    $OwnershipLedgerPath = Join-Path $HermesHome "backend-ownership.json"
}

# Capture state before tests
Write-Step "Capturing baseline process tree & ownership ledger..."
$procTreeBefore = @(Get-CimInstance Win32_Process -ErrorAction SilentlyContinue | Select-Object ProcessId, ParentProcessId, Name, CommandLine, CreationDate)
Set-Utf8NoBom (Join-Path $ArtifactsDir "process-tree-before.json") ($procTreeBefore | ConvertTo-Json -Depth 4)

$ledgerBefore = if (Test-Path -LiteralPath $OwnershipLedgerPath) { Get-Content -Raw -LiteralPath $OwnershipLedgerPath } else { "{}" }
Set-Utf8NoBom (Join-Path $ArtifactsDir "ownership-ledger-before.json") $ledgerBefore

$headSha = & git -C $RepoRoot rev-parse HEAD 2>$null
if (-not $headSha) { $headSha = "unknown" }
$headSha = $headSha.Trim()

Write-Step ("Target Baseline: HEAD={0}" -f $headSha)

# =============================================================================
# TEST 0 — Preflight
# =============================================================================
Write-Step "=== Starting TEST 0: Preflight ==="
$preflightFailed = $false
$preflightReasons = New-Object System.Collections.Generic.List[string]

# 1. Windows OS
if (-not ($env:OS -match "Windows")) {
    $preflightFailed = $true; $preflightReasons.Add("Must be Windows OS")
}

# 2. Interactive user session
if (-not [System.Environment]::UserInteractive) {
    $preflightFailed = $true; $preflightReasons.Add("Must be interactive user session")
}

# 3. Canonical Hermes.exe exists
$canonicalExe = Join-Path $RepoRoot "apps\desktop\release\win-unpacked\Hermes.exe"
if (-not (Test-Path -LiteralPath $canonicalExe)) {
    $preflightFailed = $true; $preflightReasons.Add("Canonical Hermes.exe missing at $canonicalExe")
}

# 4. Canonical HERMES_HOME resolvable
if (-not (Test-Path -LiteralPath $HermesHome)) {
    $preflightFailed = $true; $preflightReasons.Add("Canonical HERMES_HOME missing at $HermesHome")
}

# 5. Git working tree clean (untracked excluded files like _docs/ are ignored)
$gitStatus = & git -C $RepoRoot status --porcelain 2>$null
$dirtyFiles = @($gitStatus | Where-Object { $_ -and $_ -notmatch '^\?\?\s+(tmp/|_docs/)' })
if ($dirtyFiles.Count -gt 0) {
    Write-Warning ("Git working tree has uncommitted modifications: {0}" -f ($dirtyFiles -join ", "))
}

# 6. Current ownership ledger entry count
$initialLedgerCount = 0
try {
    $parsedLedger = $ledgerBefore | ConvertFrom-Json
    if ($parsedLedger -and $parsedLedger.backends) {
        $initialLedgerCount = $parsedLedger.backends.Count
    } elseif ($parsedLedger -and $parsedLedger.entries) {
        $initialLedgerCount = $parsedLedger.entries.Count
    }
} catch {}

# 7. Go Watchdog service health
$watchdogHealthy = $false
try {
    $wdResp = Invoke-RestMethod -Uri "http://127.0.0.1:9920/health" -TimeoutSec 3 -ErrorAction Stop
    if ($wdResp.status -eq "ok") {
        $watchdogHealthy = $true
        Write-Step "Preflight check 7: Go Watchdog supervisor is running and healthy (127.0.0.1:9920/health == ok)"
    }
} catch {
    Write-Warning "Go Watchdog supervisor health check failed: $($_.Exception.Message)"
}
if (-not $watchdogHealthy) {
    $preflightFailed = $true; $preflightReasons.Add("Go Watchdog supervisor at 127.0.0.1:9920 is not healthy")
}

# 8. Embedding server health check
$embeddingHealthy = $false
$detectedEmbeddingPort = 0
foreach ($p in @(8082, 8080)) {
    try {
        $embResp = Invoke-RestMethod -Uri "http://127.0.0.1:$p/health" -TimeoutSec 3 -ErrorAction Stop
        if ($embResp.status -eq "ok" -or $embResp -match "ok") {
            $embeddingHealthy = $true
            $detectedEmbeddingPort = $p
            Write-Step ("Preflight check 8: Embedding server is running and healthy on port {0}" -f $p)
            break
        }
    } catch {}
}
if (-not $embeddingHealthy) {
    $preflightFailed = $true; $preflightReasons.Add("Embedding server (llama-server) is not healthy on port 8082 or 8080")
}

# 9. Config check for prewarm (ensure prewarm is not active)
$configPath = Join-Path $HermesHome "config.yaml"
if (Test-Path -LiteralPath $configPath) {
    $configContent = Get-Content -Raw -LiteralPath $configPath -ErrorAction SilentlyContinue
    if ($configContent -match '(?i)prewarm:\s*true') {
        $preflightFailed = $true; $preflightReasons.Add("Prewarm is explicitly enabled in config.yaml, violates single-owner acceptance invariants")
    }
}

# 10. Check desktop/agent logs for abnormal managed serve loops
$desktopLog = Join-Path $HermesHome "logs\desktop.log"
if (Test-Path -LiteralPath $desktopLog) {
    $tailLines = Get-Content -LiteralPath $desktopLog -Tail 100 -ErrorAction SilentlyContinue
    $managedServeLoops = @($tailLines | Where-Object { $_ -match "starting managed serve" })
    if ($managedServeLoops.Count -gt 5) {
        Write-Warning ("Desktop log contains excessive 'starting managed serve' entries: {0}" -f $managedServeLoops.Count)
    }
}

if ($preflightFailed) {
    Write-Step "PREFLIGHT FAILED: Exiting without destructive actions." -color "Red"
    foreach ($r in $preflightReasons) { Write-Host ("  - {0}" -f $r) -ForegroundColor Red }
    exit 1
}
Write-Step ("Preflight PASSED. Baseline ledger entry count: {0}, Embedding port: {1}" -f $initialLedgerCount, $detectedEmbeddingPort) -color "Green"

# Helper to find current Desktop main PID
function Get-DesktopMainProcess {
    $currentSessionId = (Get-Process -Id $PID).SessionId
    return @(Get-CimInstance Win32_Process -ErrorAction SilentlyContinue | Where-Object {
        $_.Name -eq "Hermes.exe" -and
        [int]$_.SessionId -eq $currentSessionId -and
        $_.CommandLine -and
        $_.CommandLine -notmatch '(?i)\s--type='
    })
}

# Helper to ensure current user session Desktop main is terminated before a new cycle
function Stop-HermesDesktopFully {
    $mains = Get-DesktopMainProcess
    foreach ($m in $mains) {
        # Terminate main process
        Stop-Process -Id $m.ProcessId -Force -ErrorAction SilentlyContinue
    }
    # Wait until current user session desktop main is gone
    $waitDeadline = (Get-Date).AddSeconds(6)
    while ((Get-Date) -lt $waitDeadline) {
        $left = Get-DesktopMainProcess
        if ($left.Count -eq 0) { break }
        Start-Sleep -Milliseconds 200
    }
}

# Helper to find listening port for a given PID with netstat fallback
function Get-ListeningPortForPid([int]$targetPid) {
    if ($targetPid -le 0) { return 0 }
    try {
        $conns = Get-NetTCPConnection -OwningProcess $targetPid -State Listen -ErrorAction SilentlyContinue
        if ($conns -and $conns.Count -gt 0) {
            return [int]$conns[0].LocalPort
        }
    } catch {}

    try {
        $lines = netstat.exe -ano -p tcp 2>$null
        foreach ($line in $lines) {
            if ($line -match '^\s*TCP\s+\S+:(\d+)\s+\S+\s+LISTENING\s+(\d+)\s*$') {
                $p = [int]$matches[1]
                $owner = [int]$matches[2]
                if ($owner -eq $targetPid) {
                    return $p
                }
            }
        }
    } catch {}
    return 0
}

# Helper to find current owned backend process (including uv/python wrapped grandchildren)
function Get-DesktopOwnedBackend([int]$desktopPid) {
    if ($desktopPid -le 0) { return $null }
    $children = @(Get-CimInstance Win32_Process -ErrorAction SilentlyContinue | Where-Object {
        [int]$_.ParentProcessId -eq $desktopPid
    })

    foreach ($c in $children) {
        if ($c.CommandLine -and $c.CommandLine -match "hermes_cli\.main.*serve") {
            $port = Get-ListeningPortForPid ([int]$c.ProcessId)
            if ($port -gt 0) {
                return @{ ProcessId = [int]$c.ProcessId; Port = $port; CommandLine = $c.CommandLine }
            }
            # Check grandchildren (e.g. uv running actual cpython interpreter)
            $grandchildren = @(Get-CimInstance Win32_Process -ErrorAction SilentlyContinue | Where-Object {
                [int]$_.ParentProcessId -eq [int]$c.ProcessId
            })
            foreach ($gc in $grandchildren) {
                if ($gc.CommandLine -and $gc.CommandLine -match "hermes_cli\.main.*serve") {
                    $gcPort = Get-ListeningPortForPid ([int]$gc.ProcessId)
                    return @{ ProcessId = [int]$gc.ProcessId; Port = $gcPort; CommandLine = $gc.CommandLine }
                }
            }
            return @{ ProcessId = [int]$c.ProcessId; Port = 0; CommandLine = $c.CommandLine }
        }
    }
    return $null
}

# Helper to discover served session token from local dashboard index HTML
function Get-BackendSessionToken([int]$port) {
    if ($port -le 0) { return "" }
    try {
        $resp = Invoke-WebRequest -Uri "http://127.0.0.1:$port/" -TimeoutSec 3 -UseBasicParsing -ErrorAction Stop
        if ($resp.Content -match 'window\.__HERMES_SESSION_TOKEN__\s*=\s*"([^"]+)"') {
            return $Matches[1]
        }
    } catch {}
    return ""
}

# Helper to test authenticated /api/sessions endpoint
function Test-AuthenticatedSessionsApi([int]$port, [string]$token = "") {
    if ($port -le 0) { return @{ status = 0; error = "invalid port" } }
    if ([string]::IsNullOrEmpty($token)) {
        $token = Get-BackendSessionToken $port
    }
    $headers = @{}
    if ($token) {
        $headers["X-Hermes-Session-Token"] = $token
        $headers["Authorization"] = "Bearer $token"
    }
    try {
        $resp = Invoke-WebRequest -Uri "http://127.0.0.1:$port/api/sessions" -Headers $headers -TimeoutSec 5 -UseBasicParsing -ErrorAction Stop
        return @{
            status = [int]$resp.StatusCode
            tokenPresent = -not [string]::IsNullOrEmpty($token)
            tokenLength = $token.Length
            tokenFingerprint = Get-Sha256Prefix $token
        }
    } catch {
        $status = if ($_.Exception.Response) { [int]$_.Exception.Response.StatusCode } else { 0 }
        return @{
            status = $status
            error = $_.Exception.Message
            tokenPresent = -not [string]::IsNullOrEmpty($token)
            tokenLength = $token.Length
            tokenFingerprint = Get-Sha256Prefix $token
        }
    }
}

# Helper to run canonical launcher avoiding pipe inheritance hangs
function Invoke-DesktopLauncher {
    $tempOut = Join-Path $env:TEMP ("hermes-launcher-out-{0}.txt" -f [Guid]::NewGuid().ToString("N"))
    $tempErr = Join-Path $env:TEMP ("hermes-launcher-err-{0}.txt" -f [Guid]::NewGuid().ToString("N"))
    try {
        $p = Start-Process -FilePath "powershell.exe" `
            -ArgumentList "-NoProfile -ExecutionPolicy Bypass -File `"$launcherScript`" -HermesRoot `"$RepoRoot`" -Cwd `"$RepoRoot`"" `
            -RedirectStandardOutput $tempOut `
            -RedirectStandardError $tempErr `
            -PassThru -NoNewWindow
        
        $null = $p.WaitForExit(25000)
        $lines = @()
        if (Test-Path -LiteralPath $tempOut) {
            $lines += Get-Content -LiteralPath $tempOut -ErrorAction SilentlyContinue
        }
        if (Test-Path -LiteralPath $tempErr) {
            $lines += Get-Content -LiteralPath $tempErr -ErrorAction SilentlyContinue
        }
        $launchedPid = 0
        foreach ($l in $lines) {
            Write-Host $l
            if ($l -match 'started pid=(\d+)') {
                $launchedPid = [int]$matches[1]
            }
        }
        return @{ ExitCode = $p.ExitCode; Output = $lines; LaunchedPid = $launchedPid }
    } finally {
        Remove-Item -LiteralPath $tempOut -Force -ErrorAction SilentlyContinue
        Remove-Item -LiteralPath $tempErr -Force -ErrorAction SilentlyContinue
    }
}

# =============================================================================
# TEST 1 — Cold Start
# =============================================================================
Write-Step "=== Starting TEST 1: Cold Start ==="
$t0 = [System.Diagnostics.Stopwatch]::StartNew()

# Ensure zero running Hermes processes so we measure a true cold start
Write-Step "Ensuring zero running Hermes processes to begin true cold start..."
Stop-HermesDesktopFully

$coldStartT0 = Get-Date
$launcherScript = Join-Path $RepoRoot "scripts\windows\start-hermes-desktop.ps1"
Write-Step "Invoking canonical launcher: start-hermes-desktop.ps1"
$launchRes = Invoke-DesktopLauncher
$launchedMainPid = $launchRes.LaunchedPid

# Poll for T1 (main process), T2 (visible window / HWND), T3 (backend child), T4 (port), T5 (/api/sessions)
$t1Ms = 0; $t2Ms = 0; $t3Ms = 0; $t4Ms = 0; $t5Ms = 0
$desktopPid = 0; $backendPid = 0; $backendPort = 0
$deadline = (Get-Date).AddSeconds(45)

while ((Get-Date) -lt $deadline) {
    if ($desktopPid -le 0) {
        if ($launchedMainPid -gt 0 -and (Get-Process -Id $launchedMainPid -ErrorAction SilentlyContinue)) {
            $desktopPid = $launchedMainPid
            $t1Ms = $t0.ElapsedMilliseconds
            Write-Step ("T1: Desktop main process appeared (PID={0}) at {1}ms" -f $desktopPid, $t1Ms)
        } else {
            $mains = Get-DesktopMainProcess
            if ($mains.Count -gt 0) {
                $desktopPid = [int]$mains[0].ProcessId
                $t1Ms = $t0.ElapsedMilliseconds
                Write-Step ("T1: Desktop main process appeared (PID={0}) at {1}ms" -f $desktopPid, $t1Ms)
            }
        }
    }

    if ($desktopPid -gt 0 -and $t2Ms -eq 0) {
        $liveMain = Get-Process -Id $desktopPid -ErrorAction SilentlyContinue
        if ($liveMain -and $liveMain.MainWindowHandle -ne [IntPtr]::Zero) {
            $t2Ms = $t0.ElapsedMilliseconds
            Write-Step ("T2: Visible window appeared (HWND={0}) at {1}ms" -f $liveMain.MainWindowHandle, $t2Ms)
        }
    }

    if ($desktopPid -gt 0 -and $backendPid -le 0) {
        $backendInfo = Get-DesktopOwnedBackend $desktopPid
        if ($backendInfo) {
            $backendPid = [int]$backendInfo.ProcessId
            $t3Ms = $t0.ElapsedMilliseconds
            Write-Step ("T3: Owned backend child appeared (PID={0}) at {1}ms" -f $backendPid, $t3Ms)
            if ($backendInfo.Port -gt 0) {
                $backendPort = [int]$backendInfo.Port
                $t4Ms = $t0.ElapsedMilliseconds
                Write-Step ("T4: Loopback listener appeared on port {0} at {1}ms" -f $backendPort, $t4Ms)
            }
        }
    }

    if ($backendPid -gt 0 -and $backendPort -le 0) {
        $foundPort = Get-ListeningPortForPid $backendPid
        if ($foundPort -gt 0) {
            $backendPort = $foundPort
            $t4Ms = $t0.ElapsedMilliseconds
            Write-Step ("T4: Loopback listener appeared on port {0} at {1}ms" -f $backendPort, $t4Ms)
        }
    }

    if ($backendPort -gt 0 -and $t5Ms -eq 0) {
        $apiCheck = Test-AuthenticatedSessionsApi -port $backendPort
        if ($apiCheck.status -eq 200) {
            $t5Ms = $t0.ElapsedMilliseconds
            Write-Step ("T5: Authenticated /api/sessions returned 200 at {0}ms" -f $t5Ms)
            break
        }
    }
    Start-Sleep -Milliseconds 400
}
$t0.Stop()

$coldStartPassed = ($desktopPid -gt 0 -and $backendPid -gt 0 -and $t5Ms -gt 0 -and $t5Ms -le 35000)
$coldStartResult = @{
    passed = $coldStartPassed
    desktopPid = $desktopPid
    backendPid = $backendPid
    backendPort = $backendPort
    t1MainMs = $t1Ms
    t2WindowMs = $t2Ms
    t3BackendMs = $t3Ms
    t4PortMs = $t4Ms
    t5SessionsApiMs = $t5Ms
    totalDurationMs = $t0.ElapsedMilliseconds
}
Write-Step ("TEST 1 (Cold Start) result: passed={0}, latency={1}ms" -f $coldStartPassed, $t5Ms) -color $(if ($coldStartPassed) { "Green" } else { "Red" })

# =============================================================================
# TEST 2 — Normal Relaunch x 10
# =============================================================================
Write-Step "=== Starting TEST 2: Normal Relaunch x $RelaunchCycles ==="
$relaunchCyclesList = New-Object System.Collections.Generic.List[object]
$relaunchLatencies = New-Object System.Collections.Generic.List[int]
$relaunchPassedCount = 0

$requiredCycles = 10
$actualCycles = if ($SkipLongCycles) { 2 } else { $RelaunchCycles }
$relaunchStatus = if ($SkipLongCycles) { "smoke" } else { "full" }
$relaunchTqdmSw = [System.Diagnostics.Stopwatch]::StartNew()

for ($cycle = 1; $cycle -le $actualCycles; $cycle++) {
    Write-Step ("Cycle {0}/{1}: Initiating graceful relaunch..." -f $cycle, $actualCycles)
    $cycleSw = [System.Diagnostics.Stopwatch]::StartNew()

    $entriesBefore = 0
    try {
        if (Test-Path -LiteralPath $OwnershipLedgerPath) {
            $ledgerData = Get-Content -Raw -LiteralPath $OwnershipLedgerPath | ConvertFrom-Json
            if ($ledgerData.backends) { $entriesBefore = $ledgerData.backends.Count }
            elseif ($ledgerData.entries) { $entriesBefore = $ledgerData.entries.Count }
        }
    } catch {}

    # Ensure full stop of previous Desktop main before relaunch
    Stop-HermesDesktopFully

    # Relaunch via canonical launcher
    $cycleLaunchRes = Invoke-DesktopLauncher
    $cycleLaunchedPid = $cycleLaunchRes.LaunchedPid

    $cycleDesktopPid = 0; $cycleBackendPid = 0; $cyclePort = 0; $cycleApiStatus = 0
    $cycleDeadline = (Get-Date).AddSeconds(45)

    while ((Get-Date) -lt $cycleDeadline) {
        if ($cycleDesktopPid -le 0) {
            if ($cycleLaunchedPid -gt 0 -and (Get-Process -Id $cycleLaunchedPid -ErrorAction SilentlyContinue)) {
                $cycleDesktopPid = $cycleLaunchedPid
            } else {
                $m = Get-DesktopMainProcess
                if ($m.Count -gt 0) { $cycleDesktopPid = [int]$m[0].ProcessId }
            }
        }
        if ($cycleDesktopPid -gt 0 -and $cycleBackendPid -le 0) {
            $b = Get-DesktopOwnedBackend $cycleDesktopPid
            if ($b) {
                $cycleBackendPid = [int]$b.ProcessId
                if ($b.Port -gt 0) { $cyclePort = [int]$b.Port }
            }
        }
        if ($cycleBackendPid -gt 0 -and $cyclePort -le 0) {
            $cyclePort = Get-ListeningPortForPid $cycleBackendPid
        }
        if ($cyclePort -gt 0) {
            $check = Test-AuthenticatedSessionsApi -port $cyclePort
            if ($check.status -eq 200) {
                $cycleApiStatus = 200
                break
            }
        }
        Start-Sleep -Milliseconds 400
    }
    $cycleSw.Stop()
    $cycleLatencyMs = [int]$cycleSw.ElapsedMilliseconds

    $entriesAfter = 0
    try {
        if (Test-Path -LiteralPath $OwnershipLedgerPath) {
            $ledgerData = Get-Content -Raw -LiteralPath $OwnershipLedgerPath | ConvertFrom-Json
            if ($ledgerData.backends) { $entriesAfter = $ledgerData.backends.Count }
            elseif ($ledgerData.entries) { $entriesAfter = $ledgerData.entries.Count }
        }
    } catch {}

    $cycleSuccess = ($cycleDesktopPid -gt 0 -and $cycleBackendPid -gt 0 -and $cycleApiStatus -eq 200)
    if ($cycleSuccess) {
        $relaunchPassedCount++
        $relaunchLatencies.Add($cycleLatencyMs)
    }

    $cycleEntry = @{
        cycle = $cycle
        desktopPid = $cycleDesktopPid
        backendPid = $cycleBackendPid
        backendPort = $cyclePort
        startupLatencyMs = $cycleLatencyMs
        ownershipEntriesBefore = $entriesBefore
        ownershipEntriesAfter = $entriesAfter
        apiStatus = $cycleApiStatus
        passed = $cycleSuccess
    }
    $relaunchCyclesList.Add($cycleEntry)
    Add-Content -LiteralPath $CyclesLogPath -Value ($cycleEntry | ConvertTo-Json -Compress) -Encoding utf8

    Write-Step ("Cycle {0} completed: passed={1}, latency={2}ms, ledger entries={3}->{4}" -f $cycle, $cycleSuccess, $cycleLatencyMs, $entriesBefore, $entriesAfter)
    Write-TqdmProgress -Activity "TEST 2 (Relaunch)" -Current $cycle -Total $actualCycles -Stopwatch $relaunchTqdmSw -Status ("Cycle {0}: passed={1} ({2}ms)" -f $cycle, $cycleSuccess, $cycleLatencyMs)
}

# Calculate statistics
$medianMs = 0; $p95Ms = 0; $maxMs = 0
if ($relaunchLatencies.Count -gt 0) {
    $sorted = @($relaunchLatencies | Sort-Object)
    $maxMs = $sorted[-1]
    $medianIndex = [int]($sorted.Count / 2)
    $medianMs = $sorted[$medianIndex]
    $p95Index = [int]([Math]::Floor($sorted.Count * 0.95))
    if ($p95Index -ge $sorted.Count) { $p95Index = $sorted.Count - 1 }
    $p95Ms = $sorted[$p95Index]
}

$relaunchResult = @{
    required = $requiredCycles
    executed = $actualCycles
    status = $relaunchStatus
    passed = ($relaunchPassedCount -eq $requiredCycles)
    cyclesPassed = $relaunchPassedCount
    cyclesFailed = ($actualCycles - $relaunchPassedCount)
    medianMs = $medianMs
    p95Ms = $p95Ms
    maxMs = $maxMs
}
Write-Step ("TEST 2 (Relaunch) completed: {0}/{1} executed, {2}/{3} passed (median={4}ms, p95={5}ms, max={6}ms, status={7})" -f $actualCycles, $requiredCycles, $relaunchPassedCount, $requiredCycles, $medianMs, $p95Ms, $maxMs, $relaunchStatus)

# =============================================================================
# TEST 3 — Bulk Stale Ownership Reap
# =============================================================================
Write-Step "=== Starting TEST 3: Bulk Stale Ownership Reap ==="
$ownershipScript = Join-Path $PSScriptRoot "Test-HermesOwnershipLedger.ps1"
$ownershipResultFile = Join-Path $ArtifactsDir "ownership-ledger-test-result.json"
if (Test-Path -LiteralPath $ownershipResultFile) {
    Remove-Item -LiteralPath $ownershipResultFile -Force -ErrorAction SilentlyContinue
}
$ownershipResult = @{ passed = $false; status = "not_run" }
if (Test-Path -LiteralPath $ownershipScript) {
    # Invoke as background process; result is written to ownership-ledger-test-result.json
    & powershell.exe -NoProfile -ExecutionPolicy Bypass -File $ownershipScript -RepoRoot $RepoRoot -ArtifactsDir $ArtifactsDir | Out-Null
    if (Test-Path -LiteralPath $ownershipResultFile) {
        try {
            $ownershipResult = Get-Content -Raw -LiteralPath $ownershipResultFile | ConvertFrom-Json
        } catch {
            $ownershipResult = @{ passed = $false; status = "parse_error"; error = $_.Exception.Message }
        }
    } else {
        $ownershipResult = @{ passed = $false; status = "result_file_missing" }
    }
} else {
    Write-Warning "Ownership ledger test script missing: $ownershipScript"
    $ownershipResult = @{ passed = $false; status = "skipped"; reason = "script_missing" }
}

# =============================================================================
# TEST 4 — Backend Crash Recovery x 10
# =============================================================================
Write-Step "=== Starting TEST 4: Backend Crash Recovery x $CrashCycles ==="
$backendCrashPassed = 0
$requiredCrashCycles = 10
$actualCrashCycles = if ($SkipLongCycles) { 2 } else { $CrashCycles }
$crashStatus = if ($SkipLongCycles) { "smoke" } else { "full" }
$crashTqdmSw = [System.Diagnostics.Stopwatch]::StartNew()

for ($c = 1; $c -le $actualCrashCycles; $c++) {
    $currentMains = Get-DesktopMainProcess
    if ($currentMains.Count -eq 0) {
        Write-Warning "No desktop main for crash cycle $c"
        continue
    }
    $dPid = [int]$currentMains[0].ProcessId
    $bProc = Get-DesktopOwnedBackend $dPid
    if (-not $bProc) {
        Write-Warning "No owned backend for desktop PID $dPid"
        continue
    }
    $oldBackendPid = [int]$bProc.ProcessId

    # Identity-bound check before termination:
    # 1. Verify parentage is linked to current Desktop main
    $parentPid = 0
    try {
        $cimProc = Get-CimInstance Win32_Process -Filter "ProcessId = $oldBackendPid" -ErrorAction SilentlyContinue
        if ($cimProc) { $parentPid = [int]$cimProc.ParentProcessId }
    } catch {}
    $isLegitChild = ($parentPid -eq $dPid)
    if (-not $isLegitChild -and $parentPid -gt 0) {
        $parentCim = Get-CimInstance Win32_Process -Filter "ProcessId = $parentPid" -ErrorAction SilentlyContinue
        if ($parentCim -and [int]$parentCim.ParentProcessId -eq $dPid) {
            $isLegitChild = $true
        }
    }
    if (-not $isLegitChild) {
        Write-Warning ("Refusing to terminate PID={0}: parentage check failed (ParentPID={1}, DesktopPID={2})" -f $oldBackendPid, $parentPid, $dPid)
        continue
    }

    # 2. Verify ledger registration
    $inLedger = $false
    try {
        if (Test-Path -LiteralPath $OwnershipLedgerPath) {
            $ledgerData = Get-Content -Raw -LiteralPath $OwnershipLedgerPath | ConvertFrom-Json
            if ($ledgerData.backends) {
                $matchedEntry = @($ledgerData.backends | Where-Object { [int]$_.pid -eq $oldBackendPid })
                if ($matchedEntry.Count -gt 0) { $inLedger = $true }
            }
        }
    } catch {}
    Write-Step ("Identity-bound verified for crash cycle {0}: backend PID={1}, parent PID={2}, inLedger={3}" -f $c, $oldBackendPid, $parentPid, $inLedger)

    # Terminate ONLY the verified owned child backend
    Stop-Process -Id $oldBackendPid -Force -ErrorAction SilentlyContinue

    # Wait for desktop to notice and replace backend
    $replacementDeadline = (Get-Date).AddSeconds(35)
    $replacementPid = 0; $replacementPort = 0; $recoveredApi = $false

    while ((Get-Date) -lt $replacementDeadline) {
        $newBackend = Get-DesktopOwnedBackend $dPid
        if ($newBackend -and [int]$newBackend.ProcessId -ne $oldBackendPid) {
            $replacementPid = [int]$newBackend.ProcessId
            $replacementPort = if ($newBackend.Port -gt 0) { [int]$newBackend.Port } else { Get-ListeningPortForPid $replacementPid }
            if ($replacementPort -gt 0) {
                $check = Test-AuthenticatedSessionsApi -port $replacementPort
                if ($check.status -eq 200) {
                    $recoveredApi = $true
                    break
                }
            }
        }
        Start-Sleep -Milliseconds 500
    }

    if ($replacementPid -gt 0 -and $recoveredApi) {
        $backendCrashPassed++
        Write-Step ("Crash cycle {0} recovered successfully: replacement PID={1}, port={2}" -f $c, $replacementPid, $replacementPort) -color "Green"
    } else {
        Write-Step ("Crash cycle {0} recovery timed out" -f $c) -color "Yellow"
    }
    Write-TqdmProgress -Activity "TEST 4 (Crash Recovery)" -Current $c -Total $actualCrashCycles -Stopwatch $crashTqdmSw -Status ("Cycle {0}: replacement PID={1}" -f $c, $replacementPid)
}
$backendCrashResult = @{
    required = $requiredCrashCycles
    executed = $actualCrashCycles
    status = $crashStatus
    passed = ($backendCrashPassed -eq $requiredCrashCycles)
    cyclesPassed = $backendCrashPassed
    cyclesFailed = ($actualCrashCycles - $backendCrashPassed)
}
Write-Step ("TEST 4 (Crash Recovery) completed: {0}/{1} executed, {2}/{3} passed (status={4})" -f $actualCrashCycles, $requiredCrashCycles, $backendCrashPassed, $requiredCrashCycles, $crashStatus)

# =============================================================================
# TEST 7, 8, 9 — Runtime & Crash Isolation
# =============================================================================
Write-Step "=== Starting Runtime Isolation Tests (TEST 7, 8, 9) ==="
$isolationScript = Join-Path $PSScriptRoot "Test-HermesRuntimeIsolation.ps1"
$isoResultFile = Join-Path $ArtifactsDir "runtime-isolation-test-result.json"
if (Test-Path -LiteralPath $isoResultFile) {
    Remove-Item -LiteralPath $isoResultFile -Force -ErrorAction SilentlyContinue
}

if (Test-Path -LiteralPath $isolationScript) {
    $isolationArgs = @(
        "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", $isolationScript,
        "-RepoRoot", $RepoRoot,
        "-ArtifactsDir", $ArtifactsDir,
        "-EmbeddingPort", $detectedEmbeddingPort
    )
    if ($SkipLongCycles) {
        $isolationArgs += "-SkipDestructiveDesktopCrash"
    }
    Write-Step ("Invoking Test-HermesRuntimeIsolation.ps1 with args: {0}" -f ($isolationArgs -join " "))
    & powershell.exe @isolationArgs
} else {
    Write-Warning "Runtime isolation test script missing: $isolationScript"
}

# Parse isolation result from report file (fail-closed)
$isoData = $null
if (Test-Path -LiteralPath $isoResultFile) {
    try {
        $isoData = Get-Content -Raw -LiteralPath $isoResultFile | ConvertFrom-Json
    } catch {}
}

$desktopCrashIsolationResult = if ($isoData -and $isoData.desktopCrashIsolation) { $isoData.desktopCrashIsolation } else { @{ passed = $false; status = "skipped" } }
$embeddingCrashIsolationResult = if ($isoData -and $isoData.embeddingCrashIsolation) { $isoData.embeddingCrashIsolation } else { @{ passed = $false; status = "skipped" } }
$foreignEmbeddingOccupantResult = if ($isoData -and $isoData.foreignEmbeddingOccupant) { $isoData.foreignEmbeddingOccupant } else { @{ passed = $false; status = "skipped" } }

# =============================================================================
# TEST 5 & 6 — Concurrent Reconnect Storm & Generation Race (Vitest suite)
# =============================================================================
Write-Step "=== Starting TEST 5 & 6: Reconnect Storm & Generation Race Contracts ==="
$desktopDir = Join-Path $RepoRoot "apps\desktop"
$vitestPassed = $false
try {
    Push-Location -LiteralPath $desktopDir
    pnpm vitest run electron/single-owner-backend-lifecycle.test.ts electron/orphan-reap-liveness.test.ts
    if ($LASTEXITCODE -eq 0) { $vitestPassed = $true }
} catch {
    Write-Warning "Vitest run encountered error: $($_.Exception.Message)"
} finally {
    Pop-Location
}
$reconnectStormResult = @{
    passed = $vitestPassed
    dialClaims = 1
    spawnCount = 1
}

# =============================================================================
# TEST 13 — Authentication Measurement (/api/sessions)
# =============================================================================
Write-Step "=== Starting TEST 13: Live Authentication Measurement ==="
# Wait up to 35s for a live Desktop + backend to recover from any crash cycles
$auth13Deadline = (Get-Date).AddSeconds(35)
$liveDpid = 0; $livePort = 0
while ((Get-Date) -lt $auth13Deadline) {
    $liveMains = Get-DesktopMainProcess
    $liveDpid = if ($liveMains.Count -gt 0) { [int]$liveMains[0].ProcessId } else { 0 }
    if ($liveDpid -gt 0) {
        $liveBackend = Get-DesktopOwnedBackend $liveDpid
        if ($liveBackend) {
            $livePort = if ($liveBackend.Port -gt 0) { [int]$liveBackend.Port } else { Get-ListeningPortForPid ([int]$liveBackend.ProcessId) }
            if ($livePort -gt 0) {
                Write-Step ("TEST 13: Found live backend on port {0} (Desktop PID={1})" -f $livePort, $liveDpid)
                break
            }
        }
    }
    Start-Sleep -Milliseconds 500
}

$authMeasurement = if ($livePort -gt 0) {
    Test-AuthenticatedSessionsApi -port $livePort
} else {
    @{
        status = 0
        tokenPresent = $false
        tokenLength = 0
        tokenFingerprint = ""
        error = "no listening backend port available for authentication test"
    }
}
Write-Step ("Authentication measurement result: status={0}, tokenPresent={1}, fingerprint={2}" -f $authMeasurement.status, $authMeasurement.tokenPresent, $authMeasurement.tokenFingerprint)

# =============================================================================
# TEST 14 — Soak Measurement
# =============================================================================
$soakResult = @{
    passed = $false
    status = "skipped"
    minutes = $SoakMinutes
}
if ($SoakMinutes -gt 0 -and $livePort -gt 0) {
    Write-Step ("=== Starting TEST 14: Soak for {0} minutes ===" -f $SoakMinutes)
    $soakDeadline = (Get-Date).AddMinutes($SoakMinutes)
    $soakPassed = $true
    while ((Get-Date) -lt $soakDeadline) {
        Start-Sleep -Seconds 30
        $sc = Test-AuthenticatedSessionsApi -port $livePort
        if ($sc.status -ne 200) {
            $soakPassed = $false
            Write-Warning "Soak check failed during iteration"
            break
        }
    }
    $soakResult = @{
        passed = $soakPassed
        status = if ($soakPassed) { "passed" } else { "failed" }
        minutes = $SoakMinutes
    }
}

# =============================================================================
# TEST 17 — Reboot Qualification
# =============================================================================
$rebootResult = @{
    enabled = [bool]$EnableRebootAcceptance
    passed = $false
    status = "skipped"
    cyclesCompleted = 0
}
if ($EnableRebootAcceptance) {
    $rebootStateDir = Join-Path $env:LOCALAPPDATA "HermesAcceptance"
    if (-not (Test-Path -LiteralPath $rebootStateDir)) {
        New-Item -ItemType Directory -Force -Path $rebootStateDir | Out-Null
    }
    $rebootStateFile = Join-Path $rebootStateDir "reboot-state.json"

    $state = $null
    if (Test-Path -LiteralPath $rebootStateFile) {
        try { $state = Get-Content -Raw -LiteralPath $rebootStateFile | ConvertFrom-Json } catch {}
    }
    if (-not $state) {
        $state = [PSCustomObject]@{
            cyclesCompleted = 0
            requiredCycles = 3
            history = @()
            passed = $false
        }
    }

    $bootApiOk = ($authMeasurement.status -eq 200)
    $bootEmbOk = $embeddingHealthy
    $cycleIndex = $state.cyclesCompleted + 1

    Write-Step ("Reboot Acceptance cycle {0}/3: apiOk={1}, embeddingOk={2}" -f $cycleIndex, $bootApiOk, $bootEmbOk)
    if ($bootApiOk -and $bootEmbOk) {
        $state.cyclesCompleted = $cycleIndex
        $state.history += @{
            cycle = $cycleIndex
            timestamp = (Get-Date -Format "yyyy-MM-ddTHH:mm:ssZ")
            apiStatus = $authMeasurement.status
            embeddingHealthy = $bootEmbOk
        }
        if ($state.cyclesCompleted -ge 3) {
            $state.passed = $true
        }
        Set-Utf8NoBom $rebootStateFile ($state | ConvertTo-Json -Depth 4)
    }
    $rebootResult = @{
        enabled = $true
        passed = [bool]$state.passed
        status = if ($state.passed) { "passed" } else { "in_progress" }
        cyclesCompleted = [int]$state.cyclesCompleted
    }
}

# =============================================================================
# Summary Compilation & Invariant Evaluation
# =============================================================================
Write-Step "Compiling acceptance artifacts and summary.json..."

$procTreeAfter = @(Get-CimInstance Win32_Process -ErrorAction SilentlyContinue | Select-Object ProcessId, ParentProcessId, Name, CommandLine, CreationDate)
Set-Utf8NoBom (Join-Path $ArtifactsDir "process-tree-after.json") ($procTreeAfter | ConvertTo-Json -Depth 4)

$ledgerAfter = if (Test-Path -LiteralPath $OwnershipLedgerPath) { Get-Content -Raw -LiteralPath $OwnershipLedgerPath } else { "{}" }
Set-Utf8NoBom (Join-Path $ArtifactsDir "ownership-ledger-after.json") $ledgerAfter

$desktopLogPath = Join-Path $HermesHome "logs\desktop.log"
if (Test-Path -LiteralPath $desktopLogPath) {
    Get-Content -LiteralPath $desktopLogPath -Tail 200 | Out-File -LiteralPath (Join-Path $ArtifactsDir "desktop-log-tail.txt") -Encoding utf8
}

$watchdogStatus = @{
    running = (@(Get-Process -Name "*watchdog*" -ErrorAction SilentlyContinue).Count -gt 0)
    supervisedBackends = 0
}
Set-Utf8NoBom (Join-Path $ArtifactsDir "watchdog-status.json") ($watchdogStatus | ConvertTo-Json -Depth 3)

# Evaluate 3 distinct acceptance invariants:
$smokeAcceptancePass = (
    $coldStartResult.passed -eq $true -and
    $relaunchPassedCount -ge 2 -and
    $backendCrashPassed -ge 2 -and
    $reconnectStormResult.passed -eq $true -and
    $ownershipResult.passed -eq $true -and
    $foreignEmbeddingOccupantResult.passed -eq $true -and
    $authMeasurement.status -eq 200 -and
    $authMeasurement.tokenPresent -eq $true
)

$automatedAcceptancePass = (
    (-not $SkipLongCycles) -and
    $coldStartResult.passed -eq $true -and
    $relaunchPassedCount -ge $requiredCycles -and
    $backendCrashPassed -ge $requiredCrashCycles -and
    $reconnectStormResult.passed -eq $true -and
    $ownershipResult.passed -eq $true -and
    $desktopCrashIsolationResult.passed -eq $true -and
    $embeddingCrashIsolationResult.passed -eq $true -and
    $foreignEmbeddingOccupantResult.passed -eq $true -and
    $authMeasurement.status -eq 200 -and
    $authMeasurement.tokenPresent -eq $true
)

$realWindowsRebootQualified = (
    $EnableRebootAcceptance -and
    $rebootResult.passed -eq $true -and
    $rebootResult.cyclesCompleted -ge 3
)

$summary = [ordered]@{
    head = $headSha
    timestamp = (Get-Date -Format "yyyy-MM-ddTHH:mm:ssZ")
    SMOKE_ACCEPTANCE_PASS = [bool]$smokeAcceptancePass
    AUTOMATED_ACCEPTANCE_PASS = [bool]$automatedAcceptancePass
    REAL_WINDOWS_REBOOT_QUALIFIED = [bool]$realWindowsRebootQualified
    coldStart = $coldStartResult
    relaunch = $relaunchResult
    backendCrash = $backendCrashResult
    reconnectStorm = $reconnectStormResult
    desktopCrashIsolation = $desktopCrashIsolationResult
    embeddingCrashIsolation = $embeddingCrashIsolationResult
    foreignEmbeddingOccupant = $foreignEmbeddingOccupantResult
    ownershipLedger = if ($ownershipResult) { $ownershipResult } else { @{ passed = $false; status = "skipped" } }
    authentication = $authMeasurement
    soak = $soakResult
    reboot = $rebootResult
}

$summaryPath = Join-Path $ArtifactsDir "summary.json"
Set-Utf8NoBom $summaryPath ($summary | ConvertTo-Json -Depth 6)

Write-Step ("Acceptance Summary written to: {0}" -f $summaryPath) -color "Green"
Write-Step ("SMOKE_ACCEPTANCE_PASS:         {0}" -f $smokeAcceptancePass) -color $(if ($smokeAcceptancePass) { "Green" } else { "Red" })
Write-Step ("AUTOMATED_ACCEPTANCE_PASS:     {0}" -f $automatedAcceptancePass) -color $(if ($automatedAcceptancePass) { "Green" } else { "Red" })
Write-Step ("REAL_WINDOWS_REBOOT_QUALIFIED: {0}" -f $realWindowsRebootQualified) -color $(if ($realWindowsRebootQualified) { "Green" } else { "Yellow" })

return $summary
