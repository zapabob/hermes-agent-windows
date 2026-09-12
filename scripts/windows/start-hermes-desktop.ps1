param(
    [string]$HermesRoot = "",
    [string]$Cwd = "",
    [string]$HermesHome = "",
    # Bypass watchdog prewarm / desktop-backend.json and let Desktop spawn its
    # own `serve --port 0` (the path that reaches "Finalizing desktop startup").
    [switch]$ForceLocalSpawn
)

$ErrorActionPreference = "Stop"

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$RepoRoot = (Resolve-Path (Join-Path $ScriptDir "..\..")).Path
. (Join-Path $ScriptDir "Resolve-CanonicalHermesHome.ps1")

if (-not $HermesRoot) {
    $HermesRoot = $RepoRoot
}
if (-not $Cwd) {
    $Cwd = $HermesRoot
}
$HermesHome = Resolve-CanonicalHermesHome -Preferred $HermesHome -RepoRoot $RepoRoot

$PythonExe = Join-Path $HermesRoot ".venv\Scripts\python.exe"
if (-not (Test-Path -LiteralPath $PythonExe)) {
    $PythonExe = Join-Path $HermesRoot "venv\Scripts\python.exe"
}
if (-not (Test-Path -LiteralPath $PythonExe)) {
    $PythonExe = (Get-Command python -ErrorAction Stop).Source
}

$env:HERMES_HOME = $HermesHome
$env:HERMES_DESKTOP_HERMES_ROOT = $HermesRoot
$env:HERMES_DESKTOP_CWD = $Cwd
$WebDist = Join-Path $HermesRoot "hermes_cli\web_dist"
if (Test-Path -LiteralPath (Join-Path $WebDist "index.html")) {
    $env:HERMES_DESKTOP_DASHBOARD_WEB_DIST = $WebDist
}
$env:PYTHONUTF8 = "1"
$env:PYTHONIOENCODING = "utf-8"

$staleDesktopPattern = [regex]::Escape("AppData\Local\hermes\hermes-agent\apps\desktop\release\win-unpacked\Hermes.exe")
$staleDesktopProcesses = Get-CimInstance Win32_Process -ErrorAction SilentlyContinue | Where-Object {
    $_.CommandLine -and $_.CommandLine -match $staleDesktopPattern
}
foreach ($proc in $staleDesktopProcesses) {
    Stop-Process -Id $proc.ProcessId -Force -ErrorAction SilentlyContinue
}

# Resolve packaged EXE from the canonical checkout first.  LOCALAPPDATA is
# only a recovery fallback when the explicit HermesRoot has no packaged app.
$PackagedExe = Join-Path $HermesRoot "apps\desktop\release\win-unpacked\Hermes.exe"
if (-not (Test-Path -LiteralPath $PackagedExe)) {
    $PackagedExe = Join-Path $env:LOCALAPPDATA "hermes\hermes-agent\apps\desktop\release\win-unpacked\Hermes.exe"
}

# Electron child processes carry "--type=..." (gpu/renderer/utility). The main
# process does not. Boot races (Session 0 thrash, Startup folder + logon task)
# can leave a main Hermes.exe alive with MainWindowHandle=0 — process exists,
# no visible window. Treating that as "already running" skips logon relaunch
# and the console user sees "desktop did not start".
$packagedExePattern = [regex]::Escape($PackagedExe)
$packagedProcesses = @(Get-CimInstance Win32_Process -ErrorAction SilentlyContinue | Where-Object {
    $_.CommandLine -and $_.CommandLine -match $packagedExePattern
})
$mainProcesses = @($packagedProcesses | Where-Object {
    $_.CommandLine -notmatch '(?i)\s--type='
})

function Test-HermesDesktopVisibleWindow {
    param([Parameter(Mandatory = $true)][int[]]$ProcessIds)
    foreach ($procId in $ProcessIds) {
        if ($procId -le 0) { continue }
        $alive = Get-Process -Id $procId -ErrorAction SilentlyContinue
        if ($null -eq $alive) { continue }
        if ($alive.MainWindowHandle -ne [IntPtr]::Zero) {
            return $true
        }
    }
    return $false
}

