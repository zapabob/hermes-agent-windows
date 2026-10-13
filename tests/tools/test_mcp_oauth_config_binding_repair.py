"""Actual storage, public admission, and flow settlement regression contracts."""
import asyncio
import json
import threading
from copy import deepcopy

import pytest
import yaml

from tests.fakes.mcp_oauth_gateway import homes as homes, scoped
from tests.tools.test_mcp_oauth_config_writer_locking import (
    assert_lock_available, config_file as config_file, paused_worker,
)


def make_flow(home, binding=None):
    from tools.mcp_dashboard_oauth import DashboardOAuthFlow
    return DashboardOAuthFlow(
        flow_id="synthetic-flow", server_name="target", profile=None,
        hermes_home=str(home), redirect_uri="http://127.0.0.1:43123/callback",
        config_binding=binding,
    )


def capture_storage(home):
    from tools.mcp_dashboard_oauth import SavedMcpConfigBinding
    from tools.mcp_oauth import HermesTokenStorage
    binding = SavedMcpConfigBinding.capture(home, "target")
    storage = HermesTokenStorage("target", hermes_home=home, binding=binding)
    return binding, storage


def test_actual_bound_storage_read_rejects_replaced_config(config_file):
    from tools.mcp_dashboard_oauth import McpOAuthConfigChangedError
    binding, storage = capture_storage(config_file.parent)
    storage._write_oauth_json(storage._tokens_path(), {"access_token": "old", "token_type": "Bearer"})
    config_file.write_text("mcp_servers:\n  target:\n    command: replacement\n", encoding="utf-8")
    with pytest.raises(McpOAuthConfigChangedError):
        asyncio.run(storage.get_tokens())
    assert not binding.sealed


def test_captured_home_writes_only_original_profile(config_file, tmp_path):
    binding, storage = capture_storage(config_file.parent)
    other = tmp_path / "other-profile"
    other.mkdir()
    (other / "config.yaml").write_text("sentinel: keep\n", encoding="utf-8")
    before = list(other.iterdir())
    with scoped(other):
        storage._write_oauth_json(storage._tokens_path(), {"access_token": "owned", "token_type": "Bearer"})
    assert storage._tokens_path().is_relative_to(config_file.parent)
    assert json.loads(storage._tokens_path().read_text(encoding="utf-8"))["access_token"] == "owned"
    assert list(other.iterdir()) == before
    assert (other / "config.yaml").read_text(encoding="utf-8") == "sentinel: keep\n"


@pytest.mark.parametrize("operation", ["stamp_issuer", "strip_refresh_token"])
def test_actual_storage_rmw_serializes_newer_writer(monkeypatch, config_file, operation):
    from hermes_cli import config
    from tools import mcp_oauth
    _, storage = capture_storage(config_file.parent)
    newer = mcp_oauth.HermesTokenStorage("target", hermes_home=config_file.parent)
    path = storage._tokens_path()
    storage._write_oauth_json(path, {"access_token": "old", "refresh_token": "old-refresh", "token_type": "Bearer"})
    real_read = mcp_oauth._read_json
    ident = []
    def action(pause):
        ident.append(threading.get_ident())
        def read(target):
            value = real_read(target)
            if target == path and threading.get_ident() == ident[0]:
                pause()
            return value
        monkeypatch.setattr(mcp_oauth, "_read_json", read)
        if operation == "stamp_issuer":
            storage.stamp_issuer("https://issuer.example")
        else:
            storage.strip_refresh_token()
    failures = []
    attempted = threading.Event()
    def write_newer():
        attempted.set()
        try:
            newer._write_oauth_json(path, {"access_token": "newer", "refresh_token": "newer-refresh", "token_type": "Bearer"})
        except BaseException as exc:
            failures.append(exc)
    contender = None
    try:
        with paused_worker(action):
            assert_lock_available(config._CONFIG_LOCK, False)
            contender = threading.Thread(target=write_newer, daemon=True)
            contender.start()
            assert attempted.wait(10)
    finally:
        if contender is not None:
            contender.join(10)
    assert contender is not None and not contender.is_alive()
    assert not failures, failures
    saved = json.loads(path.read_text(encoding="utf-8"))
    assert saved["access_token"] == "newer"
    assert saved["refresh_token"] == "newer-refresh"
    assert "hermes_issuer" not in saved


