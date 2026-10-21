<#
.SYNOPSIS
    Computes the llama.cpp KV-cache footprint of a local GGUF server and the
    context window that actually fits in the GPU.

.DESCRIPTION
    A local llama-server's usable speed is decided by whether the KV cache
    for the requested context fits in VRAM next to the model weights. When it
    does not, Windows WDDM backs the allocation with system memory and every
    prompt read and generated token crosses PCIe — the server looks hung
    (long prompt reads with no output), and Hermes' compression no-progress
    window fires on a healthy-but-slow server.

    This helper reads the GGUF architecture metadata, computes the KV bytes
    per token for the requested cache types, and reports:
      * the KV bytes per token and the KV size for the requested context,
      * the EFFECTIVE per-slot context (llama.cpp divides -c across
        --parallel slots),
      * the largest per-slot context that still fits in the GPU with
        headroom for the other applications on the workstation.

    It is provider-agnostic: the arithmetic is llama.cpp's, so it holds
    identically for a stock llama.cpp build and for a PrismL build.

.PARAMETER ModelPath
    Path to the GGUF model the server will load.

.PARAMETER ContextTokens
    The total -c value the server will be launched with.

.PARAMETER ParallelSlots
    The --parallel value (llama.cpp splits the context across the slots).

.PARAMETER CacheTypeK
    K-cache quantization (f16, q8_0, q5_1, q5_0, q4_1, q4_0).

.PARAMETER CacheTypeV
    V-cache quantization.

.PARAMETER HeadroomMiB
    VRAM left free for the desktop, browsers and the compute buffers.

.PARAMETER TotalVramMiB
    Total VRAM of the target GPU. Read from nvidia-smi when omitted.

.EXAMPLE
    . "$PSScriptRoot\Get-LlamaContextBudget.ps1"
    Get-LlamaContextBudget -ModelPath $gguf -ContextTokens 98304 -ParallelSlots 1
#>

Set-StrictMode -Version Latest

# Bytes per element for each supported KV cache quantization.
$script:KvCacheTypeBytes = @{
    'f16'   = 2.0
    'bf16'  = 2.0
    'q8_0'  = 1.0625
    'q5_1'  = 0.6875
    'q5_0'  = 0.5625
    'q4_1'  = 0.5625
    'q4_0'  = 0.5625
}

function Get-GgufArchitectureMetadata {
    <#
    .SYNOPSIS
        Reads the architecture KV pairs from a GGUF header.

    .DESCRIPTION
        Only the scalar architecture keys are materialised. Arrays (the
        tokenizer vocabulary can hold hundreds of thousands of entries) are
        skipped by seeking, and the scan stops as soon as the architecture
        keys have been seen.
    #>
    param([Parameter(Mandatory)][string]$Path)

    $fs = [System.IO.File]::Open($Path, [System.IO.FileMode]::Open, [System.IO.FileAccess]::Read, [System.IO.FileShare]::ReadWrite)
    $br = New-Object System.IO.BinaryReader($fs)
    try {
        $magic = [System.Text.Encoding]::ASCII.GetString($br.ReadBytes(4))
        if ($magic -ne 'GGUF') { throw "Not a GGUF file: $Path" }
        $version = $br.ReadUInt32()
        if ($version -eq 1) {
            $null = $br.ReadUInt32(); $kvCount = $br.ReadUInt32()
        } elseif ($version -eq 2) {
            $null = $br.ReadUInt32(); $kvCount = $br.ReadUInt32()
        } else {
            $null = $br.ReadUInt64(); $kvCount = $br.ReadUInt64()
        }

        $script:GgufScalarSizes = @{ 0 = 1; 1 = 1; 2 = 2; 3 = 2; 4 = 4; 5 = 4; 6 = 4; 7 = 1; 10 = 8; 11 = 8; 12 = 8 }

        function Read-GgufString([System.IO.BinaryReader]$Reader) {
            $len = $Reader.ReadUInt64()
            if ($len -gt 1048576) { throw "Implausible GGUF string length: $len" }
            return [System.Text.Encoding]::UTF8.GetString($Reader.ReadBytes([int]$len))
        }

        function Skip-GgufValue([System.IO.BinaryReader]$Reader, [int]$Type) {
            if ($Type -eq 8) {
                $len = $Reader.ReadUInt64()
                $null = $Reader.BaseStream.Seek([int64]$len, [System.IO.SeekOrigin]::Current)
                return
            }
            if ($Type -eq 9) {
                $elemType = $Reader.ReadUInt32()
                $count = $Reader.ReadUInt64()
                if ($elemType -eq 8) {
                    for ($i = [uint64]0; $i -lt $count; $i++) {
                        $len = $Reader.ReadUInt64()
                        $null = $Reader.BaseStream.Seek([int64]$len, [System.IO.SeekOrigin]::Current)
                    }
                    return
                }
                $elemSize = [int]$script:GgufScalarSizes[[int]$elemType]
                $null = $Reader.BaseStream.Seek([int64]($count * $elemSize), [System.IO.SeekOrigin]::Current)
                return
            }
            $size = [int]$script:GgufScalarSizes[[int]$Type]
            $null = $Reader.BaseStream.Seek([int64]$size, [System.IO.SeekOrigin]::Current)
        }

        $values = @{}
        for ($i = [uint64]0; $i -lt $kvCount; $i++) {
            $key = Read-GgufString $br
            $type = $br.ReadUInt32()
            switch ($type) {
                0 { $values[$key] = $br.ReadByte() }
                1 { $values[$key] = $br.ReadSByte() }
                2 { $values[$key] = $br.ReadUInt16() }
                3 { $values[$key] = $br.ReadInt16() }
                4 { $values[$key] = $br.ReadUInt32() }
                5 { $values[$key] = $br.ReadInt32() }
                6 { $values[$key] = $br.ReadSingle() }
                7 { $values[$key] = [bool]$br.ReadByte() }
                8 { $values[$key] = Read-GgufString $br }
                default { Skip-GgufValue $br $type }
            }
            if ($values.ContainsKey('general.architecture')) {
                $arch = $values['general.architecture']
                if ($values.ContainsKey("$arch.block_count") -and
                    $values.ContainsKey("$arch.attention.head_count_kv") -and
                    $values.ContainsKey("$arch.attention.key_length") -and
                    $values.ContainsKey("$arch.attention.value_length")) {
                    break
                }
            }
        }
        return $values
    } finally {
        $br.Dispose()
        $fs.Dispose()
    }
}

