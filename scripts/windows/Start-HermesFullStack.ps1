# Start full Hermes stack (Qwen3.8-27B llama-server, Go watchdog, Gateway, WebUI, Desktop, Dashboard)
# Idempotent and suitable for both logon autostart and manual startup.

[CmdletBinding()]
param(
    [string]$RepoRoot = "C:\Users\downl\Documents\New project\hermes-agent",
    [switch]$SkipLlama,
    [switch]$SkipGateway,
    [switch]$SkipWebUI,
    [switch]$SkipGoWatchdog,
    [switch]$SkipDesktop,
    [switch]$SkipDashboard,
    [switch]$SkipTunnels,
    [int]$StartupDelaySeconds = 0,
    [int]$LlamaWaitSeconds = 300,
    [string]$LlamaServerExe = "$env:LOCALAPPDATA\Programs\llama-turboquant\bin\llama-server.exe",
    [string]$LlamaGgufPath = "C:\Users\downl\Desktop\SO8T\gguf_models\soyaakinohara\qwen3.8-27b-abliterated-3.69bpw-12GB-MTP.gguf\qwen3.8-27b-abliterated-3.69bpw-12GB-MTP.gguf",
    [int]$LlamaPort = 8080,
    # The launcher measures the model's real KV footprint and clamps this to
    # what stays resident in VRAM (a context whose KV does not fit is served
    # from system memory: prompt reads collapse to a fraction of their speed
    # and the server looks wedged). 98304 is the largest window that fits
    # next to the 6.71 GiB PQ2_0 weights on a 16 GiB card.
    [int]$LlamaCtxSize = 98304
)

$ErrorActionPreference = "Stop"

function Write-Step([string]$Message) {
    Write-Host ("[{0}] {1}" -f (Get-Date -Format "HH:mm:ss"), $Message) -ForegroundColor Cyan
}

if (-not (Test-Path -LiteralPath $RepoRoot)) {
    $RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
}
$RepoRoot = (Resolve-Path -LiteralPath $RepoRoot).Path
$HermesHome = Join-Path $env:USERPROFILE ".hermes"
$env:HERMES_HOME = $HermesHome

if ($StartupDelaySeconds -gt 0) {
    Write-Step "Waiting $StartupDelaySeconds seconds before starting stack..."
    Start-Sleep -Seconds $StartupDelaySeconds
}

Write-Step "=== Starting Hermes Full Stack ==="
Write-Step "RepoRoot = $RepoRoot"

$PythonExe = Join-Path $RepoRoot ".venv\Scripts\python.exe"
if (-not (Test-Path -LiteralPath $PythonExe)) {
    $PythonExe = Join-Path $RepoRoot "venv\Scripts\python.exe"
}
$SharedVenvPython = Join-Path $HermesHome "hermes-agent\venv\Scripts\python.exe"
if (-not (Test-Path -LiteralPath $PythonExe) -and (Test-Path -LiteralPath $SharedVenvPython)) {
    $PythonExe = $SharedVenvPython
}

# 1. Start Qwen3.8-27B llama-server
if (-not $SkipLlama) {
    $existingLlama = Get-Process -Name "llama-server" -ErrorAction SilentlyContinue
    if (-not $existingLlama) {
        Write-Step "Starting Qwen3.8-27B llama-server (port $LlamaPort, ctx $LlamaCtxSize, MTP speculative decoding)..."
        $qwenScript = Join-Path $PSScriptRoot "start-llama-qwen38-openmanus.ps1"
        if (Test-Path -LiteralPath $qwenScript) {
            & powershell.exe -NoProfile -ExecutionPolicy Bypass -File $qwenScript `
                -ServerExe $LlamaServerExe `
                -GgufPath $LlamaGgufPath `
                -Port $LlamaPort `
                -CtxSize $LlamaCtxSize `
                -WaitSeconds $LlamaWaitSeconds
        } else {
            Write-Warning "Qwen3.8 launcher script missing: $qwenScript"
        }
    } else {
        Write-Step "Llama server already running (PID: $($existingLlama.Id -join ','))"
    }
}

# 2. Start Go Watchdog
if (-not $SkipGoWatchdog) {
    $GoWdScript = Join-Path $PSScriptRoot "Start-HermesGoWatchdog.ps1"
    if (Test-Path -LiteralPath $GoWdScript) {
        Write-Step "Starting Go Desktop/backend watchdog..."
        & powershell.exe -NoProfile -ExecutionPolicy Bypass -File $GoWdScript `
            -HermesRoot $RepoRoot `
            -HermesHome $HermesHome `
            -BuildIfMissing `
            -BuildTimeoutSec 180
    }
}

# 3. Auxiliary / Memory Graph / Tailscale
if (-not $SkipTunnels) {
    $MemoryGraphScript = Join-Path $PSScriptRoot "start-obsidian-memory-graph-server.ps1"
    if (Test-Path -LiteralPath $MemoryGraphScript) {
        Write-Step "Ensuring Obsidian memory-graph server (:8765)..."
        & $MemoryGraphScript
    }

    $TailscaleScript = Join-Path $PSScriptRoot "Update-HermesTailscaleServe.ps1"
    if (Test-Path -LiteralPath $TailscaleScript) {
        Write-Step "Updating Tailscale serve configuration..."
        try {
            & $TailscaleScript -LlamaPort $LlamaPort
        } catch {
            Write-Warning "Tailscale update warning: $($_.Exception.Message)"
        }
    }
}

# 4. Start Gateway
if (-not $SkipGateway) {
    $gatewayScript = Join-Path $PSScriptRoot "start-hermes-gateway.ps1"
    if (Test-Path -LiteralPath $gatewayScript) {
        Write-Step "Starting Hermes Gateway..."
        $gwArgs = @("-NoProfile", "-ExecutionPolicy", "Bypass", "-File", $gatewayScript)
        if (-not $SkipLlama) { $gwArgs += "-StartLlama" }
        & powershell.exe @gwArgs
    }

    # Start Harness
    Write-Step "Starting Hermes Harness daemon..."
    Start-Process -FilePath $PythonExe -ArgumentList @("-m", "hermes_cli.main", "harness", "start") -WorkingDirectory $RepoRoot -WindowStyle Hidden | Out-Null
    Start-Sleep -Seconds 3
}

# 5. Start WebUI (:8787)
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

# 6. Start Dashboard (:9120)
if (-not $SkipDashboard) {
    $dashboardScript = Join-Path $PSScriptRoot "start-hermes-dashboard.ps1"
    if (Test-Path -LiteralPath $dashboardScript) {
        Write-Step "Starting Hermes Dashboard (:9120)..."
        & powershell.exe -NoProfile -ExecutionPolicy Bypass -File $dashboardScript -HermesRoot $RepoRoot -HermesHome $HermesHome
    }
}

# 7. Start Desktop App
if (-not $SkipDesktop) {
    $desktopScript = Join-Path $PSScriptRoot "start-hermes-desktop.ps1"
    if (Test-Path -LiteralPath $desktopScript) {
        Write-Step "Starting Hermes Desktop App..."
        Start-Process -FilePath "powershell.exe" `
            -ArgumentList @("-NoProfile", "-ExecutionPolicy", "Bypass", "-File", "`"$desktopScript`"", "-HermesRoot", "`"$RepoRoot`"", "-Cwd", "`"$RepoRoot`"") `
            -WorkingDirectory $RepoRoot
    }
}

Write-Step "=== Hermes Full Stack Launch Initiated ==="
