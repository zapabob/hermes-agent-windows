# llama.cpp router hot-swap launcher (RTX 5060 Ti 16GB / turboquant)
# Primary: current HERMES_LLAMA_* model (default Qwen3.6-35B IQ3_M)
# Secondary: Huihui-gemma-4-12B-agentic-fable5 Q4_K_M (HF cache local GGUF)
# Tertiary: HauhauCS/Qwen3.5-9B-Uncensored-HauhauCS-Aggressive:Q4_K_M
# Same runtime knobs as start-llama-secretary.ps1 / .env — swap via OpenAI "model" field.
#
# Usage:
#   powershell -NoProfile -ExecutionPolicy Bypass -File scripts\windows\start-llama-hotswap.ps1
#   powershell -NoProfile -ExecutionPolicy Bypass -File scripts\windows\start-llama-hotswap.ps1 -ForceRestart -WarmSecondary
#   powershell -NoProfile -ExecutionPolicy Bypass -File scripts\windows\start-llama-hotswap.ps1 -RuntimePresetPath "$env:USERPROFILE\.hermes\llama\models-hotswap-primary-secondary.ini" -ForceRestart
#   # then request any registered model ID via the OpenAI "model" field
#
# VRAM: --models-max 1 (default) so only one GGUF is resident; requesting the other unloads LRU.
# Warm standby: secondary stays registered + file-cached; -WarmSecondary does load->unload->reload primary
# to page-cache the secondary GGUF without leaving it on GPU.
# A runtime preset stays under Hermes home and is never copied back into this repository.

param(
    [int]$WaitSeconds = 300,
    [int]$ModelsMax = 1,
    [string]$PresetPath = "",
    [string]$RuntimePresetPath = "",
    [int]$BasePort = 0,
    [string]$Model = "",
    [switch]$VerboseLog,
    # Autoload is required for router hot-swap to dynamically load non-startup preset models upon request.
    # Opt out with -NoAutoload. -AllowAutoload is retained for backward compatibility.
    [switch]$NoAutoload,
    [switch]$AllowAutoload,
    [switch]$ForceRestart,
    [switch]$WarmSecondary
)

$ErrorActionPreference = "Stop"

function Import-HermesDotEnvKeys {
    $dotEnv = Join-Path $env:USERPROFILE ".hermes\.env"
    if (-not (Test-Path -LiteralPath $dotEnv)) { return }
    Get-Content -LiteralPath $dotEnv | ForEach-Object {
        $line = $_.Trim()
        if (-not $line -or $line.StartsWith('#')) { return }
        $eq = $line.IndexOf('=')
        if ($eq -lt 1) { return }
        $key = $line.Substring(0, $eq).Trim().Trim([char]0xFEFF)
        if ($key -notlike 'HERMES_LLAMA_*' -and $key -notin @('HF_HUB_CACHE', 'HF_HOME')) { return }
        if (-not [string]::IsNullOrWhiteSpace((Get-Item -Path "Env:$key" -ErrorAction SilentlyContinue).Value)) { return }
        $value = $line.Substring($eq + 1).Trim().Trim('"').Trim("'")
        if ($value) { Set-Item -Path "Env:$key" -Value $value }
    }
}

function Resolve-Default {
    param([string]$Name, [string]$Default)
    $fromEnv = [Environment]::GetEnvironmentVariable($Name)
    if (-not [string]::IsNullOrWhiteSpace($fromEnv)) { return $fromEnv }
    return $Default
}

