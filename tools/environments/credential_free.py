"""Construct credential-free launcher environments; not an OS sandbox by itself."""
from __future__ import annotations

import os
from pathlib import Path

def _directory(value: Path) -> Path:
    if not isinstance(value, Path) or not value.is_absolute() or not value.is_dir():
        raise ValueError("approved_absolute_directory_required")
    return value.resolve(strict=True)


def child_environment(
    sandbox_root: Path, executable_directories: tuple[Path, ...],
    *, system_root: Path | None = None,
) -> dict[str, str]:
    """Build, never copy, a process environment using host-approved paths.

    The host owns the fresh sandbox and launcher. It must use close_fds=True,
    no pass_fds/handle-list, no credential-bearing stdin/argv, and no inherited
    host authentication mount or broker connection. Python probes use -I.
    A child naturally passes this already-clean environment to a grandchild.

    Empty HOME/config paths prevent default credential-store discovery; they
    are NOT an OS filesystem/memory sandbox. Do not infer sandbox isolation
    from this helper or issue an admission on its strength alone.
    """
    root = _directory(sandbox_root)
    if any(root.iterdir()):
        raise ValueError("fresh_empty_runtime_root_required")
    if type(executable_directories) is not tuple or not executable_directories:
        raise ValueError("approved_runtime_paths_required")
    bins = tuple(_directory(path) for path in executable_directories)
    if any(os.pathsep in str(path) for path in bins):
        raise ValueError("ambiguous_runtime_search_path")
    env = {
        "PATH": os.pathsep.join(str(path) for path in bins),
        "HOME": str(root / "home"), "USERPROFILE": str(root / "home"),
        "APPDATA": str(root / "config"), "LOCALAPPDATA": str(root / "data"),
        "XDG_CONFIG_HOME": str(root / "config"),
        "XDG_CACHE_HOME": str(root / "cache"), "XDG_DATA_HOME": str(root / "data"),
        "TEMP": str(root / "temp"), "TMP": str(root / "temp"), "TMPDIR": str(root / "temp"),
        "HERMES_HOME": str(root / "hermes"), "CODEX_HOME": str(root / "codex"),
        "CLOUDSDK_CONFIG": str(root / "config" / "gcloud"),
        "AZURE_CONFIG_DIR": str(root / "config" / "azure"),
        "AWS_CONFIG_FILE": str(root / "config" / "aws-config"),
        "AWS_SHARED_CREDENTIALS_FILE": str(root / "config" / "aws-credentials"),
        "DOCKER_CONFIG": str(root / "config" / "docker"),
        "GIT_CONFIG_NOSYSTEM": "1", "GIT_CONFIG_SYSTEM": os.devnull,
        "GIT_CONFIG_GLOBAL": str(root / "config" / "git-config"),
        "GIT_TERMINAL_PROMPT": "0", "PYTHONNOUSERSITE": "1", "PYTHONUTF8": "1",
    }
    if os.name == "nt":
        if system_root is None:
            raise ValueError("approved_windows_system_root_required")
        windows = _directory(system_root)
        env["SystemRoot"] = str(windows)
        env["WINDIR"] = str(windows)
        env["COMSPEC"] = str(windows / "System32" / "cmd.exe")
    return env
