"""Credential minimization at real child-environment boundaries."""

import json
import os
import subprocess
import sys
from contextlib import contextmanager

import pytest

from agent import terminal_env_registry as registry
from agent.terminal_env_provider import TerminalEnvironmentProvider
from tools.environments import local

SECRET = "TEST_ONLY_SECRET_DO_NOT_USE"


def test_invalid_protected_snapshot_identifier_refuses_before_shell(tmp_path, monkeypatch):
    environment = object.__new__(local.LocalEnvironment)
    environment.env = {"GATEWAY_RELAY_INVALID-NAME_SECRET": SECRET}
    environment._snapshot_path = str(tmp_path / "missing.sh")
    environment._snapshot_passthrough_names = set()
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    with pytest.raises(RuntimeError, match="(?i)(identifier|environment.*name)"):
        environment._snapshot_excluded_passthrough_names()
ADAPTER_KEYS = (
    "WHATSAPP_CLOUD_ACCESS_TOKEN", "WHATSAPP_CLOUD_APP_SECRET",
    "WEIXIN_TOKEN", "YUANBAO_APP_SECRET", "FEISHU_ENCRYPT_KEY",
    "TELEGRAM_WEBHOOK_SECRET", "PHOTON_SIDECAR_TOKEN",
    "HERMES_DASHBOARD_SECRET", "HERMES_DASHBOARD_DRAIN_TOKEN",
    "HERMES_DASHBOARD_OIDC_CLIENT_SECRET",
    "HERMES_DASHBOARD_BASIC_AUTH_PASSWORD", "HERMES_DASHBOARD_BASIC_AUTH_SECRET",
    "HERMES_DASHBOARD_DRAIN_SECRET", "HERMES_ANON_API_SECRET",
)
PROVIDER_KEYS = ("NOUS_API_KEY", "QWEN_API_KEY")


@pytest.fixture(autouse=True)
def isolated_launch_identity(monkeypatch):
    from hermes_cli import env_loader
    monkeypatch.setattr(env_loader, "_LAUNCH_PROFILE_HOME", None, raising=False)


class SecretProvider(TerminalEnvironmentProvider):
    name = "credential-boundary-test"

    @property
    def strip_env_keys(self):
        return frozenset({"FAKE_PLUGIN_SECRET"})

    def is_available(self):
        return True

    def create_environment(self, **kwargs):
        raise AssertionError("the test must not create a plugin runtime")


def child_env(surface, extra=None):
    if surface == "terminal":
        return local._make_run_env(extra or {})
    if surface == "background":
        return local._sanitize_subprocess_env(dict(os.environ), extra)
    return local.hermes_subprocess_env(
        inherit_credentials=surface == "credential-cli", extra=extra,
    )


@pytest.fixture
def plugin_provider():
    provider = SecretProvider()
    previous = registry.snapshot_registration(provider.name)
    registry.register_provider(provider)
    try:
        yield provider
    finally:
        registry.restore_registration(provider.name, provider, previous)


@pytest.mark.parametrize("surface", ["terminal", "background", "cli", "credential-cli"])
@pytest.mark.parametrize("key", ADAPTER_KEYS + ("FAKE_PLUGIN_SECRET",))
def test_adapter_and_plugin_secrets_never_reach_child(monkeypatch, plugin_provider, surface, key):
    monkeypatch.setenv(key, SECRET)
    monkeypatch.setenv("BOUNDARY_BENIGN", "present")
    env = child_env(surface)
    assert key not in env
    assert env["BOUNDARY_BENIGN"] == "present"


@pytest.mark.parametrize("surface", ["terminal", "background", "cli"])
@pytest.mark.parametrize("key", PROVIDER_KEYS)
def test_oauth_profile_api_keys_do_not_reach_ordinary_children(monkeypatch, surface, key):
    monkeypatch.setenv(key, SECRET)
    assert key not in child_env(surface)