function Get-RuntimePresetModelIds {
    param([string]$Path)

    $modelIds = @()
    $startupIds = @()
    $currentSection = ""
    foreach ($rawLine in (Get-Content -LiteralPath $Path)) {
        $line = $rawLine.Trim()
        if (-not $line -or $line.StartsWith(";")) { continue }
        if ($line -match '^\[([^\]]+)\]$') {
            $currentSection = $Matches[1].Trim()
            continue
        }
        if ($currentSection -and $currentSection -ne "*" -and $line -match '^model\s*=') {
            if ($modelIds -notcontains $currentSection) { $modelIds += $currentSection }
            continue
        }
        if ($currentSection -and $currentSection -ne "*" -and $line -match '^load-on-startup\s*=\s*(true|1|yes)$') {
            if ($startupIds -notcontains $currentSection) { $startupIds += $currentSection }
        }
    }

    if ($modelIds.Count -eq 0) {
        throw "Runtime preset contains no named model sections: $Path"
    }
    $primaryCandidates = @($startupIds | Where-Object { $modelIds -contains $_ })
    $primary = if ($primaryCandidates.Count -gt 0) { [string]$primaryCandidates[0] } else { [string]$modelIds[0] }
    $secondaryCandidates = @($modelIds | Where-Object { $_ -ne $primary })
    $secondary = if ($secondaryCandidates.Count -gt 0) { [string]$secondaryCandidates[0] } else { "" }
    return [pscustomobject]@{
        PrimaryId = $primary
        SecondaryId = $secondary
        ModelIds = @($modelIds)
    }
}

function Resolve-TertiaryGgufPath {
    $candidates = @(
        $env:HERMES_LLAMA_TERTIARY_MODEL,
        (Join-Path -Path $env:USERPROFILE -ChildPath "Desktop\SO8T\gguf_models\HauhauCS\Qwen3.5-9B-Uncensored-HauhauCS-Aggressive\Qwen3.5-9B-Uncensored-HauhauCS-Aggressive-Q4_K_M.gguf")
    ) | Where-Object { -not [string]::IsNullOrWhiteSpace($_) }
    foreach ($p in $candidates) {
        if ((Test-Path -LiteralPath $p) -and -not ((Get-Item -LiteralPath $p).PSIsContainer) -and ((Get-Item -LiteralPath $p).Length -gt 1GB)) {
            return (Resolve-Path -LiteralPath $p).Path
        }
    }
    throw "Tertiary GGUF not found: HauhauCS/Qwen3.5-9B-Uncensored-HauhauCS-Aggressive:Q4_K_M"
}

function Resolve-SecondaryGgufPath {
    $candidates = @(
        "H:\elt_data\gguf_models\mradermacher\Huihui-gemma-4-12B-agentic-fable5-abliterated-GGUF\Huihui-gemma-4-12B-agentic-fable5-abliterated.Q4_K_M.gguf"
    )
    $metaPath = Join-Path $env:USERPROFILE ".hermes\logs\llama-hf-download\hf-hub-huihui-latest.json"
    if (Test-Path -LiteralPath $metaPath) {
        try {
            $meta = Get-Content -LiteralPath $metaPath -Raw | ConvertFrom-Json
            if ($meta.path) { $candidates = @($meta.path) + $candidates }
        } catch {}
    }
    foreach ($p in $candidates) {
        if ((Test-Path -LiteralPath $p) -and -not ((Get-Item -LiteralPath $p).PSIsContainer) -and ((Get-Item -LiteralPath $p).Length -gt 1GB)) {
            return (Resolve-Path -LiteralPath $p).Path
        }
    }
    $cacheRoot = if ($env:HF_HUB_CACHE) { $env:HF_HUB_CACHE } else { "H:\elt_data\hf-cache" }
    $pattern = "Huihui-gemma-4-12B-agentic-fable5-abliterated.Q4_K_M.gguf"
    $hits = Get-ChildItem -LiteralPath $cacheRoot -Recurse -Filter $pattern -ErrorAction SilentlyContinue |
        Where-Object { -not $_.PSIsContainer -and $_.Length -gt 1GB } |
        Sort-Object LastWriteTime -Descending
    if ($hits -and $hits.Count -gt 0) {
        return $hits[0].FullName
    }
    throw "Secondary GGUF not found. Run: powershell -File scripts\windows\download-huihui-gemma-agentic-q4km.ps1"
}