function Test-HermesOwnsEphemeralServe {
    param([Parameter(Mandatory = $true)][int[]]$MainProcessIds)
    if ($MainProcessIds.Count -eq 0) { return $false }
    $idSet = @{}
    foreach ($id in $MainProcessIds) { $idSet[[int]$id] = $true }
    $ephemeral = @(Get-CimInstance Win32_Process -ErrorAction SilentlyContinue | Where-Object {
        $_.CommandLine -and $_.CommandLine -match 'serve --host 127\.0\.0\.1 --port 0'
    })
    foreach ($svc in $ephemeral) {
        $parent = [int]$svc.ParentProcessId
        if ($idSet.ContainsKey($parent)) { return $true }
        # Walk one hop: python.exe child of Hermes.exe is common on Windows.
        $parentProc = Get-CimInstance Win32_Process -Filter "ProcessId=$parent" -ErrorAction SilentlyContinue
        if ($null -ne $parentProc -and $idSet.ContainsKey([int]$parentProc.ParentProcessId)) {
            return $true
        }
    }
    return $false
}

if ($mainProcesses.Count -gt 0) {
    $mainIds = @($mainProcesses | ForEach-Object { [int]$_.ProcessId })
    $forceRelaunch = $false
    if (Test-HermesDesktopVisibleWindow -ProcessIds $mainIds) {
        # Dual-backend latch: a visible window that still owns `--port 0` while
        # the Go watchdog manages :9119 stays on the boot overlay forever.
        # Force a clean relaunch so HERMES_DESKTOP_REMOTE_* can attach.
        if (Test-HermesOwnsEphemeralServe -MainProcessIds $mainIds) {
            Write-Host ("[start-hermes-desktop] Visible Hermes.exe owns ephemeral port-0 serve — restarting for managed backend attach: {0}" -f ($mainIds -join ","))
            $forceRelaunch = $true
            foreach ($proc in $packagedProcesses) {
                Stop-Process -Id $proc.ProcessId -Force -ErrorAction SilentlyContinue
            }
            foreach ($svc in @(Get-CimInstance Win32_Process -ErrorAction SilentlyContinue | Where-Object {
                $_.CommandLine -and $_.CommandLine -match 'serve --host 127\.0\.0\.1 --port 0'
            })) {
                Stop-Process -Id $svc.ProcessId -Force -ErrorAction SilentlyContinue
            }
            Start-Sleep -Seconds 2
        } else {
            Write-Host "[start-hermes-desktop] Packaged Hermes.exe already running with a visible window (pid=$($mainIds[0])) — skipping launch."
            exit 0
        }
    }

    if (-not $forceRelaunch) {
        # Young mains may still be creating BrowserWindow; do not thrash them.
        $ghostGraceSeconds = 45
        $now = Get-Date
        $agedGhostIds = @()
        foreach ($main in $mainProcesses) {
            $created = $main.CreationDate
            if ($null -eq $created) { continue }
            $ageSeconds = ($now - [datetime]$created).TotalSeconds
            if ($ageSeconds -ge $ghostGraceSeconds) {
                $agedGhostIds += [int]$main.ProcessId
            }
        }

        if ($agedGhostIds.Count -eq 0) {
            Write-Host "[start-hermes-desktop] Packaged Hermes.exe starting (no HWND yet, age<$ghostGraceSeconds`s) — skipping relaunch."
            exit 0
        }

        Write-Host ("[start-hermes-desktop] Ghost Hermes.exe detected (no visible window, age>={0}s). Restarting: {1}" -f $ghostGraceSeconds, ($agedGhostIds -join ","))
        foreach ($proc in $packagedProcesses) {
            Stop-Process -Id $proc.ProcessId -Force -ErrorAction SilentlyContinue
        }
        Start-Sleep -Seconds 2
    }
}


# Refuse worktree roots — User/agent mistakes keep relaunching .worktrees\* with --skip-build.
$normalizedRoot = [System.IO.Path]::GetFullPath($HermesRoot)
if ($normalizedRoot -match '(?i)[\\/]\.worktrees[\\/]') {
    throw "Refusing Hermes Desktop launch from worktree: $normalizedRoot`nUse canonical repo: C:\Users\downl\Documents\New project\hermes-agent"
}
Set-Location -LiteralPath $HermesRoot

