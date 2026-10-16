"""Windows installer regression coverage for Git long-path checkouts."""

from __future__ import annotations

import os
from pathlib import Path
import re
import shutil
import subprocess
import sys

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
INSTALL_PS1 = REPO_ROOT / "scripts" / "install.ps1"
POWERSHELL = shutil.which("powershell") or shutil.which("pwsh")
GIT = shutil.which("git")


def _install_repository_source() -> str:
    text = INSTALL_PS1.read_text(encoding="utf-8")
    match = re.search(
        r"(?ms)^function Install-Repository \{.*?(?=^function Install-Venv \{)",
        text,
    )
    assert match is not None, "Install-Repository function not found"
    return match.group(0)


def _git(cwd: Path, *args: str, env: dict[str, str]) -> None:
    result = subprocess.run(
        [GIT, *args],
        cwd=cwd,
        env=env,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )
    assert result.returncode == 0, (
        f"git {' '.join(args)} failed in {cwd}:\n{result.stdout}\n{result.stderr}"
    )


def _git_env(tmp_path: Path) -> dict[str, str]:
    env = os.environ.copy()
    global_config = tmp_path / "empty-gitconfig"
    global_config.write_text("", encoding="utf-8")
    env.update(
        {
            "GIT_CONFIG_GLOBAL": str(global_config),
            "GIT_CONFIG_NOSYSTEM": "1",
            "GIT_TERMINAL_PROMPT": "0",
        }
    )
    return env


def _deep_file() -> Path:
    parts = [f"dir-{index:02d}-" + "x" * 12 for index in range(12)]
    return Path(*parts, "deep-file.txt")


def _make_origin(
    tmp_path: Path,
    env: dict[str, str],
    *,
    include_deep_file: bool = True,
) -> tuple[Path, Path, Path]:
    source = tmp_path / "source"
    source.mkdir()
    origin = tmp_path / "origin.git"
    deep_file = _deep_file()

    _git(tmp_path, "init", "--bare", "--initial-branch=main", str(origin), env=env)
    _git(source.parent, "init", "--initial-branch=main", str(source), env=env)
    _git(source, "config", "--local", "core.longpaths", "true", env=env)
    _git(source, "config", "--local", "user.name", "Hermes test", env=env)
    _git(source, "config", "--local", "user.email", "hermes-test@example.invalid", env=env)
    (source / "README.md").write_text("initial version\n", encoding="utf-8")
    if include_deep_file:
        deep_path = source / deep_file
        deep_path.parent.mkdir(parents=True, exist_ok=True)
        deep_path.write_text("first version\n", encoding="utf-8")
    _git(source, "add", "--all", env=env)
    _git(source, "commit", "-m", "initial", env=env)
    _git(source, "remote", "add", "origin", str(origin), env=env)
    _git(source, "push", "origin", "main", env=env)
    return source, origin, deep_file


def _ps_quote(value: str | Path) -> str:
    return "'" + str(value).replace("'", "''") + "'"


