"""One host-owned sandbox binding, shared by native terminal and file tools."""
from __future__ import annotations

from unittest.mock import Mock

import pytest

from tools import terminal_tool as terminal
from tools.environments.docker_isolation import CredentialFreeDockerEnvironment


@pytest.fixture
def env():
    # Inert native boundary object: real-container evidence belongs to E2E.
    instance = object.__new__(CredentialFreeDockerEnvironment)
    instance.cwd = "/workspace"
    instance.timeout = 60
    instance._image = "sha256:" + "b" * 64
    instance.assert_credential_free = Mock()
    instance.cleanup = Mock()
    return instance


def binding():
    fn = getattr(terminal, "bind_credential_free_environment", None)
    assert callable(fn), "native isolated binding is missing"
    return fn


def test_native_registry_and_config_remain_task_scoped(env):
    identity = "test-engineering-bound"
    before = dict(terminal._active_environments)
    with binding()(identity, env):
        assert terminal.get_active_env(identity) is env
        cfg = terminal._get_env_config()
        assert cfg["env_type"] == "docker"
        assert cfg["cwd"] == "/workspace"
        assert cfg["docker_network"] is False
        assert not cfg["docker_volumes"]
        assert not cfg["docker_forward_env"]
        assert not cfg["docker_env"]
    assert terminal._active_environments == before
    assert identity not in terminal._task_env_overrides
    env.cleanup.assert_called_once()


def test_native_file_tools_use_the_same_bound_environment(env):
    from tools.file_tools import _get_file_ops
    with binding()("test-engineering-files", env):
        ops = _get_file_ops("test-engineering-files")
        assert ops.env is env


def test_loss_of_environment_cannot_create_a_normal_or_parent_sandbox(env):
    identity = "test-engineering-loss"
    with binding()(identity, env):
        terminal._active_environments.pop(identity)
        with pytest.raises(RuntimeError, match="recreat"):
            terminal._create_environment(env_type="docker", image="anything", cwd="/workspace", timeout=1)


def test_sibling_or_missing_task_cannot_use_bound_context(env):
    with binding()("test-engineering-owner", env):
        for identity in (None, "sibling"):
            with pytest.raises(RuntimeError, match="identity"):
                terminal._resolve_container_task_id(identity)


def test_no_nested_binding_or_foreign_instance_is_admitted(env):
    with pytest.raises((TypeError, ValueError)):
        with binding()("test-engineering-foreign", object()):
            pytest.fail("untrusted environment was admitted")
    with binding()("test-engineering-one", env):
        with pytest.raises(RuntimeError):
            with binding()("test-engineering-two", env):
                pytest.fail("nested binding was admitted")
