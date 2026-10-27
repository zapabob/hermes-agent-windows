# Start Hikari-Bonsai-27B-Nimble-LoRA PQ2_0 PrismL llama-server.
# Q8_0 K / Q4_0 V KV cache, context sized against KV footprint,
# ngram-mod speculative decoding, Jinja tool calling enabled.
param(
    [string]$ServerExe = "$env:USERPROFILE\.hermes\llama\prism-b10826-c9c34bc\bin\llama-server.exe",
    [string]$GgufPath = "C:\Users\downl\Desktop\SO8T\gguf_models\zapabobouj\Hikari-Bonsai-27B-Nimble-LoRA-GGUF\Hikari-LoRA-fixed-scale-PQ2_0.gguf",
    [int]$Port = 8080,
    [int]$CtxSize = 98304,
    [int]$Parallel = 1,
    [int]$DraftNMax = 16,
    [int]$WaitSeconds = 300
)

$ErrorActionPreference = "Stop"

if (-not (Test-Path -LiteralPath $ServerExe)) {
    $fallbackExe = "$env:LOCALAPPDATA\Programs\llama-prism\bin\llama-server.exe"
    if (Test-Path -LiteralPath $fallbackExe) {
        $ServerExe = $fallbackExe
    } else {
        throw "llama-server not found: $ServerExe"
    }
}
if (-not (Test-Path -LiteralPath $GgufPath)) { throw "GGUF not found: $GgufPath" }

try {
    . (Join-Path $PSScriptRoot 'Get-LlamaContextBudget.ps1')
    $Budget = Get-LlamaContextBudget `
        -ModelPath $GgufPath `
        -ContextTokens $CtxSize `
        -ParallelSlots $Parallel `
        -CacheTypeK 'q8_0' `
        -CacheTypeV 'q4_0'
    Write-Host (Format-LlamaContextBudget -Budget $Budget)
} catch {
    Write-Warning "llama.cpp KV-cache budget check skipped: $($_.Exception.Message)"
}

# Leftover LLAMA_ARG_* / LLAMA_TURBOQUANT_* env vars silently override CLI flags.
Get-ChildItem Env: |
    Where-Object { $_.Name -like "LLAMA_ARG_*" -or $_.Name -like "LLAMA_TURBOQUANT_*" } |
    ForEach-Object {
        Write-Host "unsetting leftover env: $($_.Name)"
        Remove-Item "Env:$($_.Name)" -ErrorAction SilentlyContinue
    }

$env:LLAMA_ARG_CACHE_TYPE_K = "q8_0"
$env:LLAMA_ARG_CACHE_TYPE_V = "q4_0"

# Free the port if a previous instance is still bound.
$existing = Get-Process -Name "llama-server" -ErrorAction SilentlyContinue
if ($existing) {
    Write-Host "stopping existing llama-server (PID $($existing.Id -join ','))"
    $existing | Stop-Process -Force
    Start-Sleep -Seconds 2
}

# RTX 5060 Ti Blackwell Deterministic Clocks & Power Pinning
try {
    if (Get-Command nvidia-smi -ErrorAction SilentlyContinue) {
        Write-Host "Pinning RTX 5060 Ti Clocks (2850MHz / 14001MHz / 180W)..."
        nvidia-smi -lgc 2850,2850 2>$null
        nvidia-smi -lmc 14001,14001 2>$null
        nvidia-smi -pl 180.00 2>$null
    }
} catch {
    Write-Warning "GPU Clock pinning skipped or requires elevation: $($_.Exception.Message)"
}

$logDir = Join-Path $env:LOCALAPPDATA "Temp\hermes-llama"
New-Item -ItemType Directory -Force -Path $logDir | Out-Null
$stdoutPath = Join-Path $logDir "hikari-stdout.log"
$stderrPath = Join-Path $logDir "hikari-stderr.log"

$serverArgs = @(
    "-m", $GgufPath,
    "-c", "$CtxSize",
    "--parallel", "$Parallel",
    "--threads", "6",
    "--batch-size", "2048",
    "--ubatch-size", "512",
    "-fa", "on",
    "-ctk", "q8_0",
    "-ctv", "q4_0",
    "--spec-type", "ngram-mod",
    "--spec-ngram-mod-n-min", "1",
    "--spec-ngram-mod-n-max", "$DraftNMax",
    "--jinja",
    "--alias", "Hikari-LoRA-fixed-scale-PQ2_0,qwen3.8-27b-abliterated-mtp",
    "--host", "127.0.0.1",
    "--port", "$Port"
)

Write-Host "launching: $ServerExe $($serverArgs -join ' ')"
$proc = Start-Process -FilePath $ServerExe -ArgumentList $serverArgs `
    -RedirectStandardOutput $stdoutPath -RedirectStandardError $stderrPath `
    -WindowStyle Hidden -PassThru

Write-Host "pid=$($proc.Id) waiting for /health on port $Port"

$deadline = (Get-Date).AddSeconds($WaitSeconds)
while ((Get-Date) -lt $deadline) {
    if ($proc.HasExited) {
        throw "llama-server exited early (code $($proc.ExitCode)). stderr=$stderrPath"
    }
    try {
        $r = Invoke-RestMethod -Uri "http://127.0.0.1:$Port/health" -TimeoutSec 5
        if ($r.status -eq "ok") {
            Write-Host "READY pid=$($proc.Id) port=$Port model=Hikari-LoRA-fixed-scale-PQ2_0"
            exit 0
        }
    } catch {
        Start-Sleep -Seconds 5
    }
}

throw "llama-server did not become ready within $WaitSeconds s. stdout=$stdoutPath stderr=$stderrPath"