@pytest.mark.parametrize("managed", ["installation", "auth_key"])
def test_actual_flow_adoption_refuses_managed_auth_commit(monkeypatch, config_file, managed):
    from hermes_cli import config, managed_scope
    binding, storage = capture_storage(config_file.parent)
    flow = make_flow(config_file.parent, binding)
    storage._write_oauth_json(storage._tokens_path(), {"access_token": "owned", "token_type": "Bearer"})
    before = config_file.read_bytes()
    monkeypatch.setattr(config, "is_managed", lambda: managed == "installation")
    monkeypatch.setattr(managed_scope, "is_key_managed", lambda key: managed == "auth_key" and key == "mcp_servers.target.auth")
    with pytest.raises(RuntimeError):
        flow.adopt_approved(storage, [])
    assert flow.status != "approved"
    assert not binding.sealed
    assert config_file.read_bytes() == before


def test_public_rpc_admission_rechecks_after_captured_read(monkeypatch, homes):
    from hermes_cli import mcp_config
    from tui_gateway import mcp_oauth_sessions as sessions, server
    home = homes / "profiles" / "work"
    with scoped(home):
        mcp_config._replace_mcp_servers({"target": {"url": "https://old.example/mcp"}})
    actual_start = sessions.start_flow
    reached = []
    def forbidden_listener(*args, **kwargs):
        reached.append("listener")
        raise AssertionError("stale admission started a listener")
    monkeypatch.setattr(sessions, "_start_loopback_listener", forbidden_listener)
    def action(pause):
        def start(*args, **kwargs):
            assert kwargs["config_binding"].expected_entry["url"] == "https://old.example/mcp"
            pause()
            return actual_start(*args, **kwargs)
        monkeypatch.setattr(sessions, "start_flow", start)
        return server._methods["mcp.servers.oauth.start"](10, {"profile": "work", "name": "target"})
    with paused_worker(action) as results:
        with scoped(home):
            mcp_config._replace_mcp_servers({"target": {"url": "https://new.example/mcp"}})
    assert "error" in results[0]
    assert not reached
    assert not sessions._sessions


@pytest.mark.parametrize("change", ["http_url", "stdio_command", "disable", "unrelated"])
def test_public_secret_rpc_rechecks_exact_target_after_unlocked_io(monkeypatch, homes, change):
    from hermes_cli import config, mcp_config
    from tui_gateway import server
    home = homes / "profiles" / "work"
    original = {"command": "old.exe"} if change == "stdio_command" else {"url": "https://old.example/mcp"}
    with scoped(home):
        mcp_config._replace_mcp_servers({"target": original, "other": {"command": "other.exe"}})
    live_lock = threading.RLock()
    monkeypatch.setattr(config, "_CONFIG_LOCK", live_lock)
    secret_calls = []
    def action(pause):
        def save_secret(key, value):
            secret_calls.append((key, value))
            pause()
        monkeypatch.setattr(config, "save_env_value", save_secret)
        return server._methods["mcp.servers.set_api_key"](11, {
            "profile": "work", "name": "target", "value": "synthetic-secret",
        })
    replacement = deepcopy(original)
    if change == "http_url":
        replacement["url"] = "https://replacement.example/mcp"
    elif change == "stdio_command":
        replacement["command"] = "replacement.exe"
    elif change == "disable":
        replacement["enabled"] = False
    with paused_worker(action) as results:
        assert_lock_available(live_lock, True)
        with scoped(home):
            mcp_config._replace_mcp_servers({
                "target": replacement, "other": {"command": "new-other.exe"},
            })
    saved = yaml.safe_load((home / "config.yaml").read_text(encoding="utf-8"))
    assert len(secret_calls) == 1
    assert saved["mcp_servers"]["other"] == {"command": "new-other.exe"}
    if change == "unrelated":
        assert "result" in results[0]
        assert saved["mcp_servers"]["target"]["url"] == original["url"]
        assert saved["mcp_servers"]["target"]["headers"]["Authorization"].startswith("Bearer $")
    else:
        assert "error" in results[0]
        assert saved["mcp_servers"]["target"] == replacement