@pytest.mark.parametrize("surface", ["terminal", "background", "cli", "credential-cli"])
def test_unreadable_security_declaration_blocks_child(monkeypatch, plugin_provider, surface):
    def unreadable(_self):
        raise OSError("test-only unavailable declaration")
    monkeypatch.setattr(SecretProvider, "strip_env_keys", property(unreadable))
    with pytest.raises(RuntimeError, match="(?i)(secret|credential|declaration)"):
        child_env(surface)


@pytest.mark.parametrize("surface", ["terminal", "background"])
@pytest.mark.parametrize("key", ["FAKE_PLUGIN_SECRET", "TELEGRAM_WEBHOOK_SECRET"])
def test_force_prefix_cannot_reintroduce_tier_one_secret(plugin_provider, surface, key):
    extra = {local._HERMES_PROVIDER_ENV_FORCE_PREFIX + key: SECRET}
    assert key not in child_env(surface, extra)


@pytest.mark.parametrize("surface", ["terminal", "background", "cli", "credential-cli"])
def test_native_child_observes_only_benign_values(monkeypatch, plugin_provider, surface):
    keys = ADAPTER_KEYS + ("FAKE_PLUGIN_SECRET", "BOUNDARY_BENIGN")
    for key in keys[:-1]:
        monkeypatch.setenv(key, SECRET)
    monkeypatch.setenv(keys[-1], "present")
    code = "import json,os,sys;sys.stdout.write(json.dumps({k:os.environ.get(k) for k in " + repr(keys) + "}))"
    result = subprocess.run(
        [sys.executable, "-I", "-c", code], env=child_env(surface),
        stdin=subprocess.DEVNULL, capture_output=True, text=True,
        encoding="utf-8", timeout=15, check=True,
    )
    observed = json.loads(result.stdout)
    assert observed["BOUNDARY_BENIGN"] == "present"
    assert all(observed[key] is None for key in keys[:-1])


def declare_platform(home, name, *, secret=True):
    directory = home / "plugins" / "platforms" / "boundary-test"
    directory.mkdir(parents=True)
    manifest = directory / "plugin.yaml"
    manifest.write_text(
        "name: boundary-test\nkind: platform\nrequires_env:\n"
        f"  - name: {name}\n    password: {str(secret).lower()}\n",
        encoding="utf-8",
    )
    return manifest


@contextmanager
def bound_home(home):
    from hermes_constants import set_hermes_home_override, reset_hermes_home_override
    token = set_hermes_home_override(home)
    try:
        yield
    finally:
        reset_hermes_home_override(token)


@pytest.mark.parametrize("surface", ["terminal", "background", "cli", "credential-cli"])
@pytest.mark.parametrize("reverse", [False, True])
@pytest.mark.parametrize("target_kind", ["absent", "benign", "secret"])
def test_profile_owned_value_is_resolved_before_child_policy(
    tmp_path, monkeypatch, surface, reverse, target_kind,
):
    homes = [tmp_path / "profile A", tmp_path / "profile B"]
    for home in homes:
        home.mkdir()
    launch, target = reversed(homes) if reverse else homes
    key = "CUSTOM_SHARED_VALUE"
    declare_platform(launch, key)
    (launch / ".env").write_text(f"{key}={SECRET}\n", encoding="utf-8")
    monkeypatch.setenv("HERMES_HOME", str(launch))
    monkeypatch.setenv(key, SECRET)
    monkeypatch.setenv("BOUNDARY_BENIGN", "present")
    if target_kind != "absent":
        declare_platform(target, key, secret=target_kind == "secret")
        (target / ".env").write_text(f"{key}=target-value\n", encoding="utf-8")
    with bound_home(target):
        env = child_env(surface)
    assert env.get(key) == ("target-value" if target_kind == "benign" else None)
    assert env["BOUNDARY_BENIGN"] == "present"
    assert env["HERMES_HOME"] == str(target)


@pytest.mark.parametrize("surface", ["terminal", "background", "cli", "credential-cli"])
def test_malformed_manifest_blocks_child(tmp_path, surface):
    manifest = declare_platform(tmp_path, "FAKE_PLUGIN_SECRET")
    manifest.write_text("requires_env: [\n", encoding="utf-8")
    with bound_home(tmp_path), pytest.raises(RuntimeError, match="(?i)(secret|declaration|manifest)"):
        child_env(surface)


