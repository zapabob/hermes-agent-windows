"""Minimal environment for implementation-router CI subprocesses."""
from __future__ import annotations

from contextlib import contextmanager
import os
from pathlib import Path
import shutil
import sys
import tempfile
from typing import Iterator


@contextmanager
def isolated_subprocess_env() -> Iterator[dict[str, str]]:
    """Keep host credentials and user configuration out of test descendants."""
    with tempfile.TemporaryDirectory(prefix="hermes-router-child-") as temporary:
        root = Path(temporary)
        git = shutil.which("git")
        executables = [Path(sys.executable).resolve().parent]
        if git:
            executables.append(Path(git).resolve().parent)
        if os.name == "nt":
            executables.append(Path(os.environ["SystemRoot"]) / "System32")
        else:
            executables.extend((Path("/usr/bin"), Path("/bin")))
        env = {
            "PATH": os.pathsep.join(str(path) for path in executables),
            "HOME": str(root),
            "USERPROFILE": str(root),
            "APPDATA": str(root / "config"),
            "LOCALAPPDATA": str(root / "data"),
            "XDG_CONFIG_HOME": str(root / "config"),
            "XDG_CACHE_HOME": str(root / "cache"),
            "XDG_DATA_HOME": str(root / "data"),
            "TEMP": str(root / "temp"),
            "TMP": str(root / "temp"),
            "TMPDIR": str(root / "temp"),
            "HERMES_HOME": str(root / "hermes"),
            "CODEX_HOME": str(root / "codex"),
            "DOCKER_CONFIG": str(root / "config" / "docker"),
            "CLOUDSDK_CONFIG": str(root / "config" / "gcloud"),
            "AZURE_CONFIG_DIR": str(root / "config" / "azure"),
            "AWS_CONFIG_FILE": str(root / "config" / "aws-config"),
            "AWS_SHARED_CREDENTIALS_FILE": str(root / "config" / "aws-credentials"),
            "GIT_CONFIG_NOSYSTEM": "1",
            "GIT_CONFIG_SYSTEM": os.devnull,
            "GIT_CONFIG_GLOBAL": str(root / "config" / "git-config"),
            "GIT_TERMINAL_PROMPT": "0",
            "PYTHONNOUSERSITE": "1",
            "PYTHONUTF8": "1",
        }
        for directory in ("config", "data", "cache", "temp", "hermes", "codex"):
            (root / directory).mkdir()
        if os.name == "nt":
            system_root = os.environ["SystemRoot"]
            env.update({
                "SystemRoot": system_root,
                "WINDIR": system_root,
                "COMSPEC": str(Path(system_root) / "System32" / "cmd.exe"),
                "PATHEXT": os.environ.get("PATHEXT", ".COM;.EXE;.BAT;.CMD"),
            })
        yield env