@pytest.mark.parametrize("ending", ["cancel", "error"])
@pytest.mark.parametrize("replacement", ["owned", "newer"])
@pytest.mark.parametrize("identity_timing", ["before_terminal", "after_terminal"])
def test_real_flow_terminal_restore_preserves_provider_identity(monkeypatch, config_file, ending, replacement, identity_timing):
    from tools import mcp_oauth
    from tools.mcp_oauth_manager import MCPOAuthManager, _ProviderEntry
    monkeypatch.setattr(mcp_oauth, "remove_oauth_tokens", lambda *_a, **_k: None)
    manager = MCPOAuthManager()
    home = config_file.parent
    binding, _ = capture_storage(home)
    flow = make_flow(home, binding)
    key = manager._key("target", home)
    previous = _ProviderEntry(server_url="https://old.example", oauth_config={})
    previous.provider = object()
    owned = _ProviderEntry(server_url="https://flow.example", oauth_config={})
    owned.provider = object()
    newer = _ProviderEntry(server_url="https://new.example", oauth_config={})
    newer.provider = object()
    manager._entries[key] = previous
    assert manager.remove("target", hermes_home=home, removal_owner=flow) is previous
    if identity_timing == "before_terminal":
        flow.record_provider_identity(owned, owned.provider)
    manager._entries[key] = owned if replacement == "owned" else newer
    if ending == "cancel":
        assert flow.cancel_pending()
    else:
        flow.mark_error("synthetic failure")
    if identity_timing == "after_terminal":
        flow.record_provider_identity(owned, owned.provider)
    assert flow.provider_settlement_identity() == (owned, owned.provider, False)
    manager.restore_entry("target", previous, hermes_home=home, binding=binding, removal_owner=flow)
    assert manager._entries[key] is (previous if replacement == "owned" else newer)
    manager.release_dashboard_flow(flow)
    assert key not in manager._removed_entry_owners
    assert flow.provider_settlement_identity() == (None, None, False)


@pytest.mark.parametrize("outcome", ["success", "no_previous", "stale", "new_owner"])
def test_terminal_settlement_releases_only_own_record(monkeypatch, config_file, outcome):
    from tools.mcp_oauth_manager import MCPOAuthManager, _ProviderEntry
    manager = MCPOAuthManager()
    binding, _ = capture_storage(config_file.parent)
    flow = make_flow(config_file.parent, binding)
    key = manager._key("target", config_file.parent)
    entry = _ProviderEntry(server_url="https://flow.example", oauth_config={})
    entry.provider = object()
    flow.record_provider_identity(entry, entry.provider)
    owner = make_flow(config_file.parent) if outcome == "new_owner" else flow
    manager._removed_entry_owners[key] = owner
    manager._entries[key] = entry
    if outcome == "success":
        flow.mark_approved()
    elif outcome == "stale":
        config_file.write_text("mcp_servers: {}\n", encoding="utf-8")
        manager.restore_entry("target", entry, hermes_home=config_file.parent, binding=binding, removal_owner=flow)
    elif outcome == "no_previous":
        manager.restore_entry("target", None, hermes_home=config_file.parent, binding=binding, removal_owner=flow)
    manager.release_dashboard_flow(flow)
    assert manager._entries[key] is entry
    assert flow.provider_settlement_identity() == (None, None, False)
    if outcome == "new_owner":
        assert manager._removed_entry_owners[key] is owner
    else:
        assert key not in manager._removed_entry_owners


def test_mcp_write_preserves_target_and_unrelated_raw_templates(config_file):
    from hermes_cli import mcp_config
    config_file.write_text(
        "mcp_servers:\n  other:\n    env:\n      KEEP: ${KEEP_RAW}\n"
        "  target:\n    command: old\n", encoding="utf-8",
    )
    mcp_config._save_mcp_server("target", {"command": "new", "env": {"TARGET": "${TARGET_RAW}"}})
    saved = yaml.safe_load(config_file.read_text(encoding="utf-8"))
    assert saved["mcp_servers"]["other"]["env"]["KEEP"] == "${KEEP_RAW}"
    assert saved["mcp_servers"]["target"]["env"]["TARGET"] == "${TARGET_RAW}"