def test_multiplex_credential_child_requires_bound_profile(monkeypatch):
    from agent import secret_scope
    monkeypatch.setattr(secret_scope, "_MULTIPLEX_ACTIVE", True)
    scope_token = secret_scope.set_secret_scope(None)
    try:
        with pytest.raises(secret_scope.UnscopedSecretError):
            child_env("credential-cli")
    finally:
        secret_scope.reset_secret_scope(scope_token)


@pytest.mark.parametrize("surface", ["terminal", "background", "cli", "credential-cli"])
def test_bare_adapter_token_declaration_is_always_secret(tmp_path, monkeypatch, surface):
    manifest = declare_platform(tmp_path, "TEST_ADAPTER_TOKEN")
    manifest.write_text(
        "kind: platform\nrequires_env:\n  - TEST_ADAPTER_TOKEN\n", encoding="utf-8",
    )
    monkeypatch.setenv("TEST_ADAPTER_TOKEN", SECRET)
    with bound_home(tmp_path):
        assert "TEST_ADAPTER_TOKEN" not in child_env(surface)


def test_oauth_provider_declared_api_key_is_classified(monkeypatch):
    import providers
    from providers.base import ProviderProfile
    from hermes_cli import config
    profile = ProviderProfile(
        name="test-oauth", auth_type="oauth_device_code",
        env_vars=("TEST_OAUTH_API_KEY", "TEST_OAUTH_BASE_URL"),
    )
    monkeypatch.setattr(providers, "list_providers", lambda: [profile])
    monkeypatch.setattr(config, "OPTIONAL_ENV_VARS", dict(config.OPTIONAL_ENV_VARS))
    monkeypatch.setattr(config, "_profile_env_vars_injected", False)
    config._inject_profile_env_vars()
    blocked = local._build_provider_env_blocklist()
    assert "TEST_OAUTH_API_KEY" in blocked
    assert "TEST_OAUTH_BASE_URL" not in blocked


def test_plugin_manifest_cannot_demote_core_provider(tmp_path, monkeypatch):
    declare_platform(tmp_path, "OPENAI_API_KEY", secret=False)
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    monkeypatch.setenv("OPENAI_API_KEY", SECRET)
    with bound_home(tmp_path):
        assert "OPENAI_API_KEY" not in child_env("terminal")
        assert child_env("credential-cli")["OPENAI_API_KEY"] == SECRET


def test_routed_credential_child_receives_target_provider_only(tmp_path, monkeypatch):
    launch, target = tmp_path / "launch", tmp_path / "served"
    launch.mkdir()
    target.mkdir()
    (launch / ".env").write_text("OPENAI_API_KEY=TEST_ONLY_LAUNCH\n", encoding="utf-8")
    (target / ".env").write_text("OPENAI_API_KEY=TEST_ONLY_SERVED\n", encoding="utf-8")
    monkeypatch.setenv("HERMES_HOME", str(launch))
    monkeypatch.setenv("OPENAI_API_KEY", "TEST_ONLY_LAUNCH")
    with bound_home(target):
        assert child_env("credential-cli")["OPENAI_API_KEY"] == "TEST_ONLY_SERVED"
        assert "OPENAI_API_KEY" not in child_env("terminal")


def test_same_profile_empty_scope_preserves_explicit_provider_inheritance(tmp_path, monkeypatch):
    from agent.secret_scope import set_secret_scope, reset_secret_scope
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    monkeypatch.setenv("OPENAI_API_KEY", SECRET)
    token = set_secret_scope({})
    try:
        assert child_env("credential-cli")["OPENAI_API_KEY"] == SECRET
    finally:
        reset_secret_scope(token)


