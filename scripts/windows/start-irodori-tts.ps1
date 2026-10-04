param(
    [string]$RepoDir = "",
    [string]$HostName = "127.0.0.1",
    [int]$Port = 8088,
    [int]$StartupTimeoutSeconds = 90,
    [string]$HfCacheRoot = "",
    [ValidateSet("auto", "cpu", "cuda")]
    [string]$ModelDevice = "auto",
    [ValidateSet("auto", "cpu", "cuda")]
    [string]$CodecDevice = "auto",
    [ValidateSet("auto", "fp32", "bf16", "fp16")]
    [string]$ModelPrecision = "auto",
    [ValidateRange(1024, 1048576)]
    [int]$MinimumFreeGpuMemoryMiB = 6144,
    [string]$BackendExtra = ""
)

$ErrorActionPreference = "Stop"

if ([string]::IsNullOrWhiteSpace($RepoDir)) {
    $hermesRoot = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
    $RepoDir = Join-Path (Split-Path -Parent $hermesRoot) "irodori-tts-server"
}

if (-not (Test-Path -LiteralPath $RepoDir)) {
    throw "Irodori-TTS-Server repo was not found: $RepoDir"
}

$healthUrl = "http://${HostName}:${Port}/health"
try {
    $existing = Invoke-RestMethod -Uri $healthUrl -TimeoutSec 3
    if ($existing.status -eq "ok") {
        Write-Output "Irodori-TTS server already running at $healthUrl"
        exit 0
    }
} catch {
}

$logDir = Join-Path $env:LOCALAPPDATA "hermes\logs"
New-Item -ItemType Directory -Force -Path $logDir | Out-Null

if ([string]::IsNullOrWhiteSpace($HfCacheRoot)) {
    if (Test-Path -LiteralPath "D:\") {
        $HfCacheRoot = "D:\llama-cpp-cache\huggingface"
    } else {
        $HfCacheRoot = Join-Path $env:LOCALAPPDATA "hermes\huggingface"
    }
}
$hfHubCache = Join-Path $HfCacheRoot "hub"
New-Item -ItemType Directory -Force -Path $hfHubCache | Out-Null
$torchCacheRoot = Join-Path $env:LOCALAPPDATA "hermes\torch-cache"
$torchInductorCache = Join-Path $torchCacheRoot "inductor"
New-Item -ItemType Directory -Force -Path $torchInductorCache | Out-Null
if ([string]::IsNullOrWhiteSpace($env:USER) -and -not [string]::IsNullOrWhiteSpace($env:USERNAME)) {
    $env:USER = $env:USERNAME
}
$pythonPath = Join-Path $RepoDir ".venv\Scripts\python.exe"
if (-not (Test-Path -LiteralPath $pythonPath)) {
    throw "Irodori virtual environment was not found: $pythonPath"
}
# Use only spare memory on GPU 0; never alter another service's allocation.
$useCuda = $false
if ($ModelDevice -ne "cpu" -or $CodecDevice -ne "cpu") {
    try {
        $LASTEXITCODE = 0
        $freeOutput = & nvidia-smi --query-gpu=memory.free --format=csv,noheader,nounits -i 0
        if ($LASTEXITCODE -ne 0) { throw "nvidia-smi failed" }
        $freeMiB = 0
        if (-not [int]::TryParse([string]($freeOutput | Select-Object -First 1), [ref]$freeMiB)) {
            throw "nvidia-smi did not report free GPU memory"
        }
        if ($freeMiB -ge $MinimumFreeGpuMemoryMiB) {
            $cudaAvailable = & $pythonPath -I -c "import torch; print(int(torch.cuda.is_available()))"
            $useCuda = $LASTEXITCODE -eq 0 -and ([string]$cudaAvailable).Trim() -eq "1"
        }
        Write-Output "Irodori GPU 0 free memory: $freeMiB MiB; CUDA selected: $useCuda"
    } catch {
        Write-Warning "GPU probe failed; retaining CPU fallback: $($_.Exception.Message)"
    }
    if (-not $useCuda -and ($ModelDevice -eq "cuda" -or $CodecDevice -eq "cuda")) {
        throw "CUDA was requested but unavailable or below $MinimumFreeGpuMemoryMiB MiB free memory."
    }
}
if ($ModelDevice -eq "auto") { $ModelDevice = if ($useCuda) { "cuda" } else { "cpu" } }
if ($CodecDevice -eq "auto") { $CodecDevice = if ($useCuda) { "cuda" } else { "cpu" } }
if ($ModelPrecision -eq "auto") {
    $ModelPrecision = if ($ModelDevice -eq "cuda") { "bf16" } else { "fp32" }
}
if ($useCuda) { $env:CUDA_VISIBLE_DEVICES = "0" }
$env:HF_HOME = $HfCacheRoot
$env:HF_HUB_CACHE = $hfHubCache
$env:HUGGINGFACE_HUB_CACHE = $hfHubCache
$env:HF_HUB_ENABLE_HF_TRANSFER = "0"
$env:HF_HUB_DISABLE_SYMLINKS_WARNING = "1"
$env:TORCH_HOME = $torchCacheRoot
$env:TORCHINDUCTOR_CACHE_DIR = $torchInductorCache
if (-not [string]::IsNullOrWhiteSpace($ModelDevice)) {
    $env:IRODORI_MODEL_DEVICE = $ModelDevice
}
if (-not [string]::IsNullOrWhiteSpace($CodecDevice)) {
    $env:IRODORI_CODEC_DEVICE = $CodecDevice
}
# Lazy loading avoids reserving model memory until speech is requested.
$env:IRODORI_PRELOAD = "false"
$env:IRODORI_MODEL_PRECISION = $ModelPrecision
$env:IRODORI_CODEC_PRECISION = "fp32"
$env:IRODORI_COMPILE_MODEL = "false"


$logPrefix = if ($Port -eq 8088) { "irodori-tts" } else { "irodori-tts-$Port" }
$stdout = Join-Path $logDir "$logPrefix-stdout.log"
$stderr = Join-Path $logDir "$logPrefix-stderr.log"
$arguments = @(
    # Ignore the parent interpreter's paths and user site-packages.
    "-I",
    "-m",
    "irodori_openai_tts",
    "--host",
    $HostName,
    "--port",
    [string]$Port
)

$process = Start-Process `
    -FilePath $pythonPath `
    -ArgumentList $arguments `
    -WorkingDirectory $RepoDir `
    -WindowStyle Hidden `
    -RedirectStandardOutput $stdout `
    -RedirectStandardError $stderr `
    -PassThru

$deadline = (Get-Date).AddSeconds($StartupTimeoutSeconds)
do {
    Start-Sleep -Seconds 1
    if ($process.HasExited) {
        $err = if (Test-Path -LiteralPath $stderr) {
            Get-Content -LiteralPath $stderr -Tail 50 -ErrorAction SilentlyContinue | Out-String
        } else {
            ""
        }
        throw "Irodori-TTS server exited during startup. $err"
    }
    try {
        $health = Invoke-RestMethod -Uri $healthUrl -TimeoutSec 3
        if ($health.status -eq "ok") {
            Write-Output "Irodori-TTS server started at $healthUrl (PID $($process.Id))"
            exit 0
        }
    } catch {
    }
} while ((Get-Date) -lt $deadline)

throw "Irodori-TTS server did not answer $healthUrl within $StartupTimeoutSeconds seconds. Logs: $stdout ; $stderr"