function Get-GpuTotalMemoryMiB {
    <#
    .SYNOPSIS
        Total VRAM of the first NVIDIA GPU, or $null when unknown.
    #>
    param([string]$DeviceIndex = '0')
    try {
        $smi = Get-Command nvidia-smi -ErrorAction SilentlyContinue
        if (-not $smi) { return $null }
        $raw = & nvidia-smi --query-gpu=memory.total --format=csv,noheader,nounits -i $DeviceIndex 2>$null
        if ($LASTEXITCODE -ne 0 -or -not $raw) { return $null }
        return [int]($raw | Select-Object -First 1)
    } catch {
        return $null
    }
}

function Get-LlamaContextBudget {
    <#
    .SYNOPSIS
        KV-cache footprint and the GPU-fitting context for a local server.
    #>
    param(
        [Parameter(Mandatory)][string]$ModelPath,
        [int]$ContextTokens = 98304,
        [int]$ParallelSlots = 1,
        [string]$CacheTypeK = 'q4_0',
        [string]$CacheTypeV = 'q4_0',
        [int]$HeadroomMiB = 3072,
        [int]$TotalVramMiB = 0
    )

    if ($ParallelSlots -lt 1) { $ParallelSlots = 1 }
    $meta = Get-GgufArchitectureMetadata -Path $ModelPath
    $arch = $meta['general.architecture']
    if (-not $arch) { throw "GGUF has no general.architecture: $ModelPath" }

    $layers = [int]$meta["$arch.block_count"]
    $headCountKv = [int]$meta["$arch.attention.head_count_kv"]
    if ($headCountKv -le 0) { $headCountKv = [int]$meta["$arch.attention.head_count"] }
    $keyLength = [int]$meta["$arch.attention.key_length"]
    $valueLength = [int]$meta["$arch.attention.value_length"]
    if ($layers -le 0 -or $headCountKv -le 0 -or $keyLength -le 0) {
        throw "GGUF is missing the attention metadata needed to size the KV cache: $ModelPath"
    }

    $bytesK = $script:KvCacheTypeBytes[$CacheTypeK.ToLowerInvariant()]
    $bytesV = $script:KvCacheTypeBytes[$CacheTypeV.ToLowerInvariant()]
    if ($null -eq $bytesK -or $null -eq $bytesV) { throw "Unsupported KV cache type: $CacheTypeK / $CacheTypeV" }

    # K and V are stored with their own head dimensions.
    $bytesPerToken = $layers * $headCountKv * ($keyLength * $bytesK + $valueLength * $bytesV)

    $modelBytes = (Get-Item -LiteralPath $ModelPath).Length
    if ($TotalVramMiB -le 0) { $TotalVramMiB = Get-GpuTotalMemoryMiB }
    $totalVramBytes = [int64]$TotalVramMiB * 1MB
    $headroomBytes = [int64]$HeadroomMiB * 1MB
    $budgetForKv = $totalVramBytes - $modelBytes - $headroomBytes

    $perSlotContext = [int]($ContextTokens / $ParallelSlots)
    $requestedKvBytes = [int64]$bytesPerToken * $ContextTokens
    $fits = $false
    $maxFittingPerSlot = 0
    if ($budgetForKv -gt 0) {
        $maxFittingTotal = [int64]($budgetForKv / $bytesPerToken)
        $maxFittingPerSlot = [int]($maxFittingTotal / $ParallelSlots)
        $fits = ($requestedKvBytes -le $budgetForKv)
    }

    return [pscustomobject]@{
        ModelPath            = $ModelPath
        Architecture         = $arch
        BlockCount           = $layers
        HeadCountKv          = $headCountKv
        KeyLength            = $keyLength
        ValueLength          = $valueLength
        CacheTypeK           = $CacheTypeK
        CacheTypeV           = $CacheTypeV
        BytesPerToken        = [int64]$bytesPerToken
        ModelBytes           = [int64]$modelBytes
        RequestedContext     = $ContextTokens
        ParallelSlots        = $ParallelSlots
        PerSlotContext       = $perSlotContext
        RequestedKvBytes     = $requestedKvBytes
        TotalVramMiB         = $TotalVramMiB
        HeadroomMiB          = $HeadroomMiB
        FitsInVram           = $fits
        MaxFittingPerSlot    = $maxFittingPerSlot
        MaxFittingTotal      = [int]($maxFittingPerSlot * $ParallelSlots)
    }
}