@pytest.mark.parametrize("key", ["TELEGRAM_BOT_TOKEN", "FAKE_PLUGIN_SECRET", "TEST_ADAPTER_TOKEN"])
def test_passthrough_registration_cannot_demote_adapter_authority(tmp_path, monkeypatch, plugin_provider, key):
    from tools import env_passthrough
    token = env_passthrough._allowed_env_vars_var.set(set())
    declare_platform(tmp_path, "TEST_ADAPTER_TOKEN")
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    monkeypatch.setenv(key, SECRET)
    try:
        env_passthrough.register_env_passthrough([key])
        assert key not in env_passthrough.get_all_passthrough()
        assert key not in child_env("terminal")
    finally:
        env_passthrough._allowed_env_vars_var.reset(token)


@pytest.mark.parametrize("surface", ["terminal", "background", "cli", "credential-cli"])
def test_explicit_nonsecret_extra_keeps_precedence(tmp_path, monkeypatch, surface):
    launch, target = tmp_path / "launch", tmp_path / "target"
    launch.mkdir()
    target.mkdir()
    (target / ".env").write_text("CUSTOM_FLAG=target-default\n", encoding="utf-8")
    monkeypatch.setenv("HERMES_HOME", str(launch))
    with bound_home(target):
        assert child_env(surface, {"CUSTOM_FLAG": "explicit-call-value"})["CUSTOM_FLAG"] == "explicit-call-value"


@pytest.mark.parametrize("surface", ["terminal", "background", "cli", "credential-cli"])
def test_invalid_provider_security_declaration_blocks_spawn(monkeypatch, plugin_provider, surface):
    monkeypatch.setattr(SecretProvider, "strip_env_keys", property(lambda _: "FAKE_PLUGIN_SECRET"))
    with pytest.raises(RuntimeError, match="(?i)(secret|declaration)"):
        child_env(surface)


@pytest.mark.parametrize("source", ["user", "op", "project"])
def test_loaded_profile_name_stays_owned_after_source_file_removal(tmp_path, monkeypatch, source):
    from hermes_cli.env_loader import load_hermes_dotenv
    launch, target = tmp_path / "launch", tmp_path / "target"
    launch.mkdir()
    target.mkdir()
    path = launch / ({"user": ".env", "op": ".op.env", "project": "project.env"}[source])
    key = "CUSTOM_REMOVED_PROFILE_VALUE"
    path.write_text(f"{key}={SECRET}\n", encoding="utf-8")
    monkeypatch.setenv("HERMES_HOME", str(launch))
    monkeypatch.delenv("OP_SERVICE_ACCOUNT_TOKEN", raising=False)
    monkeypatch.delenv(key, raising=False)
    load_hermes_dotenv(
        hermes_home=launch, project_env=path if source == "project" else None,
        load_external_secrets=False,
    )
    assert os.environ[key] == SECRET
    path.unlink()
    with bound_home(target):
        assert key not in child_env("terminal")
    monkeypatch.delenv(key, raising=False)


def test_real_cron_profile_context_does_not_relabel_launch_secrets(tmp_path, monkeypatch):
    from cron import scheduler
    launch, target = tmp_path / "launch", tmp_path / "target"
    launch.mkdir()
    target.mkdir()
    key = "CUSTOM_CRON_LAUNCH_VALUE"
    (launch / ".env").write_text(f"{key}={SECRET}\n", encoding="utf-8")
    monkeypatch.setenv("HERMES_HOME", str(launch))
    monkeypatch.setenv(key, SECRET)
    monkeypatch.setattr(scheduler, "_execution_home_for_job", lambda _: target)
    with scheduler._cron_profile_context({"id": "test-only", "profile": "served"}):
        assert os.environ["HERMES_HOME"] == str(target)
        assert key not in child_env("terminal")


@pytest.mark.parametrize("surface", ["terminal", "background", "cli", "credential-cli"])
@pytest.mark.parametrize("force", [False, True])
def test_extra_cannot_restore_launch_owned_secret(tmp_path, monkeypatch, surface, force):
    launch, target = tmp_path / "launch", tmp_path / "target"
    launch.mkdir()
    target.mkdir()
    key = "CUSTOM_PROFILE_VALUE"
    declare_platform(launch, key)
    monkeypatch.setenv("HERMES_HOME", str(launch))
    monkeypatch.setenv(key, SECRET)
    extra_key = local._HERMES_PROVIDER_ENV_FORCE_PREFIX + key if force else key
    with bound_home(target):
        assert key not in child_env(surface, {extra_key: SECRET})