def _run_install_repository(
    tmp_path: Path,
    *,
    origin: Path,
    install_dir: Path,
    env: dict[str, str],
) -> list[str]:
    assert POWERSHELL is not None
    function_source = _install_repository_source()
    git_log = tmp_path / "installer-git-commands.log"
    harness = tmp_path / "run-install-repository.ps1"
    harness.write_text(
        "\n".join(
            [
                "$ErrorActionPreference = 'Stop'",
                f"$InstallDir = {_ps_quote(install_dir)}",
                "$Branch = 'main'",
                f"$RepoUrlSsh = {_ps_quote(origin)}",
                f"$RepoUrlHttps = {_ps_quote(origin)}",
                "$RepoArchiveBase = 'https://example.invalid/archive'",
                "$Commit = $null",
                "$Tag = $null",
                "$ForceCommit = $false",
                "$script:RealGit = (Get-Command git.exe -ErrorAction Stop).Source",
                "function git {",
                "  Add-Content -LiteralPath $env:HERMES_TEST_GIT_LOG -Value ($args -join ' ')",
                "  if ($args -contains '--global') { $global:LASTEXITCODE = 0; return }",
                "  & $script:RealGit @args",
                "}",
                "function Write-Info { param([Parameter(ValueFromRemainingArguments=$true)][object[]]$Message) }",
                "function Write-Warn { param([Parameter(ValueFromRemainingArguments=$true)][object[]]$Message) }",
                "function Write-Success { param([Parameter(ValueFromRemainingArguments=$true)][object[]]$Message) }",
                "function Write-Err { param([Parameter(ValueFromRemainingArguments=$true)][object[]]$Message) }",
                "function Discard-LockfileChurn { param([string]$Path) }",
                "function Invoke-NativeWithRelaxedErrorAction {",
                "  param([scriptblock]$Command)",
                "  $previous = $ErrorActionPreference",
                "  try { $ErrorActionPreference = 'Continue'; & $Command }",
                "  finally { $ErrorActionPreference = $previous }",
                "}",
                "function Invoke-WebRequest { throw 'Network access is disabled in this test harness' }",
                function_source,
                "try { Install-Repository; exit 0 }",
                "catch { Write-Error $_; exit 1 }",
            ]
        ),
        encoding="utf-8",
    )
    child_env = env.copy()
    child_env["HERMES_TEST_GIT_LOG"] = str(git_log)
    result = subprocess.run(
        [POWERSHELL, "-NoLogo", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-File", str(harness)],
        cwd=REPO_ROOT,
        env=child_env,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=120,
        check=False,
    )
    assert result.returncode == 0, (
        f"Install-Repository harness failed ({result.returncode}):\n"
        f"stdout:\n{result.stdout}\nstderr:\n{result.stderr}"
    )
    return git_log.read_text(encoding="utf-8").splitlines()


@pytest.mark.skipif(sys.platform != "win32", reason="requires native Windows PowerShell")
def test_fresh_clone_persists_longpaths_and_checks_out_deep_file(tmp_path: Path) -> None:
    if GIT is None or POWERSHELL is None:
        pytest.skip("requires Git and PowerShell")
    env = _git_env(tmp_path)
    _, origin, deep_file = _make_origin(tmp_path, env)
    install_dir = tmp_path / "fresh-install"

    commands = _run_install_repository(
        tmp_path, origin=origin, install_dir=install_dir, env=env
    )

    assert (install_dir / deep_file).read_text(encoding="utf-8") == "first version\n"
    assert subprocess.run(
        [GIT, "config", "--local", "--get", "core.longpaths"],
        cwd=install_dir,
        env=env,
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=True,
    ).stdout.strip().lower() == "true"
    clone = next(command for command in commands if " clone " in f" {command} ")
    assert "--config core.longpaths=true" in clone


@pytest.mark.skipif(sys.platform != "win32", reason="requires native Windows PowerShell")
def test_existing_checkout_sets_longpaths_before_fetch_and_checkout(tmp_path: Path) -> None:
    if GIT is None or POWERSHELL is None:
        pytest.skip("requires Git and PowerShell")
    env = _git_env(tmp_path)
    source, origin, deep_file = _make_origin(tmp_path, env, include_deep_file=False)
    install_dir = tmp_path / "existing-install"
    _git(
        tmp_path,
        "clone",
        "--config",
        "core.longpaths=true",
        "--branch",
        "main",
        str(origin),
        str(install_dir),
        env=env,
    )
    _git(install_dir, "config", "--local", "--unset", "core.longpaths", env=env)

    deep_path = source / deep_file
    deep_path.parent.mkdir(parents=True, exist_ok=True)
    deep_path.write_text("updated version\n", encoding="utf-8")
    _git(source, "add", "--all", env=env)
    _git(source, "commit", "-m", "update deep file", env=env)
    _git(source, "push", "origin", "main", env=env)

    commands = _run_install_repository(
        tmp_path, origin=origin, install_dir=install_dir, env=env
    )

    assert (install_dir / deep_file).read_text(encoding="utf-8") == "updated version\n"
    longpaths_at = next(
        index
        for index, command in enumerate(commands)
        if "config core.longpaths true" in command
    )
    fetch_at = next(
        index for index, command in enumerate(commands) if "fetch origin main" in command
    )
    checkout_at = next(
        index for index, command in enumerate(commands) if "checkout main" in command
    )
    assert longpaths_at < fetch_at < checkout_at
    assert subprocess.run(
        [GIT, "config", "--local", "--get", "core.longpaths"],
        cwd=install_dir,
        env=env,
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=True,
    ).stdout.strip().lower() == "true"


def test_all_installer_clone_paths_enable_longpaths_before_checkout() -> None:
    source = _install_repository_source()
    clone_calls = re.findall(r"git -c windows\.appendAtomically=false clone[^\r\n]+", source)
    assert len(clone_calls) == 2, "both SSH and HTTPS clone fallbacks must be covered"
    assert all("clone --config core.longpaths=true" in call for call in clone_calls)

    init_at = source.index("git -c windows.appendAtomically=false init 2>$null")
    zip_longpaths_at = source.index(
        "git -c windows.appendAtomically=false config core.longpaths true", init_at
    )
    zip_fetch_at = source.index(
        "git -c windows.appendAtomically=false fetch --depth 1 origin", init_at
    )
    assert init_at < zip_longpaths_at < zip_fetch_at