function Get-LlamaFittingContext {
    <#
    .SYNOPSIS
        Largest context that keeps the KV cache resident in the GPU.

    .DESCRIPTION
        The launcher-side counterpart of Get-LlamaContextBudget: given a
        model and a requested context, return the largest context whose KV
        cache still fits next to the weights, floored at ``MinimumTokens``
        (Hermes refuses to run below 64,000 tokens, so a smaller answer is
        reported as a warning rather than silently handed back).

        A context whose KV does not fit is not a faster context — it is a
        slower one: the allocation is backed by system memory, so prompt
        reads cross the bus and the server looks wedged.
    #>
    param(
        [Parameter(Mandatory)][string]$ModelPath,
        [int]$RequestedContext = 98304,
        [int]$ParallelSlots = 1,
        [string]$CacheTypeK = 'q4_0',
        [string]$CacheTypeV = 'q4_0',
        [int]$HeadroomMiB = 3072,
        [int]$MinimumTokens = 65536
    )

    if (-not (Test-Path -LiteralPath $ModelPath)) {
        Write-Warning "Model not found ($ModelPath) — keeping the requested context $RequestedContext."
        return $RequestedContext
    }

    $budget = Get-LlamaContextBudget `
        -ModelPath $ModelPath `
        -ContextTokens $RequestedContext `
        -ParallelSlots $ParallelSlots `
        -CacheTypeK $CacheTypeK `
        -CacheTypeV $CacheTypeV `
        -HeadroomMiB $HeadroomMiB

    if ($budget.FitsInVram) {
        return $RequestedContext
    }

    $fitting = $budget.MaxFittingTotal
    if ($fitting -lt $MinimumTokens) {
        Write-Warning ("The KV cache for -c {0} does not fit in VRAM (max fitting {1}, Hermes needs at least {2}). " +
            "The server will serve the prompt from system memory and prompt reads will collapse to a fraction of their speed. " +
            "Use a smaller-quantised model, a smaller cache type, or a context near {1}.") -f $RequestedContext, $fitting, $MinimumTokens
        return $RequestedContext
    }

    Write-Warning ("-c {0} does not fit in VRAM for this model (KV {1:N2} GiB + weights {2:N2} GiB). Using {3} instead." -f
        $RequestedContext, ($budget.RequestedKvBytes / 1GB), ($budget.ModelBytes / 1GB), $fitting)
    return $fitting
}