def test_strict_allowlist_does_not_import_arbitrary_target_profile_values(tmp_path, monkeypatch):
    launch, target = tmp_path / "launch", tmp_path / "target"
    launch.mkdir()
    target.mkdir()
    (target / ".env").write_text("CUSTOM_TARGET_CANARY=TEST_ONLY_SECRET_DO_NOT_USE\n", encoding="utf-8")
    monkeypatch.setenv("HERMES_HOME", str(launch))
    with bound_home(target):
        assert "CUSTOM_TARGET_CANARY" not in local.hermes_subprocess_env(allowlist_only=True)


@pytest.mark.parametrize("surface", ["terminal", "background", "cli", "credential-cli"])
@pytest.mark.parametrize("key", ["TELEGRAM_BOT_TOKEN", "MSGRAPH_CLIENT_SECRET", "MSGRAPH_WEBHOOK_CLIENT_STATE", "QQ_STT_API_KEY", "RAFT_CHANNEL_TOKEN"])
def test_core_adapter_secret_cannot_be_forced_into_ordinary_child(monkeypatch, surface, key):
    monkeypatch.setenv(key, SECRET)
    extra = {local._HERMES_PROVIDER_ENV_FORCE_PREFIX + key: SECRET}
    assert key not in child_env(surface, extra)


@pytest.mark.parametrize("surface", ["terminal", "background", "cli"])
def test_runtime_adapter_secret_is_filtered_without_loading_deferred_plugins(monkeypatch, surface):
    import gateway.platform_registry as platform_module
    registry = platform_module.PlatformRegistry()
    registry.register(platform_module.PlatformEntry(
        name="test-boundary", label="Test", adapter_factory=lambda _: None,
        check_fn=lambda: True, required_env=["CUSTOM_ADAPTER_TOKEN", "OPENAI_API_KEY"],
    ))
    registry.register_deferred("must-stay-deferred", lambda: pytest.fail("security scan loaded plugin code"))
    monkeypatch.setattr(platform_module, "platform_registry", registry)
    monkeypatch.setenv("CUSTOM_ADAPTER_TOKEN", SECRET)
    assert "CUSTOM_ADAPTER_TOKEN" not in child_env(surface)
    monkeypatch.setenv("OPENAI_API_KEY", SECRET)
    assert child_env("credential-cli")["OPENAI_API_KEY"] == SECRET


def test_global_runtime_declaration_survives_minimal_os_environment(monkeypatch):
    import gateway.platform_registry as platform_module
    registry = platform_module.PlatformRegistry()
    registry.register(platform_module.PlatformEntry(
        name="test-minimal", label="Test", adapter_factory=lambda _: None,
        check_fn=lambda: True, required_env=["CUSTOM_ADAPTER_TOKEN"],
    ))
    monkeypatch.setattr(platform_module, "platform_registry", registry)
    from unittest.mock import patch
    with patch.dict(os.environ, {"HOME": "/test-only-home", "CUSTOM_ADAPTER_TOKEN": SECRET}, clear=True):
        assert "CUSTOM_ADAPTER_TOKEN" not in child_env("cli")


@pytest.mark.parametrize("invalid_global", [False, True])
def test_scoped_adapter_override_cannot_hide_global_security_declaration(tmp_path, monkeypatch, invalid_global):
    import gateway.platform_registry as platform_module
    registry = platform_module.PlatformRegistry()
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    monkeypatch.setenv("GLOBAL_ADAPTER_TOKEN", SECRET)
    registry.register(platform_module.PlatformEntry(
        name="same-adapter", label="Global", adapter_factory=lambda _: None,
        check_fn=lambda: True, required_env="invalid" if invalid_global else ["GLOBAL_ADAPTER_TOKEN"],
    ))
    registry.register(platform_module.PlatformEntry(
        name="same-adapter", label="Scoped", adapter_factory=lambda _: None,
        check_fn=lambda: True, required_env=["SCOPED_ADAPTER_TOKEN"],
    ), scope=registry.current_scope_key())
    monkeypatch.setattr(platform_module, "platform_registry", registry)
    if invalid_global:
        with pytest.raises(RuntimeError, match="(?i)(credential|declaration)"):
            child_env("cli")
    else:
        assert "GLOBAL_ADAPTER_TOKEN" not in child_env("cli")


