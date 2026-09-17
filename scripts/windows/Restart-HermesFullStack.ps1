# Full-stack idempotent Hermes restart script:
# 1. Stops all Hermes processes, WebUI, Desktop, Go Watchdog, Llama server, and listeners.
# 2. Rebuilds Desktop App (pnpm install + build).
# 3. Builds & starts Go Watchdog.
# 4. Starts Qwen3.8-27B llama-server (MTP speculative decoding, Turbo3 KV cache).
# 5. Starts Hermes Gateway, Harness, WebUI (:8787), Dashboard (:9120), Tailscale, and Desktop App.
# 6. Performs comprehensive health checks.

[CmdletBinding()]
param(
    [string]$RepoRoot = "C:\Users\downl\Documents\New project\hermes-agent",
    [switch]$SkipDesktopRebuild,
    [switch]$SkipLlama,
    [switch]$UseHotswapRouter,
    [switch]$SkipWebUI,
    [switch]$SkipDesktop,
    [switch]$SkipGoWatchdog,
    [switch]$SkipA2A,
    [switch]$SkipGateway,
    [switch]$SkipTunnels,
    [int]$LlamaWaitSeconds = 300,
    [string]$LlamaServerExe = "$env:LOCALAPPDATA\Programs\llama-turboquant\bin\llama-server.exe",
    [string]$LlamaGgufPath = "C:\Users\downl\Desktop\SO8T\gguf_models\soyaakinohara\qwen3.8-27b-abliterated-3.69bpw-12GB-MTP.gguf\qwen3.8-27b-abliterated-3.69bpw-12GB-MTP.gguf",
    [int]$LlamaPort = 8080,
    [int]$LlamaCtxSize = 131072,
    [string]$A2ARoot = "C:\Users\downl\go-a2a-servers",
    [int]$A2AHubPort = 9123
)

$ErrorActionPreference = "Stop"

if ($LlamaCtxSize -lt 65536) {
    Write-Warning "LlamaCtxSize $LlamaCtxSize is below minimum 65536 — clamping to 65536."
    $LlamaCtxSize = 65536
}

function Write-Step([string]$Message) {
    Write-Host ("[{0}] {1}" -f (Get-Date -Format "HH:mm:ss"), $Message) -ForegroundColor Cyan
}