# Launch packaged Hermes.exe — never use --source or node_modules/electron.
# If the EXE is missing, build first: hermes desktop --build-only --force-build
if (-not (Test-Path -LiteralPath $PackagedExe)) {
    throw (
        "Packaged Hermes.exe not found. Build it first:`n" +
        "  hermes desktop --build-only --force-build`n" +
        "Searched:`n" +
        "  $env:LOCALAPPDATA\hermes\hermes-agent\apps\desktop\release\win-unpacked\Hermes.exe`n" +
        "  $HermesRoot\apps\desktop\release\win-unpacked\Hermes.exe"
    )
}

$WorkDir = Split-Path -Parent $PackagedExe

# Prefer the Go watchdog prewarmed backend via Desktop's built-in
# resolveWatchdogPrewarmedBackend (local mode). Forcing
# HERMES_DESKTOP_REMOTE_* against loopback marks the session as "Remote
# gateway", blocks Settings, and on this host leaves the UI stuck on
# CONNECTING (WS ready frame never lands / no usable shell) even when
# /api/sessions is healthy.
$manifestPath = Join-Path $env:LOCALAPPDATA "HermesWatchdog\desktop-backend.json"
$managedUrl = ""
$managedToken = ""

if ($ForceLocalSpawn) {
    # Packaged Desktop adopts desktop-backend.json before spawning. When that
    # prewarm path stalls at progress 94 ("Watchdog-managed ... ready") without
    # "Finalizing desktop startup", CONNECTING never clears. Quarantine the
    # manifest so this launch takes the owned `serve --port 0` path.
    if (Test-Path -LiteralPath $manifestPath) {
        $stamp = Get-Date -Format "yyyyMMddHHmmss"
        $bak = "{0}.bak-forcelocal-{1}" -f $manifestPath, $stamp
        Move-Item -LiteralPath $manifestPath -Destination $bak -Force
        Write-Host "[start-hermes-desktop] ForceLocalSpawn: quarantined desktop-backend.json -> $bak"
    } else {
        Write-Host "[start-hermes-desktop] ForceLocalSpawn: no desktop-backend.json (already clear)"
    }
    Remove-Item Env:HERMES_DESKTOP_REMOTE_URL -ErrorAction SilentlyContinue
    Remove-Item Env:HERMES_DESKTOP_REMOTE_TOKEN -ErrorAction SilentlyContinue
} else {
$waitSeconds = 90
$deadline = (Get-Date).AddSeconds($waitSeconds)
while ((Get-Date) -lt $deadline) {
    if (-not (Test-Path -LiteralPath $manifestPath)) {
        Start-Sleep -Seconds 2
        continue
    }
    try {
        $manifest = Get-Content -LiteralPath $manifestPath -Raw -Encoding utf8 | ConvertFrom-Json
    } catch {
        Start-Sleep -Seconds 2
        continue
    }
    $candidateUrl = [string]$manifest.baseUrl
    $candidateToken = [string]$manifest.token
    if ([string]::IsNullOrWhiteSpace($candidateUrl) -or [string]::IsNullOrWhiteSpace($candidateToken)) {
        Start-Sleep -Seconds 2
        continue
    }
    try {
        $probe = Invoke-WebRequest `
            -Uri ($candidateUrl.TrimEnd('/') + '/api/sessions') `
            -Headers @{
                Authorization = "Bearer $candidateToken"
                'X-Hermes-Session-Token' = $candidateToken
            } `
            -UseBasicParsing `
            -TimeoutSec 3
        if ([int]$probe.StatusCode -ge 200 -and [int]$probe.StatusCode -lt 300) {
            $managedUrl = $candidateUrl.Trim()
            $managedToken = $candidateToken.Trim()
            break
        }
    } catch {
        Start-Sleep -Seconds 2
        continue
    }
}
} # end else !ForceLocalSpawn

# Never leave stale REMOTE_* in the process environment — a previous shell
# session can otherwise force Remote mode even when we want local+prewarm.
Remove-Item Env:HERMES_DESKTOP_REMOTE_URL -ErrorAction SilentlyContinue
Remove-Item Env:HERMES_DESKTOP_REMOTE_TOKEN -ErrorAction SilentlyContinue

