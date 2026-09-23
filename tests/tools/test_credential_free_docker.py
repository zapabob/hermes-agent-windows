"""Native Docker policy tests; actual isolation is exercised by a separate E2E gate."""
from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace

import pytest

from tools.environments.docker import DockerEnvironment

IMAGE = "sha256:" + "b" * 64
CONTAINER = "a" * 64


def observed():
    return [{
        "Id": CONTAINER, "Image": IMAGE, "State": {"Running": True},
        "Config": {"Image": IMAGE, "User": "65534:65534", "Labels": {"hermes-credential-free": "1"}},
        "HostConfig": {"NetworkMode": "none", "PidMode": "", "IpcMode": "private",
            "Privileged": False, "ReadonlyRootfs": True, "CapAdd": None, "CapDrop": ["ALL"],
            "SecurityOpt": ["no-new-privileges"], "Binds": None, "Devices": [], "DeviceRequests": None,
            "Tmpfs": {"/workspace": "rw", "/tmp": "rw", "/root": "rw", "/home": "rw"}},
        "Mounts": [], "NetworkSettings": {"Networks": {"none": {}}},
    }]


@pytest.fixture
def driver(monkeypatch, tmp_path):
    import subprocess
    from tools.environments import docker
    calls = []
    state = observed()
    exe = tmp_path / "docker"
    exe.write_text("inert test driver")
    monkeypatch.setattr(docker, "find_docker", lambda: str(exe))
    monkeypatch.setenv("ODDLY_NAMED_PARENT_CREDENTIAL", "synthetic-secret")
    monkeypatch.setenv("DOCKER_AUTH_CONFIG", "synthetic-docker-token")

    def run(argv, **kwargs):
        calls.append((argv, kwargs))
        assert kwargs.get("close_fds") is True
        assert type(kwargs.get("env")) is dict
        assert "synthetic-secret" not in repr(kwargs)
        assert "synthetic-docker-token" not in repr(kwargs)
        if "info" in argv:
            output = "linux\n"
        elif "inspect" in argv:
            output = json.dumps(state)
        elif "top" in argv:
            output = "PID\n1234\n"
        elif "run" in argv:
            output = CONTAINER + "\n"
        else:
            output = ""
        return SimpleNamespace(stdout=output, stderr="", returncode=0)
    monkeypatch.setattr(subprocess, "run", run)
    return calls, state


def make_environment():
    factory = getattr(DockerEnvironment, "credential_free", None)
    assert callable(factory), "native credential-free factory is missing"
    return factory(image=IMAGE, task_id="engineering-test")


def test_native_factory_has_no_host_mount_proxy_or_ambient_environment(driver, monkeypatch):
    from tools import credential_files
    monkeypatch.setattr(credential_files, "get_credential_file_mounts", lambda: pytest.fail("must not inspect auth mounts"))
    env = make_environment()
    calls, _ = driver
    argv = next(argv for argv, _ in calls if "run" in argv)
    assert "--network=none" in argv
    assert "--read-only" in argv
    assert "--cap-drop=ALL" in argv
    assert "--security-opt=no-new-privileges" in argv
    assert "--pull=never" in argv
    assert not any(arg in {"-v", "--volume", "--mount", "--privileged", "-e"} for arg in argv)
    env.assert_credential_free()
    env.cleanup()
    assert env.wait_for_cleanup() is True


@pytest.mark.parametrize("mutate", [
    lambda s: s[0]["HostConfig"].update(NetworkMode="host"),
    lambda s: s[0]["NetworkSettings"]["Networks"].update(bridge={}),
    lambda s: s[0]["HostConfig"].update(Privileged=True),
    lambda s: s[0]["HostConfig"].update(ReadonlyRootfs=False),
    lambda s: s[0]["HostConfig"].update(CapAdd=["SYS_ADMIN"]),
    lambda s: s[0]["HostConfig"].update(PidMode="host"),
    lambda s: s[0]["HostConfig"].update(Binds=["/home:/home"]),
    lambda s: s[0]["Mounts"].append({"Type": "volume", "Destination": "/auth"}),
    lambda s: s[0]["Config"].update(User="root"),
    lambda s: s[0]["State"].update(Running=False),
])
def test_actual_isolation_drift_is_rejected_and_never_recreated(driver, mutate):
    env = make_environment()
    calls, state = driver
    mutate(state)
    with pytest.raises(RuntimeError, match="isolation"):
        env.assert_credential_free()
    assert sum("run" in argv for argv, _ in calls) == 1
    env.cleanup()


def test_unpinned_image_is_rejected_before_any_process(driver):
    factory = getattr(DockerEnvironment, "credential_free", None)
    assert callable(factory), "native credential-free factory is missing"
    with pytest.raises(ValueError, match="digest"):
        factory(image="python:latest", task_id="engineering-test")
    assert driver[0] == []


def test_extra_writer_is_not_conclusive_stage_completion(driver, monkeypatch):
    import subprocess
    env = make_environment()
    original = subprocess.run
    def with_writer(argv, **kwargs):
        if "top" in argv:
            return SimpleNamespace(stdout="PID\n1234\n5678\n", stderr="", returncode=0)
        return original(argv, **kwargs)
    monkeypatch.setattr(subprocess, "run", with_writer)
    with pytest.raises(RuntimeError, match="writer"):
        env.assert_quiescent()
    env.cleanup()


def test_parent_sudo_password_never_enters_isolated_stdin(driver, monkeypatch):
    monkeypatch.setenv("SUDO_PASSWORD", "synthetic-sudo-secret")
    env = make_environment()
    try:
        assert env._prepare_command("sudo echo hi") == ("sudo echo hi", None)
    finally:
        env.cleanup()