function Format-LlamaContextBudget {
    <#
    .SYNOPSIS
        Human-readable report for a Get-LlamaContextBudget result.
    #>
    param([Parameter(Mandatory)]$Budget)

    $lines = @(
        ("model            : {0}" -f $Budget.ModelPath),
        ("architecture     : {0} (layers={1}, kv_heads={2}, head_dim={3}/{4})" -f $Budget.Architecture, $Budget.BlockCount, $Budget.HeadCountKv, $Budget.KeyLength, $Budget.ValueLength),
        ("kv cache type    : {0} / {1}" -f $Budget.CacheTypeK, $Budget.CacheTypeV),
        ("kv bytes/token   : {0:N0} ({1:N2} MiB)" -f $Budget.BytesPerToken, ($Budget.BytesPerToken / 1MB)),
        ("model on disk    : {0:N2} GiB" -f ($Budget.ModelBytes / 1GB)),
        ("total vram       : {0:N0} MiB (headroom {1} MiB)" -f $Budget.TotalVramMiB, $Budget.HeadroomMiB),
        ("requested -c     : {0:N0} over {1} slot(s) -> {2:N0} tokens per slot" -f $Budget.RequestedContext, $Budget.ParallelSlots, $Budget.PerSlotContext),
        ("kv for requested : {0:N2} GiB" -f ($Budget.RequestedKvBytes / 1GB)),
        ("fits in vram     : {0}" -f $Budget.FitsInVram)
    )
    if ($Budget.MaxFittingPerSlot -gt 0) {
        $lines += ("max fitting -c   : {0:N0} total ({1:N0} per slot)" -f $Budget.MaxFittingTotal, $Budget.MaxFittingPerSlot)
    }
    return ($lines -join [Environment]::NewLine)
}

function Test-LlamaContextFits {
    <#
    .SYNOPSIS
        Warns when a local server's context cannot fit in the GPU.

    .DESCRIPTION
        A context whose KV cache does not fit next to the model is not a
        faster context — it is a slower one: the allocation is backed by
        system memory, so every prompt read and generated token crosses the
        bus. The server then looks wedged (long silent prompt reads), which
        is indistinguishable from a hang for Hermes' no-progress watchdogs.

        The warning is advisory: the launcher keeps its configured context
        unless the caller explicitly asks for the fitting one.

    .PARAMETER ModelPath
        The GGUF the server will load.

    .PARAMETER ContextTokens
        The total -c value.

    .PARAMETER ParallelSlots
        The --parallel value.

    .PARAMETER CacheTypeK / CacheTypeV
        KV cache quantizations.

    .PARAMETER HeadroomMiB
        VRAM reserved for the desktop, browsers and the compute buffers.

    .PARAMETER ApplyFittingContext
        Return the largest fitting context instead of the requested one.

    .OUTPUTS
        A hashtable with the budget, the effective context and whether the
        request fits.
    #>
    param(
        [Parameter(Mandatory)][string]$ModelPath,
        [Parameter(Mandatory)][int]$ContextTokens,
        [int]$ParallelSlots = 1,
        [string]$CacheTypeK = 'q4_0',
        [string]$CacheTypeV = 'q4_0',
        [int]$HeadroomMiB = 3072,
        [switch]$ApplyFittingContext
    )

    $budget = Get-LlamaContextBudget `
        -ModelPath $ModelPath `
        -ContextTokens $ContextTokens `
        -ParallelSlots $ParallelSlots `
        -CacheTypeK $CacheTypeK `
        -CacheTypeV $CacheTypeV `
        -HeadroomMiB $HeadroomMiB

    $effective = $ContextTokens
    if (-not $budget.FitsInVram) {
        $recommended = $budget.MaxFittingTotal
        $message = @(
            "WARNING: the requested context does not fit in the GPU.",
            "  requested : -c {0} over {1} slot(s) -> {2} tokens per slot" -f $ContextTokens, $ParallelSlots, $budget.PerSlotContext,
            "  kv cache  : {0:N2} GiB for the requested context (+ {1:N2} GiB of weights)" -f ($budget.RequestedKvBytes / 1GB), ($budget.ModelBytes / 1GB),
            "  gpu       : {0:N0} MiB total, {1} MiB reserved as headroom" -f $budget.TotalVramMiB, $HeadroomMiB,
            "  recommended: -c {0} ({1} tokens per slot) keeps the KV cache resident" -f $recommended, $budget.MaxFittingPerSlot,
            "  A context that does not fit is served from system memory: prompt reads",
            "  and token generation then cross the bus and the server looks wedged."
        ) -join [Environment]::NewLine
        Write-Warning $message
        if ($ApplyFittingContext -and $recommended -gt 0) {
            $effective = $recommended
        }
    }

    return @{
        Budget            = $budget
        RequestedContext  = $ContextTokens
        EffectiveContext  = $effective
        FitsInVram        = $budget.FitsInVram
        RecommendedContext = $budget.MaxFittingTotal
    }
}