$useRemoteFallback = $false
if ($managedUrl -and $managedToken) {
    $isLoopback = $false
    try {
        $uri = [Uri]$managedUrl
        $isLoopback = ($uri.Host -eq '127.0.0.1') -or ($uri.Host -eq 'localhost') -or ($uri.Host -eq '::1')
    } catch {
        $isLoopback = $false
    }
    if ($isLoopback) {
        Write-Host "[start-hermes-desktop] Managed loopback backend ready at $managedUrl — launching local+prewarm (no HERMES_DESKTOP_REMOTE_*)"
    } else {
        $useRemoteFallback = $true
        $env:HERMES_DESKTOP_REMOTE_URL = $managedUrl
        $env:HERMES_DESKTOP_REMOTE_TOKEN = $managedToken
        Write-Host "[start-hermes-desktop] Attaching to non-loopback managed backend $managedUrl via REMOTE env"
    }
} else {
    if ($ForceLocalSpawn) {
        Write-Host "[start-hermes-desktop] ForceLocalSpawn: Desktop will own serve --port 0 (classic local boot)"
    } else {
        Write-Host "[start-hermes-desktop] WARNING: managed backend not ready after ${waitSeconds}s; Desktop may spawn its own serve"
    }
}

Write-Host "[start-hermes-desktop] Launching: $PackagedExe"
Write-Host "[start-hermes-desktop] HERMES_DESKTOP_HERMES_ROOT=$env:HERMES_DESKTOP_HERMES_ROOT"

function Test-IsElevatedDesktopLauncher {
    try {
        $identity = [Security.Principal.WindowsIdentity]::GetCurrent()
        $principal = New-Object Security.Principal.WindowsPrincipal($identity)
        return $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
    } catch {
        return $false
    }
}

