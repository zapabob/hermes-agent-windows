param(
    [Parameter(Mandatory = $true)]
    [string]$InputPath,

    [Parameter(Mandatory = $true)]
    [string]$OutputPath,

    [string]$Format = "wav",
    [string]$Voice = "none",
    [string]$Model = "irodori-tts",
    [double]$Speed = 1.0,
    [string]$BaseUrl = "http://127.0.0.1:8088",
    [string]$StartScriptPath = ""
)

$ErrorActionPreference = "Stop"

if (-not (Test-Path -LiteralPath $InputPath)) {
    throw "Input text file was not found: $InputPath"
}

$healthUrl = "$BaseUrl/health"
try {
    $health = Invoke-RestMethod -Uri $healthUrl -TimeoutSec 3
    if ($health.status -ne "ok") {
        throw "unexpected health status"
    }
} catch {
    if ([string]::IsNullOrWhiteSpace($StartScriptPath)) {
        $StartScriptPath = Join-Path $PSScriptRoot "start-irodori-tts.ps1"
    }
    $endpoint = [Uri]$BaseUrl
    if ($endpoint.Scheme -ne "http" -or $endpoint.Host -notin @("127.0.0.1", "localhost")) {
        throw "Automatic server startup is limited to local HTTP endpoints."
    }
    & $StartScriptPath -HostName $endpoint.Host -Port $endpoint.Port | Out-Null
}

$text = Get-Content -LiteralPath $InputPath -Raw -Encoding UTF8
if ([string]::IsNullOrWhiteSpace($text)) {
    throw "Input text is empty."
}

$resolvedFormat = $Format.Trim().TrimStart(".").ToLowerInvariant()
if (-not @("wav", "mp3", "flac", "opus", "aac", "pcm").Contains($resolvedFormat)) {
    $resolvedFormat = "wav"
}

$resolvedVoice = if ([string]::IsNullOrWhiteSpace($Voice)) { "none" } else { $Voice.Trim() }
$resolvedModel = if ([string]::IsNullOrWhiteSpace($Model)) { "irodori-tts" } else { $Model.Trim() }

$parent = Split-Path -Parent $OutputPath
if ($parent) {
    New-Item -ItemType Directory -Force -Path $parent | Out-Null
}

$jsonEscape = {
    param([string]$Value)
    Add-Type -AssemblyName System.Web
    [System.Web.HttpUtility]::JavaScriptStringEncode($Value)
}
$resolvedSpeed = [Math]::Max(0.25, [Math]::Min(4.0, $Speed))
$payload = '{' +
    '"model":"' + (& $jsonEscape $resolvedModel) + '",' +
    '"input":"' + (& $jsonEscape $text) + '",' +
    '"voice":"' + (& $jsonEscape $resolvedVoice) + '",' +
    '"response_format":"' + (& $jsonEscape $resolvedFormat) + '",' +
    '"speed":' + ([string]::Format([Globalization.CultureInfo]::InvariantCulture, "{0:0.###}", $resolvedSpeed)) +
    '}'

$speechUrl = "$BaseUrl/v1/audio/speech"
$payloadPath = [System.IO.Path]::GetTempFileName()
try {
    $utf8NoBom = New-Object System.Text.UTF8Encoding($false)
    [System.IO.File]::WriteAllText($payloadPath, $payload, $utf8NoBom)

    $curlArgs = @(
        "--fail-with-body",
        "--silent",
        "--show-error",
        "--max-time",
        "900",
        "--request",
        "POST",
        "--url",
        $speechUrl,
        "--header",
        "Content-Type: application/json; charset=utf-8",
        "--data-binary",
        "@$payloadPath",
        "--output",
        $OutputPath
    )
    if ($env:IRODORI_API_KEY) {
        $curlArgs = @(
            "--header",
            "Authorization: Bearer $env:IRODORI_API_KEY"
        ) + $curlArgs
    }

    & curl.exe @curlArgs
    if ($LASTEXITCODE -ne 0) {
        throw "curl.exe exited with code $LASTEXITCODE while calling $speechUrl"
    }
} finally {
    Remove-Item -LiteralPath $payloadPath -Force -ErrorAction SilentlyContinue
}

if (-not (Test-Path -LiteralPath $OutputPath) -or (Get-Item -LiteralPath $OutputPath).Length -le 0) {
    throw "Irodori-TTS did not produce audio at $OutputPath"
}

Write-Output $OutputPath