@pytest.mark.parametrize("field", ["requires_env", "optional_env"])
@pytest.mark.parametrize("value", [False, 0, "", {}])
def test_falsey_non_list_manifest_declaration_refuses_child(tmp_path, monkeypatch, field, value):
    directory = tmp_path / "plugins/platforms/test-falsey"
    directory.mkdir(parents=True)
    (directory / "plugin.yaml").write_text(json.dumps({"kind": "platform", field: value}), encoding="utf-8")
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    with pytest.raises(RuntimeError, match="(?i)(secret|declaration)"):
        child_env("cli")


@pytest.mark.parametrize("field", ["requires_env", "optional_env"])
@pytest.mark.parametrize("value", [None, []])
def test_explicit_empty_or_null_manifest_list_retains_benign_child(tmp_path, monkeypatch, field, value):
    directory = tmp_path / "plugins/platforms/test-empty"
    directory.mkdir(parents=True)
    (directory / "plugin.yaml").write_text(json.dumps({"kind": "platform", field: value}), encoding="utf-8")
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    monkeypatch.setenv("BOUNDARY_BENIGN", "kept")
    assert child_env("cli")["BOUNDARY_BENIGN"] == "kept"


@pytest.mark.skipif(sys.platform != "win32", reason="Windows canonical default-home routing")
def test_default_windows_launch_home_uses_canonical_resolver(tmp_path, monkeypatch):
    from hermes_cli.env_loader import load_hermes_dotenv
    local_appdata, user = tmp_path / "Local", tmp_path / "User"
    canonical, target = local_appdata / "hermes", tmp_path / "served"
    canonical.mkdir(parents=True)
    target.mkdir()
    user.mkdir()
    key = "CUSTOM_DEFAULT_PROFILE_VALUE"
    (canonical / ".env").write_text(f"{key}={SECRET}\n", encoding="utf-8")
    monkeypatch.delenv("HERMES_HOME", raising=False)
    monkeypatch.setenv("LOCALAPPDATA", str(local_appdata))
    monkeypatch.setenv("USERPROFILE", str(user))
    monkeypatch.setenv("HOME", str(user))
    monkeypatch.setenv(key, SECRET)
    load_hermes_dotenv(load_external_secrets=False)
    with bound_home(target):
        assert key not in child_env("terminal")


@pytest.mark.parametrize("flag", ["secret", "password"])
@pytest.mark.parametrize("value", [[], {}, 0, "false"])
def test_invalid_manifest_security_flag_refuses_child(tmp_path, monkeypatch, flag, value):
    directory = tmp_path / "plugins/platforms/test-flag"
    directory.mkdir(parents=True)
    (directory / "plugin.yaml").write_text(json.dumps({
        "kind": "platform", "requires_env": [{"name": "CUSTOM_LOGIN", flag: value}],
    }), encoding="utf-8")
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    monkeypatch.setenv("CUSTOM_LOGIN", SECRET)
    with pytest.raises(RuntimeError, match="(?i)(secret|declaration)"):
        child_env("cli")


@pytest.mark.parametrize("surface", ["terminal", "background", "cli"])
def test_late_oauth_provider_credential_is_filtered(monkeypatch, surface):
    from types import SimpleNamespace
    import providers
    monkeypatch.setattr(providers, "list_providers", lambda: [SimpleNamespace(
        name="test-late-oauth", auth_type="oauth", env_vars=("CUSTOM_OAUTH_API_KEY",),
    )])
    monkeypatch.setenv("CUSTOM_OAUTH_API_KEY", SECRET)
    assert "CUSTOM_OAUTH_API_KEY" not in child_env(surface)
    assert child_env("credential-cli")["CUSTOM_OAUTH_API_KEY"] == SECRET