@pytest.mark.parametrize("change", ["url", "headers"])
def test_stale_active_flow_acquisition_preserves_newer_provider_owner(config_file, change):
    from hermes_cli import mcp_config
    from tools.mcp_dashboard_oauth import (
        McpOAuthConfigChangedError, SavedMcpConfigBinding, dashboard_oauth_flow,
    )
    from tools.mcp_oauth import HermesTokenStorage
    from tools.mcp_oauth_manager import MCPOAuthManager

    home = config_file.parent
    manager = MCPOAuthManager()
    old_url = "https://old.example/mcp"
    original = {"url": old_url, "auth": "oauth", "oauth": {"cimd": False}}
    with scoped(home):
        mcp_config._save_mcp_server("target", original)
        stale_flow = make_flow(home, SavedMcpConfigBinding.capture(home, "target"))
        replacement = deepcopy(original)
        if change == "url":
            replacement["url"] = "https://new.example/mcp"
        else:
            replacement["headers"] = {"X-Profile": "new-owner"}
        mcp_config._save_mcp_server("target", replacement)
        runtime_storage = HermesTokenStorage("target", hermes_home=home)
        runtime_storage._write_oauth_json(runtime_storage._tokens_path(), {
            "access_token": "new-owner", "token_type": "Bearer",
        })
        newer_provider = manager.get_or_build_provider(
            "target", replacement["url"], replacement["oauth"],
        )
        assert newer_provider is not None
        key = manager._key("target", home)
        newer_entry = manager._entries[key]
        newer_owner = make_flow(home, SavedMcpConfigBinding.capture(home, "target"))
        manager._removed_entry_owners[key] = newer_owner
        token_bytes = runtime_storage._tokens_path().read_bytes()
        config_bytes = config_file.read_bytes()

        with dashboard_oauth_flow(stale_flow):
            with pytest.raises(McpOAuthConfigChangedError):
                manager.get_or_build_provider("target", old_url, original["oauth"])

        assert manager._entries[key] is newer_entry
        assert manager._entries[key].provider is newer_provider
        assert manager._removed_entry_owners[key] is newer_owner
        assert stale_flow.provider_settlement_identity() == (None, None, False)
        assert runtime_storage._tokens_path().read_bytes() == token_bytes
        assert config_file.read_bytes() == config_bytes


@pytest.mark.parametrize("bound", [False, True])
def test_current_provider_acquisition_reuses_real_provider(config_file, bound):
    from contextlib import nullcontext
    from hermes_cli import mcp_config
    from tools.mcp_dashboard_oauth import SavedMcpConfigBinding, dashboard_oauth_flow
    from tools.mcp_oauth import HermesTokenStorage
    from tools.mcp_oauth_manager import MCPOAuthManager

    home = config_file.parent
    manager = MCPOAuthManager()
    cfg = {"url": "https://current.example/mcp", "auth": "oauth", "oauth": {"cimd": False}}
    with scoped(home):
        mcp_config._save_mcp_server("target", cfg)
        storage = HermesTokenStorage("target", hermes_home=home)
        storage._write_oauth_json(storage._tokens_path(), {
            "access_token": "current-owner", "token_type": "Bearer",
        })
        flow = make_flow(home, SavedMcpConfigBinding.capture(home, "target"))
        context = dashboard_oauth_flow(flow) if bound else nullcontext()
        with context:
            first = manager.get_or_build_provider("target", cfg["url"], cfg["oauth"])
            second = manager.get_or_build_provider("target", cfg["url"], cfg["oauth"])
        assert first is not None and second is first
        assert isinstance(first.context.storage, HermesTokenStorage)
        entry = manager._entries[manager._key("target", home)]
        assert entry.provider is first
        if bound:
            assert flow.provider_settlement_identity() == (entry, first, False)
        else:
            assert flow.provider_settlement_identity() == (None, None, False)


def test_unbound_acquisition_keeps_profile_provider_caches_separate(config_file):
    from tools.mcp_oauth import HermesTokenStorage
    from tools.mcp_oauth_manager import MCPOAuthManager

    manager = MCPOAuthManager()
    first_home = config_file.parent
    second_home = first_home / "other-profile"
    second_home.mkdir()
    (second_home / "config.yaml").write_text(config_file.read_text(encoding="utf-8"), encoding="utf-8")
    providers = []
    for home in (first_home, second_home):
        with scoped(home):
            storage = HermesTokenStorage("target", hermes_home=home)
            storage._write_oauth_json(storage._tokens_path(), {
                "access_token": "synthetic-profile-token", "token_type": "Bearer",
            })
            provider = manager.get_or_build_provider("target", "https://same.example/mcp", {"cimd": False})
            assert provider is not None
            providers.append(provider)
    assert providers[0] is not providers[1]
    with scoped(first_home):
        assert manager.get_or_build_provider("target", "https://same.example/mcp", {"cimd": False}) is providers[0]
    assert len(manager._entries) == 2