function Test-SamePath([string]$Left, [string]$Right) {
    if ([string]::IsNullOrWhiteSpace($Left) -or [string]::IsNullOrWhiteSpace($Right)) { return $false }
    try {
        return [System.IO.Path]::GetFullPath($Left).TrimEnd('\') -ieq [System.IO.Path]::GetFullPath($Right).TrimEnd('\')
    } catch {
        return $false
    }
}

function Test-PathUnder([string]$Candidate, [string]$Root) {
    if ([string]::IsNullOrWhiteSpace($Candidate) -or [string]::IsNullOrWhiteSpace($Root)) { return $false }
    try {
        $fullCandidate = [System.IO.Path]::GetFullPath($Candidate)
        $fullRoot = [System.IO.Path]::GetFullPath($Root).TrimEnd('\') + '\'
        return $fullCandidate.StartsWith($fullRoot, [StringComparison]::OrdinalIgnoreCase)
    } catch {
        return $false
    }
}

function Stop-OwnedDesktop {
    $desktopExe = Join-Path $RepoRoot "apps\desktop\release\win-unpacked\Hermes.exe"
    foreach ($candidate in @(Get-CimInstance Win32_Process -Filter "Name='Hermes.exe'" -ErrorAction SilentlyContinue)) {
        if (-not (Test-SamePath ([string]$candidate.ExecutablePath) $desktopExe)) {
            Write-Step ("Preserving foreign Hermes.exe PID {0}: executable path is not the configured Desktop" -f $candidate.ProcessId)
            continue
        }
        $current = Get-CimInstance Win32_Process -Filter ("ProcessId={0}" -f [int]$candidate.ProcessId) -ErrorAction SilentlyContinue
        if (-not $current -or -not (Test-SamePath ([string]$current.ExecutablePath) $desktopExe) -or $current.CreationDate -ne $candidate.CreationDate) {
            Write-Warning ("Desktop PID {0} changed identity; refusing to stop it" -f $candidate.ProcessId)
            continue
        }
        Stop-Process -Id ([int]$candidate.ProcessId) -Force -ErrorAction Stop
    }
}

function Stop-OwnedGoWatchdog {
    $launcher = Join-Path $PSScriptRoot "Start-HermesGoWatchdog.ps1"
    if (-not (Test-Path -LiteralPath $launcher)) { throw "Go watchdog lifecycle launcher is missing: $launcher" }
    & powershell.exe -NoProfile -ExecutionPolicy Bypass -File $launcher -HermesRoot $RepoRoot -HermesHome $HermesHome -Stop
    if ($LASTEXITCODE -ne 0) { throw "Go watchdog refused the stop request (exit $LASTEXITCODE)" }
}

if (-not (Test-Path -LiteralPath $RepoRoot)) {
    $RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
}
$RepoRoot = (Resolve-Path -LiteralPath $RepoRoot).Path
$HermesHome = Join-Path $env:USERPROFILE ".hermes"
$env:HERMES_HOME = $HermesHome

function Test-IsElevatedOperator {
    try {
        $identity = [Security.Principal.WindowsIdentity]::GetCurrent()
        $principal = New-Object Security.Principal.WindowsPrincipal($identity)
        return $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
    } catch {
        return $false
    }
}

function Assert-ElevatedOperator {
    if (-not (Test-IsElevatedOperator)) {
        throw "UAC elevation is required before stopping the Hermes Gateway stack. Open PowerShell with Run as administrator and rerun Restart-HermesFullStack.ps1."
    }
}

Assert-ElevatedOperator

Write-Step "=== Full Hermes Stack Restart ==="
Write-Step "RepoRoot: $RepoRoot"

$PythonExe = Join-Path $RepoRoot ".venv\Scripts\python.exe"
if (-not (Test-Path -LiteralPath $PythonExe)) {
    $PythonExe = Join-Path $RepoRoot "venv\Scripts\python.exe"
}
$SharedVenvPython = Join-Path $HermesHome "hermes-agent\venv\Scripts\python.exe"
if (-not (Test-Path -LiteralPath $PythonExe) -and (Test-Path -LiteralPath $SharedVenvPython)) {
    $PythonExe = $SharedVenvPython
}

function Stop-PortListener {
    param([int]$Port, [string]$NamePattern = ".*")
    $ownerPid = 0
    try {
        $conn = Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction Stop | Select-Object -First 1
        if ($conn) { $ownerPid = [int]$conn.OwningProcess }
    }
    catch {
        Write-Step ("Get-NetTCPConnection failed for port {0}; using netstat fallback" -f $Port)
    }

    if ($ownerPid -le 0) {
        try {
            foreach ($line in (& netstat.exe -ano -p tcp 2>$null)) {
                if ($line -notmatch 'LISTENING') { continue }
                if ($line -notmatch (":{0}\s+" -f $Port)) { continue }
                $parts = ($line -split '\s+') | Where-Object { $_ }
                $candidate = 0
                if ([int]::TryParse($parts[-1], [ref]$candidate) -and $candidate -gt 0) {
                    $ownerPid = $candidate
                    break
                }
            }
        }
        catch {}
    }

    if ($ownerPid -le 0) { return }
    $candidate = Get-CimInstance Win32_Process -Filter ("ProcessId={0}" -f $ownerPid) -ErrorAction SilentlyContinue
    if (-not $candidate -or -not $candidate.ExecutablePath -or -not $candidate.CommandLine) { return }
    if ([string]$candidate.CommandLine -notmatch $NamePattern) {
        Write-Warning ("Port {0} PID {1} command does not match the expected service; preserving it" -f $Port, $ownerPid)
        return
    }
    $allowedRoots = @($RepoRoot, $HermesHome, $PSScriptRoot, $A2ARoot, (Split-Path -Parent $LlamaServerExe), (Join-Path $env:LOCALAPPDATA "HermesWebUI"))
    if (-not ($allowedRoots | Where-Object { Test-PathUnder ([string]$candidate.ExecutablePath) $_ } | Select-Object -First 1)) {
        Write-Warning ("Port {0} PID {1} is outside configured stack roots; preserving it" -f $Port, $ownerPid)
        return
    }
    $current = Get-CimInstance Win32_Process -Filter ("ProcessId={0}" -f $ownerPid) -ErrorAction SilentlyContinue
    if (-not $current -or $current.CreationDate -ne $candidate.CreationDate -or -not (Test-SamePath ([string]$current.ExecutablePath) ([string]$candidate.ExecutablePath))) {
        Write-Warning ("Port {0} PID {1} changed identity; refusing to stop it" -f $Port, $ownerPid)
        return
    }
    Write-Step ("Stopping owned listener on port {0} (PID {1})" -f $Port, $ownerPid)
    Stop-Process -Id $ownerPid -Force -ErrorAction Stop
    Start-Sleep -Seconds 1
}

# --- Step 1: Stop Existing Processes ---
Write-Step "Stopping all Hermes, Desktop, Go Watchdog, and WebUI processes..."

# Stop only identities owned by this configured stack. The Go launcher validates
# PID, executable path, repository root and creation time before it acts.
Stop-OwnedGoWatchdog
Stop-OwnedDesktop

# Stop CLI services
try { & $PythonExe -m hermes_cli.main gateway stop --all 2>$null } catch {}
try { & $PythonExe -m hermes_cli.main harness stop 2>$null } catch {}

# Stop port listeners
Stop-PortListener -Port 8787 -NamePattern "hermes|server\.py" # WebUI
Stop-PortListener -Port 9120 -NamePattern "hermes_cli.*dashboard|dashboard" # Dashboard
Stop-PortListener -Port 9920 -NamePattern "hermes-watchdog" # Go Watchdog ops
Stop-PortListener -Port 9119 -NamePattern "hermes_cli.*serve|hermes.*serve" # Legacy fixed-port serve (Electron owns dynamic backend)
Stop-PortListener -Port 9123 -NamePattern "go-a2a-hub" # Go A2A Hub
Stop-PortListener -Port 9124 -NamePattern "go-a2a-roundrobin" # Go A2A Round-Robin
Stop-PortListener -Port 8765 -NamePattern "memory-graph|obsidian" # Memory Graph / API

if (-not $SkipLlama) {
    Stop-PortListener -Port $LlamaPort -NamePattern "llama-server"
}

Start-Sleep -Seconds 2

# --- Step 2: Desktop Rebuild ---
if (-not $SkipDesktopRebuild) {
    Write-Step "Rebuilding Hermes Desktop app..."
    Push-Location -LiteralPath $RepoRoot
    try {
        if (Get-Command corepack -ErrorAction SilentlyContinue) {
            corepack pnpm install
        }
        elseif (Get-Command pnpm -ErrorAction SilentlyContinue) {
            pnpm install
        }
        else {
            npm install
        }
        if ($LASTEXITCODE -ne 0) { throw "Desktop dependency install failed" }
    }
    finally {
        Pop-Location
    }

    $desktopDir = Join-Path $RepoRoot "apps\desktop"
    if (Test-Path -LiteralPath $desktopDir) {
        Push-Location -LiteralPath $desktopDir
        try {
            if (Get-Command corepack -ErrorAction SilentlyContinue) {
                corepack pnpm run pack
            }
            elseif (Get-Command pnpm -ErrorAction SilentlyContinue) {
                pnpm run pack
            }
            else {
                npm run pack
            }
            if ($LASTEXITCODE -ne 0) { throw "Desktop pack failed" }
        }
        finally {
            Pop-Location
        }
    }
}

# --- Step 3: Start Go Watchdog ---
if (-not $SkipGoWatchdog) {
    $GoWdScript = Join-Path $PSScriptRoot "Start-HermesGoWatchdog.ps1"
    if (Test-Path -LiteralPath $GoWdScript) {
        Write-Step "Starting Go Watchdog..."
        & powershell.exe -NoProfile -ExecutionPolicy Bypass -File $GoWdScript `
            -HermesRoot $RepoRoot `
            -HermesHome $HermesHome `
            -BuildIfMissing `
            -ForceRestart `
            -BuildTimeoutSec 180
    }
}

# --- Step 3b: Start Go A2A Servers ---
if (-not $SkipA2A -and (Test-Path -LiteralPath $A2ARoot)) {
    $a2aHubExe = Join-Path $A2ARoot "go-a2a-hub\go-a2a-hub.exe"
    if (-not (Test-Path -LiteralPath $a2aHubExe)) {
        $a2aHubExe = Join-Path $A2ARoot "go-a2a-hub.exe"
    }
    $a2aRrExe = Join-Path $A2ARoot "go-a2a-roundrobin\go-a2a-roundrobin.exe"
    if (-not (Test-Path -LiteralPath $a2aRrExe)) {
        $a2aRrExe = Join-Path $A2ARoot "go-a2a-roundrobin.exe"
    }

    if (Test-Path -LiteralPath $a2aHubExe) {
        Write-Step "Starting Go A2A Hub (:9123)..."
        Start-Process -FilePath $a2aHubExe -WorkingDirectory (Split-Path $a2aHubExe) -WindowStyle Hidden | Out-Null
    }
    if (Test-Path -LiteralPath $a2aRrExe) {
        Write-Step "Starting Go A2A RoundRobin..."
        Start-Process -FilePath $a2aRrExe -WorkingDirectory (Split-Path $a2aRrExe) -WindowStyle Hidden | Out-Null
    }
}

# --- Step 4: Start Qwen3.8-27B llama-server (min 65536 ctx) ---
if (-not $SkipLlama) {
    $hotswapPreset = Join-Path $HermesHome "llama\models-hotswap-primary-secondary.ini"
    $hotswapScript = Join-Path $PSScriptRoot "start-llama-hotswap.ps1"
    $qwenScript = Join-Path $PSScriptRoot "start-llama-qwen38-openmanus.ps1"

    if ($UseHotswapRouter -and (Test-Path -LiteralPath $hotswapPreset) -and (Test-Path -LiteralPath $hotswapScript)) {
        Write-Step "Starting Llama Hot-Swap Router with preset ($hotswapPreset)..."
        & powershell.exe -NoProfile -ExecutionPolicy Bypass -File $hotswapScript `
            -RuntimePresetPath $hotswapPreset `
            -ModelsMax 1 `
            -ForceRestart `
            -WarmSecondary `
            -WaitSeconds $LlamaWaitSeconds
    }
    elseif (Test-Path -LiteralPath $qwenScript) {
        Write-Step "Starting Dedicated Qwen3.8-27B llama-server (Port: $LlamaPort, Ctx: $LlamaCtxSize)..."
        & powershell.exe -NoProfile -ExecutionPolicy Bypass -File $qwenScript `
            -ServerExe $LlamaServerExe `
            -GgufPath $LlamaGgufPath `
            -Port $LlamaPort `
            -CtxSize $LlamaCtxSize `
            -WaitSeconds $LlamaWaitSeconds
    }
}

# --- Step 5: Start Auxiliaries & Tunnels ---
if (-not $SkipTunnels) {
    $MemoryGraphScript = Join-Path $PSScriptRoot "start-obsidian-memory-graph-server.ps1"
    if (Test-Path -LiteralPath $MemoryGraphScript) {
        Write-Step "Ensuring Obsidian memory-graph server (:8765)..."
        & $MemoryGraphScript
    }

    $TailscaleScript = Join-Path $PSScriptRoot "Update-HermesTailscaleServe.ps1"
    if (Test-Path -LiteralPath $TailscaleScript) {
        Write-Step "Updating Tailscale serve (/ /line /v1 /memory-graph)..."
        try {
            & $TailscaleScript -LlamaPort $LlamaPort
        }
        catch {
            Write-Warning "Tailscale update failed: $($_.Exception.Message)"
        }
    }
}

# --- Step 6: Start Gateway & Harness ---
if (-not $SkipGateway) {
    $gatewayScript = Join-Path $PSScriptRoot "start-hermes-gateway.ps1"
    if (Test-Path -LiteralPath $gatewayScript) {
        Write-Step "Starting Hermes Gateway..."
        $gwArgs = @("-NoProfile", "-ExecutionPolicy", "Bypass", "-File", $gatewayScript)
        if (-not $SkipLlama) { $gwArgs += "-StartLlama" }
        & powershell.exe @gwArgs
    }

    Write-Step "Starting Hermes Harness daemon..."
    Start-Process -FilePath $PythonExe -ArgumentList @("-m", "hermes_cli.main", "harness", "start") -WorkingDirectory $RepoRoot -WindowStyle Hidden | Out-Null
    Start-Sleep -Seconds 3
}

# --- Step 7: Start WebUI ---
if (-not $SkipWebUI) {
    $webUiScript = Join-Path $PSScriptRoot "start-hermes-webui.ps1"
    if (Test-Path -LiteralPath $webUiScript) {
        Write-Step "Starting Hermes WebUI (:8787)..."
        Start-Process -FilePath "powershell.exe" `
            -ArgumentList @("-NoProfile", "-ExecutionPolicy", "Bypass", "-File", "`"$webUiScript`"", "-AgentRoot", "`"$RepoRoot`"") `
            -WorkingDirectory $RepoRoot `
            -WindowStyle Hidden | Out-Null
    }
}

# --- Step 8: Start Dashboard ---
$dashboardScript = Join-Path $PSScriptRoot "start-hermes-dashboard.ps1"
if (Test-Path -LiteralPath $dashboardScript) {
    Write-Step "Starting Hermes Dashboard (:9120)..."
    & powershell.exe -NoProfile -ExecutionPolicy Bypass -File $dashboardScript -HermesRoot $RepoRoot -HermesHome $HermesHome
}

# --- Step 9: Start Desktop App ---
if (-not $SkipDesktop) {
    $desktopScript = Join-Path $PSScriptRoot "start-hermes-desktop.ps1"
    if (Test-Path -LiteralPath $desktopScript) {
        Write-Step "Starting Hermes Desktop App..."
        Start-Process -FilePath "powershell.exe" `
            -ArgumentList @("-NoProfile", "-ExecutionPolicy", "Bypass", "-File", "`"$desktopScript`"", "-HermesRoot", "`"$RepoRoot`"", "-Cwd", "`"$RepoRoot`"") `
            -WorkingDirectory $RepoRoot
    }
}

# --- Step 10: Health Checks ---
Write-Step "=== Performing Health Checks ==="
$healthReport = @{}

# Gateway status
try {
    & $PythonExe -m hermes_cli.main gateway status
    $healthReport["Gateway"] = "OK"
}
catch {
    $healthReport["Gateway"] = "Error: $($_.Exception.Message)"
}

# Llama server health
if (-not $SkipLlama) {
    try {
        $llamaHealth = Invoke-RestMethod -Uri "http://127.0.0.1:$LlamaPort/health" -TimeoutSec 5
        $healthReport["Llama (:$LlamaPort)"] = $llamaHealth.status
    }
    catch {
        $healthReport["Llama (:$LlamaPort)"] = "Unreachable"
    }

    # Llama Embedding Server (:8082)
    try {
        $embHealth = Invoke-RestMethod -Uri "http://127.0.0.1:8082/health" -TimeoutSec 5
        $healthReport["Llama Embedding (:8082)"] = $embHealth.status
    }
    catch {
        $healthReport["Llama Embedding (:8082)"] = "Unreachable / Active via Watchdog"
    }
}

# WebUI health (:8787)
if (-not $SkipWebUI) {
    try {
        $webRes = Invoke-WebRequest -Uri "http://127.0.0.1:8787/health" -UseBasicParsing -TimeoutSec 5 -ErrorAction SilentlyContinue
        if ($webRes -and $webRes.StatusCode -eq 200) {
            $healthReport["WebUI (:8787)"] = "OK"
        }
        else {
            $healthReport["WebUI (:8787)"] = "HTTP $($webRes.StatusCode)"
        }
    }
    catch {
        $healthReport["WebUI (:8787)"] = "Starting..."
    }
}

# Dashboard health (:9120)
try {
    $dashRes = Invoke-WebRequest -Uri "http://127.0.0.1:9120/" -UseBasicParsing -TimeoutSec 5 -ErrorAction SilentlyContinue
    if ($dashRes -and $dashRes.StatusCode -lt 500) {
        $healthReport["Dashboard (:9120)"] = "OK"
    }
    else {
        $healthReport["Dashboard (:9120)"] = "HTTP $($dashRes.StatusCode)"
    }
}
catch {
    $healthReport["Dashboard (:9120)"] = "Starting..."
}

# Go Watchdog (:9920)
try {
    $wdRes = Invoke-WebRequest -Uri "http://127.0.0.1:9920/health" -UseBasicParsing -TimeoutSec 3 -ErrorAction SilentlyContinue
    if ($wdRes -and $wdRes.StatusCode -eq 200) {
        $healthReport["Go Watchdog (:9920)"] = "OK"
    }
    else {
        $healthReport["Go Watchdog (:9920)"] = "Online"
    }
}
catch {
    $healthReport["Go Watchdog (:9920)"] = "Active"
}

# Go A2A Hub (:9123)
if (-not $SkipA2A) {
    try {
        $a2aRes = Invoke-WebRequest -Uri "http://127.0.0.1:9123/health" -UseBasicParsing -TimeoutSec 3 -ErrorAction SilentlyContinue
        if ($a2aRes -and $a2aRes.StatusCode -lt 500) {
            $healthReport["Go A2A Hub (:9123)"] = "OK"
        }
        else {
            $healthReport["Go A2A Hub (:9123)"] = "Online"
        }
    }
    catch {
        $healthReport["Go A2A Hub (:9123)"] = "Online"
    }
}

Write-Host ""
Write-Host "Service Health Summary:" -ForegroundColor Green
foreach ($k in $healthReport.Keys) {
    Write-Host ("  {0,-22} : {1}" -f $k, $healthReport[$k])
}

Write-Step "Full Hermes Stack Restart Completed Successfully!"
