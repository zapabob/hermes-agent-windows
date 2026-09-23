"""Strict policy for the existing Docker backend, without ambient host capabilities.

Inference stays in Hermes. This environment only executes credential-free work.
It deliberately does not call the ordinary Docker constructor: that constructor
supports operator-approved credentials, mounts, egress proxies and reuse.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import re
import subprocess
import tempfile
import threading
import uuid

from hermes_cli._subprocess_compat import windows_hide_flags
from tools.environments.base import BaseEnvironment, _popen_bash
from tools.environments.credential_free import child_environment
from tools.environments.docker import DockerEnvironment

_IMAGE = re.compile(r"(?:sha256:[a-f0-9]{64}|[A-Za-z0-9][A-Za-z0-9._/:\-]*@sha256:[a-f0-9]{64})\Z")
_CONTAINER = re.compile(r"[a-f0-9]{64}\Z")
_CLEAN_ENV = (
    "PATH=/usr/local/bin:/usr/bin:/bin", "HOME=/home/runner",
    "LANG=C.UTF-8", "PYTHONUTF8=1", "PYTHONDONTWRITEBYTECODE=1", "PYTHONNOUSERSITE=1",
    "GIT_CONFIG_NOSYSTEM=1", "GIT_CONFIG_GLOBAL=/dev/null",
    "GIT_TERMINAL_PROMPT=0", "HERMES_HOME=/home/runner/hermes",
    "CODEX_HOME=/home/runner/codex", "AWS_SHARED_CREDENTIALS_FILE=/dev/null",
    "AWS_CONFIG_FILE=/dev/null", "CLOUDSDK_CONFIG=/home/runner/gcloud",
)
_TMPFS = frozenset({"/workspace", "/tmp", "/root", "/home"})


class CredentialFreeDockerEnvironment(DockerEnvironment):
    """A measured, non-reusable native environment with no host authentication."""

    _profile_scoped_passthrough = False
    credential_free = True

    def __init__(self, *, image: str, task_id: str, timeout: int = 60):
        if not isinstance(image, str) or not _IMAGE.fullmatch(image):
            raise ValueError("A locally prepared image pinned by digest is required")
        if not isinstance(task_id, str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,128}", task_id):
            raise ValueError("Invalid isolated task identity")
        if type(timeout) is not int or not 1 <= timeout <= 3600:
            raise ValueError("Invalid execution timeout")
        from tools.environments.docker import find_docker

        executable = find_docker()
        if not executable or not Path(executable).is_absolute():
            raise RuntimeError("Credential-free execution requires the native Docker CLI")
        BaseEnvironment.__init__(self, cwd="/workspace", timeout=timeout)
        self._docker_exe = executable
        self._image = image
        self._task_id = task_id
        self._container_id = None
        self._container_name = "hermes-engineering-" + uuid.uuid4().hex
        self._persistent = False
        self._persist_across_processes = False
        self._session_scoped = False
        self._workspace_dir = None
        self._home_dir = None
        self._forward_env = []
        self._env = {}
        self._init_unset_passthrough_names = ()
        self._serial = threading.RLock()
        self._runtime = tempfile.TemporaryDirectory(prefix="hermes-credential-free-")
        root = Path(self._runtime.name)
        system_root = Path(os.environ["SystemRoot"]) if os.name == "nt" else None
        self._driver_env = child_environment(root, (Path(executable).parent,), system_root=system_root)
        for name in ("home", "config", "data", "temp"):
            (root / name).mkdir()
        try:
            engine = self._driver("info", "--format", "{{.OSType}}")
            if engine.stdout.strip() != "linux":
                raise RuntimeError("Credential-free isolation requires a Linux Docker engine")
            args = [
                "run", "--detach", "--pull=never", "--name", self._container_name,
                "--label", "hermes-agent=1", "--label", "hermes-credential-free=1",
                "--network=none", "--ipc=private", "--read-only", "--user=65534:65534",
                "--cap-drop=ALL", "--security-opt=no-new-privileges",
                "--pids-limit=128", "--memory=5120m", "--memory-swap=5120m", "--cpus=2",
            ]
            for destination in sorted(_TMPFS):
                args += ["--tmpfs", f"{destination}:rw,exec,nosuid,nodev,mode=1777,size=1g"]
            args += ["--entrypoint", "/usr/bin/env", image, "-i", *_CLEAN_ENV, "/bin/sleep", "infinity"]
            created = self._driver(*args)
            identity = created.stdout.strip()
            if not _CONTAINER.fullmatch(identity):
                raise RuntimeError("Docker did not return a conclusive container identity")
            self._container_id = identity
            self.assert_credential_free()
            self._idle_processes = self._process_ids()
            if len(self._idle_processes) != 1:
                raise RuntimeError("Unexpected initial isolated process tree")
        except BaseException:
            # A failed run may still have been accepted by the daemon. Remove by
            # our unique name; never retry creation or attach to another run.
            self._driver("rm", "--force", "--volumes", self._container_name, check=False)
            self._runtime.cleanup()
            raise

    def _driver(self, *args: str, check: bool = True):
        result = subprocess.run(
            [self._docker_exe, *args], env=dict(self._driver_env),
            close_fds=True, stdin=subprocess.DEVNULL, capture_output=True,
            text=True, encoding="utf-8", errors="replace", timeout=30,
            creationflags=windows_hide_flags(),
        )
        if check and result.returncode != 0:
            # Driver output can contain machine-local configuration. Keep it
            # out of model responses and exception-based handoffs.
            raise RuntimeError("Native isolated Docker operation failed")
        return result

    def assert_credential_free(self) -> None:
        if not self._container_id:
            raise RuntimeError("Native isolation is no longer active")
        try:
            values = json.loads(self._driver("inspect", self._container_id).stdout)
            if type(values) is not list or len(values) != 1:
                raise ValueError("invalid inspection")
            value = values[0]
            host, config = value["HostConfig"], value["Config"]
            valid = (
                value["Id"] == self._container_id
                and value["State"].get("Running") is True
                and config.get("Image") == self._image
                and config.get("User") == "65534:65534"
                and config.get("Labels", {}).get("hermes-credential-free") == "1"
                and host.get("NetworkMode") == "none"
                and set(value["NetworkSettings"]["Networks"]) == {"none"}
                and host.get("PidMode") in ("", "private")
                and host.get("IpcMode") == "private"
                and host.get("Privileged") is False
                and host.get("ReadonlyRootfs") is True
                and not host.get("CapAdd") and "ALL" in host.get("CapDrop", [])
                and any(item in ("no-new-privileges", "no-new-privileges:true") for item in host.get("SecurityOpt", []))
                and not host.get("Binds") and not host.get("Devices") and not host.get("DeviceRequests")
                and set(host.get("Tmpfs", {})) == _TMPFS
                and all(item.get("Type") == "tmpfs" and item.get("Destination") in _TMPFS for item in value["Mounts"])
            )
            if not valid:
                raise ValueError("isolation drift")
        except (KeyError, TypeError, ValueError) as exc:
            raise RuntimeError("Native credential-free isolation could not be established") from exc

    def _process_ids(self) -> frozenset[str]:
        lines = self._driver("top", self._container_id, "-eo", "pid").stdout.splitlines()
        if not lines or lines[0].strip() != "PID":
            raise RuntimeError("Cannot establish isolated writer state")
        values = frozenset(line.strip() for line in lines[1:] if line.strip())
        if not values or any(not value.isdigit() for value in values):
            raise RuntimeError("Cannot establish isolated writer state")
        return values

    def assert_quiescent(self) -> None:
        self.assert_credential_free()
        if self._process_ids() != self._idle_processes:
            raise RuntimeError("An isolated writer may still be active")

    def _prepare_command(self, command):
        # Never borrow the parent operator's sudo password for an isolated actor.
        return command, None

    def _resolve_passthrough_env(self):
        return {}, set()

    def _run_bash(self, cmd_string, *, login=False, timeout=120, stdin_data=None):
        if not self._container_id:
            raise RuntimeError("Isolated environment was closed; it cannot be replayed")
        args = [self._docker_exe, "exec"]
        if stdin_data is not None:
            args.append("-i")
        args += ["--workdir", "/workspace", self._container_id, "/usr/bin/env", "-i",
                 *_CLEAN_ENV, "/bin/bash", "--noprofile", "--norc", "-c", cmd_string]
        return _popen_bash(args, stdin_data, env=dict(self._driver_env), close_fds=True)

    def execute(self, command, cwd="", **kwargs):
        with self._serial:
            self.assert_credential_free()
            result = BaseEnvironment.execute(self, command, cwd, **kwargs)
            if result.get("returncode") in (124, 130, 137):
                self.cleanup()
            return result

    def execute_clean(self, argv: tuple[str, ...], *, stdin: str | None = None,
                      timeout: int = 120, root: bool = False) -> dict:
        """Run a host-owned argv without the model's mutable shell snapshot.

        ``root`` is only for importing files/protecting acceptance probes in
        tmpfs. No model-facing tool exposes this parameter or this method.
        """
        if not argv or any(not isinstance(arg, str) or "\0" in arg for arg in argv):
            raise ValueError("Invalid host-owned command")
        with self._serial:
            self.assert_credential_free()
            command = [self._docker_exe, "exec"]
            if stdin is not None:
                command.append("-i")
            if root:
                command += ["--user", "0:0"]
            command += ["--workdir", "/workspace", self._container_id, "/usr/bin/env", "-i", *_CLEAN_ENV, *argv]
            process = _popen_bash(command, stdin, env=dict(self._driver_env), close_fds=True)
            result = self._wait_for_process(process, timeout=timeout, bounded_capture=True)
            if result.get("returncode") in (124, 130, 137):
                self.cleanup()
            return result

    def cleanup(self, *, force_remove=False):
        with self._serial:
            if self._container_id:
                self._driver("rm", "--force", "--volumes", self._container_id)
                self._container_id = None
            self._runtime.cleanup()

    def wait_for_cleanup(self, timeout=30.0):
        return self._container_id is None