@pytest.mark.parametrize("surface", ["terminal", "background", "cli", "credential-cli"])
def test_invalid_provider_profile_declaration_refuses_child(monkeypatch, surface):
    from types import SimpleNamespace
    import providers
    monkeypatch.setattr(providers, "list_providers", lambda: [
        SimpleNamespace(name="invalid-oauth", auth_type="oauth", env_vars=None),
        SimpleNamespace(name="valid-oauth", auth_type="oauth", env_vars=("CUSTOM_OAUTH_API_KEY",)),
    ])
    monkeypatch.setenv("CUSTOM_OAUTH_API_KEY", SECRET)
    with pytest.raises(RuntimeError, match="(?i)(credential|declaration)"):
        child_env(surface)


@pytest.mark.parametrize("source", ["skill", "config"])
@pytest.mark.parametrize("surface", ["terminal", "background", "cli"])
def test_cached_passthrough_rechecks_late_adapter_ownership(monkeypatch, tmp_path, source, surface):
    from tools import env_passthrough
    import gateway.platform_registry as platform_module
    adapter_registry = platform_module.PlatformRegistry()
    monkeypatch.setattr(platform_module, "platform_registry", adapter_registry)
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    key = "CUSTOM_LATE_ADAPTER_TOKEN"
    token = env_passthrough._allowed_env_vars_var.set(set())
    monkeypatch.setattr(env_passthrough, "_config_passthrough", frozenset({key}) if source == "config" else frozenset())
    try:
        if source == "skill":
            env_passthrough.register_env_passthrough([key])
        assert env_passthrough.is_env_passthrough(key)
        adapter_registry.register(platform_module.PlatformEntry(
            name="late-adapter", label="Late", adapter_factory=lambda _: None,
            check_fn=lambda: True, required_env=[key],
        ))
        monkeypatch.setenv(key, SECRET)
        assert key not in child_env(surface)
        assert not env_passthrough.is_env_passthrough(key)
        assert key not in env_passthrough.get_all_passthrough()
    finally:
        env_passthrough._allowed_env_vars_var.reset(token)


@pytest.mark.parametrize("surface", ["terminal", "background", "cli", "credential-cli"])
def test_registered_benign_extra_keeps_explicit_precedence(tmp_path, monkeypatch, surface):
    from tools import env_passthrough
    from agent.secret_scope import set_secret_scope, reset_secret_scope
    launch, target = tmp_path / "launch", tmp_path / "target"
    launch.mkdir()
    target.mkdir()
    (target / ".env").write_text("CUSTOM_FLAG=target-default\n", encoding="utf-8")
    monkeypatch.setenv("HERMES_HOME", str(launch))
    token = env_passthrough._allowed_env_vars_var.set({"CUSTOM_FLAG"})
    scope_token = set_secret_scope({"CUSTOM_FLAG": "target-default"})
    try:
        with bound_home(target):
            assert child_env(surface, {"CUSTOM_FLAG": "explicit-call-value"})["CUSTOM_FLAG"] == "explicit-call-value"
    finally:
        reset_secret_scope(scope_token)
        env_passthrough._allowed_env_vars_var.reset(token)


@pytest.mark.parametrize("surface", ["terminal", "background", "cli", "credential-cli"])
def test_provider_discovery_preserves_user_cli_oauth_and_general_aws(monkeypatch, surface):
    from types import SimpleNamespace
    import providers
    monkeypatch.setattr(providers, "list_providers", lambda: [
        SimpleNamespace(auth_type="api_key", env_vars=("CLAUDE_CODE_OAUTH_TOKEN", "ANTHROPIC_API_KEY")),
        SimpleNamespace(auth_type="aws_sdk", env_vars=("AWS_ACCESS_KEY_ID", "AWS_SECRET_ACCESS_KEY")),
    ])
    keys = ("CLAUDE_CODE_OAUTH_TOKEN", "AWS_ACCESS_KEY_ID", "AWS_SECRET_ACCESS_KEY")
    for key in keys:
        monkeypatch.setenv(key, SECRET)
    env = child_env(surface)
    assert all(env.get(key) == SECRET for key in keys)