function Stop-LlamaOnPort {
    param([int]$TargetPort)
    # Prefer graceful unload via router API, then TerminateProcess.
    # Avoid Get-NetTCPConnection / Get-CimInstance / blocking taskkill — they hang on this host.
    try {
        $tmp = Join-Path $env:TEMP "llama-unload-all.json"
        $listed = Invoke-RestMethod -Uri "http://127.0.0.1:${TargetPort}/v1/models" -TimeoutSec 3
        foreach ($row in @($listed.data)) {
            $st = if ($row.status) { [string]$row.status.value } else { "" }
            if ($st -eq "loaded") {
                [System.IO.File]::WriteAllText($tmp, ("{`"model`":`"{0}`"}" -f $row.id))
                curl.exe -s --max-time 60 -X POST "http://127.0.0.1:${TargetPort}/models/unload" -H "Content-Type: application/json" --data-binary "@$tmp" | Out-Null
            }
        }
    } catch {}

    $pids = New-Object 'System.Collections.Generic.HashSet[int]'
    try {
        $net = & netstat.exe -ano -p tcp 2>$null
        foreach ($line in $net) {
            if ($line -notmatch 'LISTENING') { continue }
            if ($line -notmatch (":{0}\s+" -f $TargetPort)) { continue }
            $parts = ($line -split '\s+') | Where-Object { $_ }
            $own = 0
            if ([int]::TryParse($parts[-1], [ref]$own) -and $own -gt 0) { [void]$pids.Add($own) }
        }
    } catch {}
    # Fall back to image-name discovery only when the requested listener was
    # not discoverable.  A normal port-targeted restart must leave other
    # llama-server instances, such as the embedding service, untouched.
    if ($pids.Count -eq 0) {
        try {
            $task = & tasklist.exe /FI "IMAGENAME eq llama-server.exe" /FO CSV /NH 2>$null
            foreach ($row in $task) {
                if ($row -match '"llama-server\.exe","(\d+)"') {
                    [void]$pids.Add([int]$Matches[1])
                }
            }
        } catch {}
    }

    if (-not ("KillNativeLlama" -as [type])) {
        Add-Type -TypeDefinition @"
using System;
using System.Runtime.InteropServices;
public static class KillNativeLlama {
  [DllImport("kernel32.dll", SetLastError=true)]
  public static extern IntPtr OpenProcess(uint access, bool inherit, int pid);
  [DllImport("kernel32.dll", SetLastError=true)]
  public static extern bool TerminateProcess(IntPtr handle, uint code);
  [DllImport("kernel32.dll", SetLastError=true)]
  public static extern bool CloseHandle(IntPtr handle);
}
"@
    }
    foreach ($procId in @($pids)) {
        try {
            $h = [KillNativeLlama]::OpenProcess(0x0001, $false, $procId)
            if ($h -ne [IntPtr]::Zero) {
                [void][KillNativeLlama]::TerminateProcess($h, 1)
                [void][KillNativeLlama]::CloseHandle($h)
            }
        } catch {}
        # Non-blocking fallback; do not wait on hung taskkill.
        Start-Process -FilePath "taskkill.exe" -ArgumentList @("/F", "/PID", "$procId") -WindowStyle Hidden -ErrorAction SilentlyContinue | Out-Null
    }
    Start-Sleep -Seconds 2
}

function Write-HotswapPreset {
    param(
        [string]$OutPath,
        [string]$PrimaryPath,
        [string]$PrimaryId,
        [string]$SecondaryPath,
        [string]$SecondaryId,
        [string]$TertiaryPath,
        [string]$TertiaryId,
        [int]$Ctx,
        [int]$GpuLayers,
        [int]$Threads,
        [int]$Parallel,
        [string]$CacheK,
        [string]$CacheV,
        [int]$BatchSize,
        [int]$UbatchSize
    )
    $dir = Split-Path -Parent $OutPath
    New-Item -ItemType Directory -Path $dir -Force | Out-Null
    $ini = @"
; Auto-generated by start-llama-hotswap.ps1 - do not hand-edit while server is running.
version = 1

[*]
c = $Ctx
ngl = $GpuLayers
n-gpu-layers = $GpuLayers
t = $Threads
threads = $Threads
np = $Parallel
parallel = $Parallel
flash-attn = on
jinja = true
cont-batching = true
batch-size = $BatchSize
ubatch-size = $UbatchSize
cache-type-k = $CacheK
cache-type-v = $CacheV

[$PrimaryId]
model = $PrimaryPath
load-on-startup = true
stop-timeout = 30

[$SecondaryId]
model = $SecondaryPath
load-on-startup = false
stop-timeout = 30

[$TertiaryId]
model = $TertiaryPath
load-on-startup = false
stop-timeout = 30
"@
    [System.IO.File]::WriteAllText($OutPath, $ini, [System.Text.UTF8Encoding]::new($false))
}

function Test-PortListening {
    param([string]$TargetHost, [int]$TargetPort)
    try {
        $tcp = New-Object System.Net.Sockets.TcpClient
        $iar = $tcp.BeginConnect($TargetHost, $TargetPort, $null, $null)
        $ok = $iar.AsyncWaitHandle.WaitOne(800)
        if ($ok -and $tcp.Connected) { $tcp.EndConnect($iar); $tcp.Close(); return $true }
        $tcp.Close()
    } catch {}
    return $false
}

function Get-RouterModelStatus {
    param(
        [string]$RouterUrl,
        [string]$ModelId
    )
    $models = Invoke-RestMethod -Uri "$RouterUrl/v1/models" -TimeoutSec 10
    $row = @($models.data | Where-Object { $_.id -eq $ModelId }) | Select-Object -First 1
    if ($row -and $row.status) { return [string]$row.status.value }
    return "missing"
}

function Wait-RouterModelStatus {
    param(
        [string]$RouterUrl,
        [string]$ModelId,
        [string[]]$ExpectedStatus,
        [int]$TimeoutSec = 600
    )
    $deadline = (Get-Date).AddSeconds($TimeoutSec)
    $lastStatus = "missing"
    while ((Get-Date) -lt $deadline) {
        $lastStatus = Get-RouterModelStatus -RouterUrl $RouterUrl -ModelId $ModelId
        if ($lastStatus -in $ExpectedStatus) {
            return $lastStatus
        }
        if ($lastStatus -in @("failed", "error")) {
            throw "Model '$ModelId' entered status '$lastStatus'."
        }
        Start-Sleep -Seconds 2
    }
    throw "Timed out waiting for model '$ModelId' status '$($ExpectedStatus -join '/')'; last status was '$lastStatus'."
}

function Invoke-WarmSecondary {
    param(
        [string]$RouterUrl,
        [string]$PrimaryId,
        [string]$SecondaryId,
        [int]$TimeoutSec = 600
    )
    Write-Output "Warm-standby: loading secondary '$SecondaryId' once (LRU will unload primary)..."
    $modelBody = @{ model = $SecondaryId } | ConvertTo-Json
    $secondaryStatus = Get-RouterModelStatus -RouterUrl $RouterUrl -ModelId $SecondaryId
    if ($secondaryStatus -notin @("loaded", "ready", "loading")) {
        $null = Invoke-RestMethod -Uri "$RouterUrl/models/load" -Method Post -Body $modelBody -ContentType "application/json" -TimeoutSec 15
    }
    $null = Wait-RouterModelStatus -RouterUrl $RouterUrl -ModelId $SecondaryId -ExpectedStatus @("loaded", "ready") -TimeoutSec $TimeoutSec
    $bodySec = @{
        model = $SecondaryId
        max_tokens = 4
        messages = @(@{ role = "user"; content = "warm" })
    } | ConvertTo-Json -Depth 5
    $null = Invoke-RestMethod -Uri "$RouterUrl/v1/chat/completions" -Method Post -Body $bodySec -ContentType "application/json" -TimeoutSec $TimeoutSec
    Write-Output "Warm-standby: unloading secondary '$SecondaryId'..."
    if ((Get-RouterModelStatus -RouterUrl $RouterUrl -ModelId $SecondaryId) -ne "unloaded") {
        $null = Invoke-RestMethod -Uri "$RouterUrl/models/unload" -Method Post -Body $modelBody -ContentType "application/json" -TimeoutSec 15
    }
    $null = Wait-RouterModelStatus -RouterUrl $RouterUrl -ModelId $SecondaryId -ExpectedStatus @("unloaded") -TimeoutSec $TimeoutSec
    Write-Output "Warm-standby: reloading primary '$PrimaryId'..."
    $modelBody = @{ model = $PrimaryId } | ConvertTo-Json
    $primaryStatus = Get-RouterModelStatus -RouterUrl $RouterUrl -ModelId $PrimaryId
    if ($primaryStatus -notin @("loaded", "ready", "loading")) {
        $null = Invoke-RestMethod -Uri "$RouterUrl/models/load" -Method Post -Body $modelBody -ContentType "application/json" -TimeoutSec 15
    }
    $null = Wait-RouterModelStatus -RouterUrl $RouterUrl -ModelId $PrimaryId -ExpectedStatus @("loaded", "ready") -TimeoutSec $TimeoutSec
    $bodyPri = @{
        model = $PrimaryId
        max_tokens = 4
        messages = @(@{ role = "user"; content = "warm" })
    } | ConvertTo-Json -Depth 5
    $null = Invoke-RestMethod -Uri "$RouterUrl/v1/chat/completions" -Method Post -Body $bodyPri -ContentType "application/json" -TimeoutSec $TimeoutSec
    $models = Invoke-RestMethod -Uri "$RouterUrl/v1/models" -TimeoutSec 10
    foreach ($row in $models.data) {
        Write-Output ("warm-status {0}={1}" -f $row.id, $row.status.value)
    }
}

Import-HermesDotEnvKeys

if (-not $env:HF_HUB_CACHE) {
    $env:HF_HUB_CACHE = "H:\elt_data\hf-cache"
}
New-Item -ItemType Directory -Path $env:HF_HUB_CACHE -Force | Out-Null

$ServerExe = Resolve-Default "HERMES_LLAMA_SERVER_EXE" (Join-Path $env:LOCALAPPDATA "Programs\llama-turboquant\bin\llama-server.exe")
$HostName = Resolve-Default "HERMES_LLAMA_HOST" "127.0.0.1"
$Port = if ($BasePort -gt 0) { $BasePort } else { [int](Resolve-Default "HERMES_LLAMA_PORT" "8080") }
if (-not $RuntimePresetPath -and -not $PresetPath) {
    $defaultPreset = Join-Path $env:USERPROFILE ".hermes\llama\models-hotswap-primary-secondary.ini"
    if (Test-Path -LiteralPath $defaultPreset) {
        $RuntimePresetPath = $defaultPreset
    }
}
$UsingRuntimePreset = -not [string]::IsNullOrWhiteSpace($RuntimePresetPath)
if ($UsingRuntimePreset) {
    if (-not (Test-Path -LiteralPath $RuntimePresetPath)) {
        throw "Runtime preset not found: $RuntimePresetPath"
    }
    $PresetPath = (Resolve-Path -LiteralPath $RuntimePresetPath).Path
    $runtimeModels = Get-RuntimePresetModelIds -Path $PresetPath
    $PrimaryId = $runtimeModels.PrimaryId
    $SecondaryId = $runtimeModels.SecondaryId
    $TertiaryId = ""
    $PrimaryPath = "[runtime-preset]"
    $SecondaryPath = "[runtime-preset]"
    $TertiaryPath = ""
} else {
    $PrimaryPath = Resolve-Default "HERMES_LLAMA_GGUF_PATH" (Join-Path -Path $env:USERPROFILE -ChildPath "Desktop\SO8T\gguf_models\Qwen3.6-35B-A3B-Uncensored-HauhauCS-Aggressive-IQ3_M.gguf")
    $PrimaryId = Resolve-Default "HERMES_LLAMA_ALIAS" (Resolve-Default "HERMES_LLAMA_MODEL" "Qwen3.6-35B-A3B-Uncensored-IQ3_M")
    $SecondaryId = "Huihui-gemma-4-12B-agentic-fable5-Q4_K_M"
    $SecondaryPath = Resolve-SecondaryGgufPath
    $TertiaryId = "HauhauCS/Qwen3.5-9B-Uncensored-HauhauCS-Aggressive:Q4_K_M"
    $TertiaryPath = Resolve-TertiaryGgufPath
    $Ctx = [int](Resolve-Default "HERMES_LLAMA_CTX" "65536")
    $CacheK = Resolve-Default "HERMES_LLAMA_CACHE_TYPE_K" "turbo3"
    $CacheV = Resolve-Default "HERMES_LLAMA_CACHE_TYPE_V" "turbo3"
    $Threads = [int](Resolve-Default "HERMES_LLAMA_THREADS" "8")
    $Parallel = [int](Resolve-Default "HERMES_LLAMA_PARALLEL" "1")
    $GpuLayers = [int](Resolve-Default "HERMES_LLAMA_GPU_LAYERS" "99")
    $BatchSize = [int](Resolve-Default "HERMES_LLAMA_BATCH_SIZE" "2048")
    $UbatchSize = [int](Resolve-Default "HERMES_LLAMA_UBATCH_SIZE" "512")
    if ($Ctx -lt 64000) {
        throw "HERMES_LLAMA_CTX=$Ctx is below the Hermes Agent minimum of 64000. Set HERMES_LLAMA_CTX=65536."
    }
    if (-not (Test-Path -LiteralPath $PrimaryPath)) {
        throw "Primary GGUF not found: $PrimaryPath"
    }
}
if (-not (Test-Path -LiteralPath $ServerExe)) {
    throw "llama-server not found: $ServerExe"
}
$ExpectedModelIds = @($PrimaryId)
if (-not [string]::IsNullOrWhiteSpace($SecondaryId)) { $ExpectedModelIds += $SecondaryId }
if (-not [string]::IsNullOrWhiteSpace($TertiaryId)) { $ExpectedModelIds += $TertiaryId }

$helpText = (& $ServerExe --help 2>&1 | Out-String)
if ($helpText -notmatch '--models-preset') {
    throw "This llama-server build lacks --models-preset (router hot-swap). Update llama-turboquant."
}

if ($ForceRestart -and (Test-PortListening -TargetHost $HostName -TargetPort $Port)) {
    Write-Output "ForceRestart: stopping llama on port $Port"
    Stop-LlamaOnPort -TargetPort $Port
}

if (Test-PortListening -TargetHost $HostName -TargetPort $Port) {
    Write-Output "llama.cpp already listening on port $Port. Hot-swap: request model id via /v1/chat/completions."
    try {
        $listed = Invoke-RestMethod -Uri "http://${HostName}:${Port}/v1/models" -TimeoutSec 5
        $ids = @($listed.data | ForEach-Object { $_.id })
        Write-Output ("models: {0}" -f ($ids -join ", "))
        # HF-cache stubs look like org/repo:QUANT
        $hfStubs = @($ids | Where-Object { $_ -match '/' -and $_ -notin $ExpectedModelIds })
        if ($hfStubs.Count -gt 0) {
            Write-Warning ("HF-cache stubs still listed ({0}). Re-run with -ForceRestart to apply hf-cache isolation." -f ($hfStubs -join ", "))
        }
        if ($WarmSecondary) {
            if ([string]::IsNullOrWhiteSpace($SecondaryId)) {
                Write-Warning "Warm standby requested, but the selected preset has no secondary model."
            } else {
                Invoke-WarmSecondary -RouterUrl "http://${HostName}:${Port}" -PrimaryId $PrimaryId -SecondaryId $SecondaryId -TimeoutSec $WaitSeconds
            }
        }
    } catch {
        throw "Existing llama router failed inspection or warm-standby: $($_.Exception.Message)"
    }
    exit 0
}

if (-not $UsingRuntimePreset) {
    if ([string]::IsNullOrWhiteSpace($PresetPath)) {
        $PresetPath = Join-Path $env:USERPROFILE ".hermes\llama\models-hotswap.ini"
    }
    Write-HotswapPreset `
        -OutPath $PresetPath `
        -PrimaryPath ((Resolve-Path -LiteralPath $PrimaryPath).Path) `
        -PrimaryId $PrimaryId `
        -SecondaryPath $SecondaryPath `
        -SecondaryId $SecondaryId `
        -TertiaryPath $TertiaryPath `
        -TertiaryId $TertiaryId `
        -Ctx $Ctx `
        -GpuLayers $GpuLayers `
        -Threads $Threads `
        -Parallel $Parallel `
        -CacheK $CacheK `
        -CacheV $CacheV `
        -BatchSize $BatchSize `
        -UbatchSize $UbatchSize
}

$logDir = Join-Path $env:USERPROFILE ".hermes\logs\llama-hotswap"
New-Item -ItemType Directory -Path $logDir -Force | Out-Null
$stamp = Get-Date -Format "yyyyMMdd_HHmmss"
$stdoutPath = Join-Path $logDir "llama-hotswap-$stamp.out.log"
$stderrPath = Join-Path $logDir "llama-hotswap-$stamp.err.log"

$serverArgs = @(
    "--models-preset", $PresetPath,
    "--models-max", [string]$ModelsMax,
    "--host", $HostName,
    "--port", [string]$Port,
    "--jinja"
)
if (-not $UsingRuntimePreset) {
    $serverArgs += @(
        "--cache-type-k", $CacheK,
        "--cache-type-v", $CacheV,
        "--spec-type", "ngram-mod",
        "--spec-ngram-mod-n-match", "24",
        "--spec-ngram-mod-n-min", "48",
        "--spec-ngram-mod-n-max", "64"
    )
}
$disableAutoload = $NoAutoload
if ($disableAutoload) {
    if ($helpText -match '--no-models-autoload') {
        $serverArgs += @("--no-models-autoload")
    } else {
        Write-Warning "llama-server lacks --no-models-autoload"
    }
}

# llama-server always registers HF hub cache GGUFs as router presets
# ("Loaded N cached model presets"). That surfaces stubs like
# NousResearch/Hermes-3-Llama-3.1-8B-GGUF:Q4_K_M even with --no-models-autoload.
# Point the child at an empty hub cache so /v1/models is preset-only.
# Do NOT delete the real HF cache — downloads stay under HF_HUB_CACHE.
$routerHfCache = Join-Path $env:USERPROFILE ".hermes\llama\router-hf-cache-empty"
New-Item -ItemType Directory -Path $routerHfCache -Force | Out-Null
$hfEnvKeys = @("LLAMA_CACHE", "HF_HUB_CACHE", "HUGGINGFACE_HUB_CACHE", "HF_HOME")
$hfEnvBackup = @{}
foreach ($k in $hfEnvKeys) {
    $hfEnvBackup[$k] = [Environment]::GetEnvironmentVariable($k, "Process")
    Set-Item -Path "Env:$k" -Value $routerHfCache
}

Write-Output "Starting llama router hot-swap on ${HostName}:${Port}"
Write-Output "preset=$PresetPath models-max=$ModelsMax"
Write-Output "primary=$PrimaryId -> $PrimaryPath"
if (-not [string]::IsNullOrWhiteSpace($SecondaryId)) {
    Write-Output "secondary=$SecondaryId -> $SecondaryPath (warm-standby registered)"
}
if (-not [string]::IsNullOrWhiteSpace($TertiaryId)) {
    Write-Output "tertiary=$TertiaryId -> $TertiaryPath (warm-standby registered)"
}
Write-Output "hf-cache-isolated=$routerHfCache (preset-only /v1/models)"

try {
    $proc = Start-Process `
        -FilePath $ServerExe `
        -ArgumentList $serverArgs `
        -RedirectStandardOutput $stdoutPath `
        -RedirectStandardError $stderrPath `
        -WindowStyle Hidden `
        -PassThru
} finally {
    foreach ($k in $hfEnvKeys) {
        $prev = $hfEnvBackup[$k]
        if ([string]::IsNullOrWhiteSpace($prev)) {
            Remove-Item -Path "Env:$k" -ErrorAction SilentlyContinue
        } else {
            Set-Item -Path "Env:$k" -Value $prev
        }
    }
}

$modelsUrl = "http://${HostName}:${Port}/v1/models"
$deadline = (Get-Date).AddSeconds($WaitSeconds)
$listedOnce = $false
$routerReady = $false
while ((Get-Date) -lt $deadline) {
    if ($proc.HasExited) {
        $tail = ""
        try { $tail = [System.IO.File]::ReadAllText($stderrPath) } catch {
            $tail = (Get-Content -LiteralPath $stderrPath -Tail 40 -ErrorAction SilentlyContinue) -join "`n"
        }
        throw "llama-server exited (exit=$($proc.ExitCode)). stderr:`n$tail"
    }
    try {
        $models = Invoke-RestMethod -Uri $modelsUrl -TimeoutSec 3
        $ids = @($models.data | ForEach-Object { $_.id })
        $missingExpectedIds = @($ExpectedModelIds | Where-Object { $_ -notin $ids })
        $hasAllExpectedModels = $missingExpectedIds.Count -eq 0
        if ($hasAllExpectedModels -and -not $listedOnce) {
            $listedOnce = $true
            Write-Output ("router listed all presets: {0}" -f ($ids -join ", "))
        }
        $primaryRow = @($models.data | Where-Object { $_.id -eq $PrimaryId }) | Select-Object -First 1
        $primaryStatus = if ($primaryRow -and $primaryRow.status) { [string]$primaryRow.status.value } else { "" }
        if ($hasAllExpectedModels -and $primaryStatus -notin @("failed", "error")) {
            if ($primaryStatus -in @("", "loading")) {
                Write-Output ("waiting for primary load status=$primaryStatus ...")
                Start-Sleep -Seconds 5
                continue
            }
            Write-Output "llama.cpp hot-swap ready on $modelsUrl"
            Write-Output "pid=$($proc.Id) primary_status=$primaryStatus"
            Write-Output ("models: {0}" -f ($ids -join ", "))
            $swapModelIds = $ExpectedModelIds -join "', '"
            Write-Output ("swap: model='{0}' (models-max={1} LRU)" -f $swapModelIds, $ModelsMax)
            $routerReady = $true
            break
        }
    } catch {
        Start-Sleep -Seconds 2
    }
}

if (-not $routerReady) {
    if (-not $proc.HasExited) {
        Stop-Process -Id $proc.Id -Force -ErrorAction SilentlyContinue
    }
    throw "llama-server hot-swap did not become ready within $WaitSeconds seconds. See $stderrPath"
}

if ($WarmSecondary -and -not [string]::IsNullOrWhiteSpace($SecondaryId)) {
    Invoke-WarmSecondary -RouterUrl "http://${HostName}:${Port}" -PrimaryId $PrimaryId -SecondaryId $SecondaryId -TimeoutSec $WaitSeconds
}
Write-Output "stdout=$stdoutPath"
Write-Output "stderr=$stderrPath"
exit 0
