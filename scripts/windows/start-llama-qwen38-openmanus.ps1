# Start Qwen3.8-27B abliterated MTP llama-server for OpenManus harness.
# Q8_0 K / Turbo3 V KV cache, context sized against the KV footprint
# (98304 requested, clamped to what stays resident in VRAM), MTP speculative
# decoding.
param(
    [string]$ServerExe = "$env:LOCALAPPDATA\Programs\llama-turboquant\bin\llama-server.exe",
    [string]$GgufPath = "C:\Users\downl\Desktop\SO8T\gguf_models\soyaakinohara\qwen3.8-27b-abliterated-3.69bpw-12GB-MTP.gguf\qwen3.8-27b-abliterated-3.69bpw-12GB-MTP.gguf",
    [int]$Port = 8080,
    # The KV cache of a 27B model costs ~72 KiB/token at q4_0, so the context
    # must be sized against the WEIGHTS of the model actually loaded: this
    # one is a 12 GB file, which leaves only a few GiB for the KV. The
    # launcher measures the real footprint below and clamps the window to
    # what stays resident in VRAM.
    [int]$CtxSize = 98304,
    [int]$Parallel = 1,
    [int]$DraftNMax = 3,
    [switch]$CpuMoe,
    [int]$WaitSeconds = 300
)

$ErrorActionPreference = "Stop"

if (-not (Test-Path -LiteralPath $ServerExe)) { throw "llama-server not found: $ServerExe" }
if (-not (Test-Path -LiteralPath $GgufPath)) { throw "GGUF not found: $GgufPath" }

# A context whose KV cache does not fit next to the weights is served from
# system memory: every prompt read and generated token then crosses the bus
# and the server looks wedged to Hermes' no-progress watchdogs. Report the
# budget before starting so the operator sees the real cost of -c.
try {
    . (Join-Path $PSScriptRoot 'Get-LlamaContextBudget.ps1')
    $CtxSize = Get-LlamaFittingContext `
        -ModelPath $GgufPath `
        -RequestedContext $CtxSize `
        -ParallelSlots $Parallel `
        -CacheTypeK 'q8_0' `
        -CacheTypeV 'turbo3'
    $Budget = Get-LlamaContextBudget `
        -ModelPath $GgufPath `
        -ContextTokens $CtxSize `
        -ParallelSlots $Parallel `
        -CacheTypeK 'q8_0' `
        -CacheTypeV 'turbo3'
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

# Free the port if a previous instance is still bound.
$existing = Get-Process -Name "llama-server" -ErrorAction SilentlyContinue
if ($existing) {
    Write-Host "stopping existing llama-server (PID $($existing.Id -join ','))"
    $existing | Stop-Process -Force
    Start-Sleep -Seconds 3
}

$logDir = Join-Path $env:LOCALAPPDATA "Temp\hermes-llama"
New-Item -ItemType Directory -Force -Path $logDir | Out-Null
$stdoutPath = Join-Path $logDir "qwen38-stdout.log"
$stderrPath = Join-Path $logDir "qwen38-stderr.log"

$serverArgs = @(
    "-m", $GgufPath,
    "-c", "$CtxSize",
    # n_slots defaults to 4, so -c is split 4 ways AND four concurrent KV caches
    # are allocated. With ~0.9GB VRAM spare that spills and prompt processing
    # collapses from ~38 tok/s to ~6 tok/s. One slot keeps the full context per
    # request and keeps the KV cache resident.
    "--parallel", "$Parallel",
    # Let llama.cpp fit the GPU/CPU split while retaining GPU offload.
    # -CpuMoe additionally keeps MoE expert weights on the CPU.
    "--fit", "on",
    "--fit-target", "1024",
    "-fa", "on",
    "-ctk", "q8_0",
    "-ctv", "turbo3",
    "--spec-type", "draft-mtp",
    "--spec-draft-n-max", "$DraftNMax",
    "--spec-draft-n-min", "1",
    "--jinja",
    "--alias", "qwen3.8-27b-abliterated-mtp",
    "--no-mmap",
    "--host", "127.0.0.1",
    "--port", "$Port"
)

if ($CpuMoe) {
    $serverArgs += "--cpu-moe"
}

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
            Write-Host "READY pid=$($proc.Id) port=$Port model=qwen3.8-27b-abliterated-mtp"
            exit 0
        }
    } catch {
        Start-Sleep -Seconds 5
    }
}

throw "llama-server did not become ready within $WaitSeconds s. stdout=$stdoutPath stderr=$stderrPath"