def test_late_provider_keeps_tier_two_authority_over_manifest(tmp_path, monkeypatch):
    from types import SimpleNamespace
    import providers
    key = "LATE_OAUTH_API_KEY"
    monkeypatch.setattr(providers, "list_providers", lambda: [SimpleNamespace(auth_type="oauth", env_vars=(key,))])
    declare_platform(tmp_path, key)
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    monkeypatch.setenv(key, SECRET)
    assert key not in child_env("cli")
    assert child_env("credential-cli")[key] == SECRET


def test_dangling_manifest_link_is_unreadable_declaration(tmp_path, monkeypatch):
    directory = tmp_path / "plugins/platforms/test-link"
    directory.mkdir(parents=True)
    manifest = directory / "plugin.yaml"
    target = tmp_path / "manifest-target.yaml"
    target.write_text('kind: platform\nrequires_env:\n  - name: CUSTOM_LOGIN\n    secret: true\n', encoding="utf-8")
    manifest.write_bytes(target.read_bytes())
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    monkeypatch.setenv("CUSTOM_LOGIN", SECRET)
    assert "CUSTOM_LOGIN" not in child_env("cli")
    manifest.unlink()
    # Model a placed dangling file link's lstat result. Windows native file
    # symlink creation requires a privilege unavailable to this test account.
    original = os.path.lexists
    monkeypatch.setattr(os.path, "lexists", lambda path: str(path) == str(manifest) or original(path))
    with pytest.raises(RuntimeError, match="(?i)(secret|declaration)"):
        child_env("cli")


@pytest.mark.skipif(sys.platform != "win32", reason="native Windows junction boundary")
def test_native_dangling_platform_junction_refuses_child(tmp_path, monkeypatch):
    directory = tmp_path / "plugins/platforms"
    directory.mkdir(parents=True)
    target = tmp_path / "platform target"
    target.mkdir()
    (target / "plugin.yaml").write_text('kind: platform\nrequires_env:\n  - name: CUSTOM_LOGIN\n    secret: true\n', encoding="utf-8")
    junction = directory / "test-junction"
    subprocess.run([os.environ.get("COMSPEC", "cmd.exe"), "/c", "mklink", "/J", str(junction), str(target)],
                   stdin=subprocess.DEVNULL, capture_output=True, timeout=10, check=True)
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    monkeypatch.setenv("CUSTOM_LOGIN", SECRET)
    moved = tmp_path / "moved-platform-target"
    try:
        assert "CUSTOM_LOGIN" not in child_env("cli")
        target.rename(moved)
        assert os.path.lexists(junction) and not junction.exists()
        with pytest.raises(RuntimeError, match="(?i)(secret|declaration)"):
            child_env("cli")
    finally:
        junction.rmdir()


@pytest.mark.parametrize("surface", ["terminal", "background", "cli", "credential-cli"])
def test_startup_sdk_registration_preserves_general_aws_credentials(monkeypatch, surface):
    import providers
    from providers.base import ProviderProfile
    from hermes_cli import config
    keys = ("AWS_ACCESS_KEY_ID", "AWS_SECRET_ACCESS_KEY", "AWS_SESSION_TOKEN")
    monkeypatch.setattr(providers, "list_providers", lambda: [ProviderProfile(
        name="test-startup-sdk", auth_type="aws_sdk", env_vars=keys,
    )])
    monkeypatch.setattr(config, "OPTIONAL_ENV_VARS", {k: v for k, v in config.OPTIONAL_ENV_VARS.items() if k not in keys})
    monkeypatch.setattr(config, "_profile_env_vars_injected", False)
    config._inject_profile_env_vars()
    # Execute the same static-owner derivation used during local import.
    monkeypatch.setattr(local, "_HERMES_PROVIDER_ENV_BLOCKLIST", local._build_provider_env_blocklist())
    for key in keys:
        monkeypatch.setenv(key, SECRET)
    env = child_env(surface)
    assert all(env.get(key) == SECRET for key in keys)