function Start-HermesDesktopProcess {
    param(
        [Parameter(Mandatory = $true)][string]$ExePath,
        [Parameter(Mandatory = $true)][string]$WorkDirectory,
        [hashtable]$ExtraEnv = @{},
        [string[]]$RemoveEnv = @()
    )

    # Elevated parents create a BrowserWindow that never gets WS_VISIBLE
    # (HWND exists, title=Hermes, IsWindowVisible=false). Launch Medium IL
    # via a one-shot Interactive Limited scheduled task when elevated.
    if (Test-IsElevatedDesktopLauncher) {
        Write-Host "[start-hermes-desktop] Launcher is elevated — starting Desktop as Medium IL (Limited task)"
        $wrapper = Join-Path $env:TEMP ("hermes-desktop-unelevated-{0}.ps1" -f (Get-Date -Format "yyyyMMddHHmmss"))
        $envLines = New-Object System.Collections.Generic.List[string]
        $envLines.Add('$ErrorActionPreference = "Stop"')
        $envLines.Add(('Set-Location -LiteralPath ''{0}''' -f ($WorkDirectory -replace "'", "''")))
        foreach ($key in $ExtraEnv.Keys) {
            $val = [string]$ExtraEnv[$key]
            $envLines.Add(('$env:{0} = ''{1}''' -f $key, ($val -replace "'", "''")))
        }
        foreach ($key in $RemoveEnv) {
            $envLines.Add(('Remove-Item Env:{0} -ErrorAction SilentlyContinue' -f $key))
        }
        $envLines.Add(('$p = Start-Process -FilePath ''{0}'' -WorkingDirectory ''{1}'' -PassThru' -f ($ExePath -replace "'", "''"), ($WorkDirectory -replace "'", "''")))
        $envLines.Add('if ($null -eq $p) { throw "unelevated Hermes start failed" }')
        $envLines.Add('Write-Output ("started pid={0}" -f $p.Id)')
        $utf8NoBom = New-Object System.Text.UTF8Encoding $false
        [System.IO.File]::WriteAllText($wrapper, (($envLines -join "`r`n") + "`r`n"), $utf8NoBom)

        $taskName = "HermesDesktopUnelevatedOnce"
        Unregister-ScheduledTask -TaskName $taskName -Confirm:$false -ErrorAction SilentlyContinue | Out-Null
        $action = New-ScheduledTaskAction -Execute "powershell.exe" -Argument ("-NoProfile -ExecutionPolicy Bypass -File `"$wrapper`"") -WorkingDirectory $WorkDirectory
        # UserId must be DOMAIN\user (or MACHINE\user) — bare $env:USERNAME is
        # rejected as 0x80070057 InvalidArgument by Register-ScheduledTask.
        $userId = [Security.Principal.WindowsIdentity]::GetCurrent().Name
        $principal = New-ScheduledTaskPrincipal -UserId $userId -LogonType Interactive -RunLevel Limited
        $settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -MultipleInstances IgnoreNew -ExecutionTimeLimit ([TimeSpan]::FromMinutes(5))
        try {
            Register-ScheduledTask -TaskName $taskName -Action $action -Principal $principal -Settings $settings -Force | Out-Null
            Start-ScheduledTask -TaskName $taskName
            Write-Host ("[start-hermes-desktop] Limited task started as {0}" -f $userId)
        } catch {
            Write-Host ("[start-hermes-desktop] Limited task failed ({0}); falling back to runas /trustlevel:0x20000" -f $_.Exception.Message)
            # Medium IL without Task Scheduler. Env is baked into the wrapper already.
            $runasArgs = '/trustlevel:0x20000 "powershell.exe -NoProfile -ExecutionPolicy Bypass -File \"{0}\""' -f $wrapper
            Start-Process -FilePath "$env:SystemRoot\System32\runas.exe" -ArgumentList $runasArgs -Wait:$false | Out-Null
        }
        Start-Sleep -Seconds 4
        $info = Get-ScheduledTaskInfo -TaskName $taskName -ErrorAction SilentlyContinue
        if ($null -ne $info -and $info.LastTaskResult -ne 0 -and $info.LastTaskResult -ne 267009) {
            # 267009 = still running; other codes may be transient during start.
            Write-Host ("[start-hermes-desktop] Limited task lastResult={0}" -f $info.LastTaskResult)
        }
        $deadline = (Get-Date).AddSeconds(20)
        $main = $null
        while ((Get-Date) -lt $deadline -and $null -eq $main) {
            $main = @(Get-CimInstance Win32_Process -ErrorAction SilentlyContinue | Where-Object {
                $_.CommandLine -and $_.CommandLine -match ([regex]::Escape($ExePath)) -and $_.CommandLine -notmatch '(?i)\s--type='
            } | Select-Object -First 1)
            if ($null -eq $main -or $main.Count -eq 0) {
                $main = $null
                Start-Sleep -Seconds 1
            }
        }
        if ($null -eq $main) {
            throw "Elevated launcher failed to start a Medium-IL Hermes.exe (task/runas)"
        }
        return Get-Process -Id ([int]$main.ProcessId) -ErrorAction Stop
    }

    # Force CreateProcess with an explicit environment block so HERMES_HOME /
    # HERMES_DESKTOP_HERMES_ROOT are never dropped by UseShellExecute.
    $psi = New-Object System.Diagnostics.ProcessStartInfo
    $psi.FileName = $ExePath
    $psi.WorkingDirectory = $WorkDirectory
    $psi.UseShellExecute = $false
    $psi.CreateNoWindow = $false
    foreach ($entry in [System.Environment]::GetEnvironmentVariables([System.EnvironmentVariableTarget]::Process).GetEnumerator()) {
        try {
            $psi.EnvironmentVariables[$entry.Key] = [string]$entry.Value
        } catch {
            # Some process-only keys are read-only on ProcessStartInfo; skip.
        }
    }
    foreach ($key in $RemoveEnv) {
        $psi.EnvironmentVariables.Remove($key) | Out-Null
    }
    foreach ($key in $ExtraEnv.Keys) {
        $psi.EnvironmentVariables[$key] = [string]$ExtraEnv[$key]
    }
    $proc = [System.Diagnostics.Process]::Start($psi)
    if ($null -eq $proc) {
        throw "Failed to start Hermes Desktop: $ExePath"
    }
    return $proc
}

$launchExtra = @{
    HERMES_DESKTOP_HERMES_ROOT = [string]$env:HERMES_DESKTOP_HERMES_ROOT
    HERMES_DESKTOP_CWD = [string]$env:HERMES_DESKTOP_CWD
    HERMES_HOME = [string]$env:HERMES_HOME
}
if ($env:HERMES_DESKTOP_DASHBOARD_WEB_DIST) {
    $launchExtra['HERMES_DESKTOP_DASHBOARD_WEB_DIST'] = [string]$env:HERMES_DESKTOP_DASHBOARD_WEB_DIST
}
$launchRemove = @()
if ($useRemoteFallback) {
    $launchExtra['HERMES_DESKTOP_REMOTE_URL'] = $managedUrl
    $launchExtra['HERMES_DESKTOP_REMOTE_TOKEN'] = $managedToken
} else {
    $launchRemove = @('HERMES_DESKTOP_REMOTE_URL', 'HERMES_DESKTOP_REMOTE_TOKEN')
}

$launched = Start-HermesDesktopProcess -ExePath $PackagedExe -WorkDirectory $WorkDir -ExtraEnv $launchExtra -RemoveEnv $launchRemove
Write-Host "[start-hermes-desktop] started pid=$($launched.Id)"

# Soft verify: if Desktop still spawns an ephemeral serve despite a ready
# managed loopback backend, fall back once to REMOTE attach.
$verifyDeadline = (Get-Date).AddSeconds(40)
$ownedDuringVerify = $false
while ((Get-Date) -lt $verifyDeadline) {
    Start-Sleep -Seconds 5
    if ($launched.HasExited) {
        Write-Host "[start-hermes-desktop] WARNING: Hermes.exe exited during attach verify (code=$($launched.ExitCode))"
        break
    }
    $owned = $false
    $ephemeral = @(Get-CimInstance Win32_Process -ErrorAction SilentlyContinue | Where-Object {
        $_.CommandLine -and $_.CommandLine -match 'serve --host 127\.0\.0\.1 --port 0'
    })
    foreach ($svc in $ephemeral) {
        if ([int]$svc.ParentProcessId -eq [int]$launched.Id) {
            $owned = $true
            break
        }
        $parentProc = Get-CimInstance Win32_Process -Filter "ProcessId=$($svc.ParentProcessId)" -ErrorAction SilentlyContinue
        if ($null -ne $parentProc -and [int]$parentProc.ParentProcessId -eq [int]$launched.Id) {
            $owned = $true
            break
        }
    }
    if ($owned) {
        $ownedDuringVerify = $true
        break
    }
}

if ($ownedDuringVerify -and $managedUrl -and $managedToken -and -not $useRemoteFallback) {
    Write-Host "[start-hermes-desktop] prewarm path spawned port-0 — retrying once with REMOTE attach to $managedUrl"
    try { Stop-Process -Id $launched.Id -Force -ErrorAction SilentlyContinue } catch {}
    foreach ($svc in @(Get-CimInstance Win32_Process -ErrorAction SilentlyContinue | Where-Object {
        $_.CommandLine -and $_.CommandLine -match 'serve --host 127\.0\.0\.1 --port 0'
    })) {
        Stop-Process -Id $svc.ProcessId -Force -ErrorAction SilentlyContinue
    }
    Start-Sleep -Seconds 2
    $retryExtra = @{
        HERMES_DESKTOP_REMOTE_URL = $managedUrl
        HERMES_DESKTOP_REMOTE_TOKEN = $managedToken
        HERMES_DESKTOP_HERMES_ROOT = [string]$env:HERMES_DESKTOP_HERMES_ROOT
        HERMES_DESKTOP_CWD = [string]$env:HERMES_DESKTOP_CWD
        HERMES_HOME = [string]$env:HERMES_HOME
    }
    if ($env:HERMES_DESKTOP_DASHBOARD_WEB_DIST) {
        $retryExtra['HERMES_DESKTOP_DASHBOARD_WEB_DIST'] = [string]$env:HERMES_DESKTOP_DASHBOARD_WEB_DIST
    }
    $launched = Start-HermesDesktopProcess -ExePath $PackagedExe -WorkDirectory $WorkDir -ExtraEnv $retryExtra -RemoveEnv @()
    if ($null -eq $launched) {
        throw "Failed to start Hermes Desktop on REMOTE fallback: $PackagedExe"
    }
    Write-Host "[start-hermes-desktop] REMOTE fallback started pid=$($launched.Id)"
} elseif ($ownedDuringVerify) {
    Write-Host "[start-hermes-desktop] ERROR: Desktop spawned ephemeral port-0 serve — dual-backend latch. Killing and failing closed."
    try { Stop-Process -Id $launched.Id -Force -ErrorAction SilentlyContinue } catch {}
    foreach ($svc in @(Get-CimInstance Win32_Process -ErrorAction SilentlyContinue | Where-Object {
        $_.CommandLine -and $_.CommandLine -match 'serve --host 127\.0\.0\.1 --port 0'
    })) {
        Stop-Process -Id $svc.ProcessId -Force -ErrorAction SilentlyContinue
    }
    exit 2
} else {
    Write-Host "[start-hermes-desktop] attach verify: no Desktop-owned port-0 serve within 40s"
}

exit 0
