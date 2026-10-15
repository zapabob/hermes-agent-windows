"""A retired OAuth response must never overwrite newer credentials."""
import asyncio
import json
import os
from pathlib import Path
import subprocess
import sys
import time
from types import SimpleNamespace

import httpx
import pytest
from mcp.shared.auth import OAuthToken

from tools.mcp_oauth import HermesTokenStorage
from tools.mcp_oauth_manager import HermesMCPOAuthProvider, MCPOAuthManager, _ProviderEntry
from tools.mcp_oauth_state import StaleOAuthCommitError


@pytest.mark.asyncio
@pytest.mark.parametrize("retirement", ["evict", "remove", "replace", "config_aba", "external", "external_same_bytes", "external_client", "external_metadata"])
async def test_retirement_after_parse_cannot_publish_old_login(tmp_path, monkeypatch, retirement):
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    monkeypatch.setattr("tools.mcp_dashboard_oauth.get_dashboard_oauth_flow", lambda: None)
    from utils import atomic_yaml_write
    config = {"mcp_servers": {"fixture": {"url": "https://mcp.example.invalid/mcp", "auth": "oauth"}}}
    atomic_yaml_write(tmp_path / "config.yaml", config)
    storage = HermesTokenStorage("fixture", hermes_home=tmp_path)
    old = OAuthToken(access_token="OLD_FIXTURE", token_type="Bearer")
    await storage.set_tokens(old)
    before = storage._tokens_path().read_bytes()
    provider = HermesMCPOAuthProvider.__new__(HermesMCPOAuthProvider)
    provider._initialized = True
    provider.context = SimpleNamespace(
        storage=storage, current_tokens=old, oauth_metadata=None,
        update_token_expiry=lambda token: None,
    )

    async def no_prefetch():
        return None

    async def authorization():
        return httpx.Request("POST", "https://auth.example.invalid/token")

    provider._prefetch_oauth_metadata = no_prefetch
    provider._perform_authorization = authorization
    manager = MCPOAuthManager()
    monkeypatch.setattr(manager, "_build_provider", lambda *_: provider)
    original_client = httpx.AsyncClient
    transport = httpx.MockTransport(lambda request: httpx.Response(
        200, json={"access_token": "STALE_FIXTURE", "token_type": "Bearer"}
    ))
    monkeypatch.setattr(httpx, "AsyncClient", lambda *, timeout: original_client(timeout=timeout, transport=transport))
    from mcp.client.auth import utils
    parse = utils.handle_token_response_scopes
    started, finish = asyncio.Event(), asyncio.Event()

    async def gated_parse(response):
        token = await parse(response)
        started.set()
        await finish.wait()
        return token

    monkeypatch.setattr(utils, "handle_token_response_scopes", gated_parse)
    task = asyncio.create_task(manager.force_login(
        "fixture", "https://mcp.example.invalid/mcp", {"client_id": "fixture"}
    ))
    try:
        await asyncio.wait_for(started.wait(), timeout=3)
        if retirement == "evict":
            manager.evict("fixture")
        elif retirement == "remove":
            manager.remove("fixture")
        elif retirement == "replace":
            replacement = SimpleNamespace(context=SimpleNamespace(storage=HermesTokenStorage("fixture", hermes_home=tmp_path)))
            monkeypatch.setattr(manager, "_build_provider", lambda *_: replacement)
            manager.get_or_build_provider("fixture", "https://new.example.invalid", {})
            await replacement.context.storage.set_tokens(OAuthToken(access_token="NEW_WRITER", token_type="Bearer"))
        else:
            # A genuine second Windows/Python process, with synthetic state only.
            script = '''import asyncio, sys
from pathlib import Path
from mcp.shared.auth import OAuthToken, OAuthClientInformationFull, OAuthMetadata
from tools.mcp_oauth import HermesTokenStorage
from utils import atomic_yaml_write
home=Path(sys.argv[1]); mode=sys.argv[2]
if mode == 'config_aba':
    a={'mcp_servers': {'fixture': {'url':'https://mcp.example.invalid/mcp', 'auth':'oauth'}}}
    b={'mcp_servers': {'fixture': {'url':'https://other.example.invalid/mcp', 'auth':'oauth'}}}
    atomic_yaml_write(home/'config.yaml', b)
    atomic_yaml_write(home/'config.yaml', a)
elif mode == 'external_client':
    asyncio.run(HermesTokenStorage('fixture', hermes_home=home).set_client_info(OAuthClientInformationFull(client_id='NEW_CLIENT', redirect_uris=['http://127.0.0.1/callback'])))
elif mode == 'external_metadata':
    HermesTokenStorage('fixture', hermes_home=home).save_oauth_metadata(OAuthMetadata(issuer='https://new.example.invalid', authorization_endpoint='https://new.example.invalid/authorize', token_endpoint='https://new.example.invalid/token', response_types_supported=['code']))
else:
    token='OLD_FIXTURE' if mode == 'external_same_bytes' else 'NEW_WRITER'
    asyncio.run(HermesTokenStorage('fixture', hermes_home=home).set_tokens(OAuthToken(access_token=token, token_type='Bearer')))
'''
            completed = subprocess.run([sys.executable, "-B", "-c", script, str(tmp_path), retirement], cwd=Path(__file__).resolve().parents[2], env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"}, capture_output=True, text=True, encoding="utf-8", timeout=20)
            assert completed.returncode == 0, completed.stderr
    finally:
        finish.set()
    assert await asyncio.wait_for(task, timeout=3) is False
    if retirement == "remove":
        assert not storage._tokens_path().exists()
    elif retirement in {"replace", "external"}:
        assert json.loads(storage._tokens_path().read_text(encoding="utf-8"))["access_token"] == "NEW_WRITER"
    else:
        assert storage._tokens_path().read_bytes() == before
    assert provider.context.current_tokens is old


@pytest.mark.asyncio
@pytest.mark.parametrize("retirement", ["evict", "remove", "replace", "restore", "restore_no_disk_change"])
@pytest.mark.parametrize("response_kind", ["success", "invalid", "failure"])
async def test_refresh_response_cannot_mutate_retired_context(tmp_path, monkeypatch, retirement, response_kind):
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    storage = HermesTokenStorage("fixture", hermes_home=tmp_path)
    old = OAuthToken(access_token="OLD", token_type="Bearer")
    await storage.set_tokens(old)
    provider = HermesMCPOAuthProvider.__new__(HermesMCPOAuthProvider)
    provider.context = SimpleNamespace(storage=storage, current_tokens=old, update_token_expiry=lambda _: None)
    provider.context.clear_tokens = lambda: setattr(provider.context, "current_tokens", None)
    manager = MCPOAuthManager()
    monkeypatch.setattr(manager, "_build_provider", lambda *_: provider)
    manager.get_or_build_provider("fixture", "https://mcp.example.invalid", {})
    key = manager._key("fixture")
    entry = manager._entries[key]
    entered, release = asyncio.Event(), asyncio.Event()
    response = httpx.Response(200, json={"access_token": "STALE", "token_type": "Bearer"})
    if response_kind == "invalid":
        response = httpx.Response(200, content=b"invalid token response")
    read = response.aread

    async def gated_read():
        entered.set()
        await release.wait()
        return await read()

    monkeypatch.setattr(response, "aread", gated_read)
    if response_kind == "failure":
        # Non-2xx handlers have no await: enter the immutable guard explicitly
        # before retirement, then let the real handler capture the retired epoch.
        response = httpx.Response(400)
        entered.set()
    task = None if response_kind == "failure" else asyncio.create_task(provider._handle_refresh_response(response))
    try:
        await asyncio.wait_for(entered.wait(), 3)
        if retirement == "evict":
            manager.evict("fixture")
        elif retirement == "replace":
            manager._entries[key] = _ProviderEntry("https://new.example.invalid", {})
        elif retirement == "remove":
            manager.remove("fixture")
        else:
            if retirement == "restore_no_disk_change":
                monkeypatch.setattr("tools.mcp_oauth.remove_oauth_tokens", lambda *_a, **_k: None)
            owner = SimpleNamespace(provider_settlement_identity=lambda: (None, None, False))
            manager.remove("fixture", removal_owner=owner)
            manager.restore_entry("fixture", entry, removal_owner=owner)
        expected = storage._tokens_path().read_bytes() if storage._tokens_path().exists() else None
    finally:
        release.set()
    if response_kind == "failure" and retirement == "restore_no_disk_change":
        assert await provider._handle_refresh_response(response) is False
        return
    with pytest.raises(StaleOAuthCommitError):
        if task is None:
            await provider._handle_refresh_response(response)
        else:
            await asyncio.wait_for(task, 3)
    assert provider.context.current_tokens is old
    assert (storage._tokens_path().read_bytes() if storage._tokens_path().exists() else None) == expected


def test_same_url_oauth_configuration_is_deep_copied_and_replaces_provider(tmp_path, monkeypatch):
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    manager = MCPOAuthManager()
    monkeypatch.setattr(manager, "_build_provider", lambda *_: SimpleNamespace())
    cfg = {"client_id": "A", "scope": ["read"]}
    first = manager.get_or_build_provider("fixture", "https://mcp.example.invalid", cfg)
    cfg["scope"].append("write")
    second = manager.get_or_build_provider("fixture", "https://mcp.example.invalid", cfg)
    assert second is not first


def test_saved_binding_rejects_aba_through_all_yaml_serializers(tmp_path):
    from tools.mcp_dashboard_oauth import SavedMcpConfigBinding, McpOAuthConfigChangedError
    from utils import atomic_yaml_write, atomic_roundtrip_yaml_update_multi, atomic_roundtrip_yaml_save
    path = tmp_path / "config.yaml"
    a = {"mcp_servers": {"fixture": {"url": "https://a.example.invalid", "auth": "oauth"}}}
    atomic_yaml_write(path, a)
    binding = SavedMcpConfigBinding.capture(str(tmp_path), "fixture")
    atomic_roundtrip_yaml_update_multi(path, {"mcp_servers.fixture.url": "https://b.example.invalid"})
    atomic_roundtrip_yaml_save(path, a)
    with pytest.raises(McpOAuthConfigChangedError):
        binding.assert_current()


def test_manager_construction_cannot_drift_to_another_home(tmp_path, monkeypatch):
    from tools import mcp_oauth
    a, b = tmp_path / "a", tmp_path / "b"
    monkeypatch.setenv("HERMES_HOME", str(a))
    monkeypatch.setattr(mcp_oauth, "_is_interactive", lambda: True)
    monkeypatch.setattr(mcp_oauth, "_configure_callback_port", lambda cfg, storage: cfg.update(_resolved_port=0))
    manager = MCPOAuthManager()
    build = manager._build_provider

    def changed_ambient(*args):
        monkeypatch.setenv("HERMES_HOME", str(b))
        return build(*args)

    monkeypatch.setattr(manager, "_build_provider", changed_ambient)
    provider = manager.get_or_build_provider("fixture", "https://mcp.example.invalid", {})
    assert provider.context.storage._tokens_path().is_relative_to(a)


@pytest.mark.asyncio
async def test_config_aba_rebuilds_cache_and_accepts_fresh_sdk_grant(tmp_path, monkeypatch):
    from tools import mcp_oauth
    from utils import atomic_yaml_write
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    monkeypatch.setattr(mcp_oauth, "_is_interactive", lambda: True)
    monkeypatch.setattr(mcp_oauth, "_configure_callback_port", lambda cfg, storage: cfg.update(_resolved_port=0))
    a = {"mcp_servers": {"fixture": {"url": "https://a.example.invalid", "auth": "oauth"}}}
    b = {"mcp_servers": {"fixture": {"url": "https://b.example.invalid", "auth": "oauth"}}}
    atomic_yaml_write(tmp_path / "config.yaml", a)
    manager = MCPOAuthManager()
    retired = manager.get_or_build_provider("fixture", "https://a.example.invalid", {})
    atomic_yaml_write(tmp_path / "config.yaml", b)
    atomic_yaml_write(tmp_path / "config.yaml", a)
    current = manager.get_or_build_provider("fixture", "https://a.example.invalid", {})
    assert current is not retired
    with pytest.raises(StaleOAuthCommitError):
        await retired._handle_token_response(httpx.Response(200, json={"access_token": "STALE", "token_type": "Bearer"}))
    await current._handle_token_response(httpx.Response(200, json={"access_token": "FRESH", "token_type": "Bearer"}))
    assert current.context.current_tokens.access_token == "FRESH"
    assert (await current.context.storage.get_tokens()).access_token == "FRESH"


@pytest.mark.windows_only
@pytest.mark.skipif(sys.platform != "win32", reason="Native Windows process and OS lock contract")
def test_native_two_process_writers_cannot_overwrite_winner(tmp_path):
    script = '''import asyncio, sys
from pathlib import Path
from mcp.shared.auth import OAuthToken
from tools.mcp_oauth import HermesTokenStorage
from tools.mcp_oauth_state import StaleOAuthCommitError
home=Path(sys.argv[1]); name=sys.argv[2]
storage=HermesTokenStorage('fixture', hermes_home=home)
(home/(name+'.ready')).write_text('ready', encoding='utf-8')
sys.stdin.readline()
try:
    asyncio.run(storage.set_tokens(OAuthToken(access_token=name, token_type='Bearer')))
except StaleOAuthCommitError:
    print('FENCED', flush=True)
else:
    print('WRITTEN', flush=True)
'''
    processes = []
    try:
        for name in ("winner", "stale"):
            processes.append(subprocess.Popen([sys.executable, "-B", "-c", script, str(tmp_path), name], cwd=Path(__file__).resolve().parents[2], env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"}, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, encoding="utf-8"))
        deadline = time.monotonic() + 20
        while not all((tmp_path / (name + ".ready")).exists() for name in ("winner", "stale")):
            assert all(process.poll() is None for process in processes)
            assert time.monotonic() < deadline, "native writers failed to reach barrier"
            time.sleep(0.01)
        output, error = processes[0].communicate("commit\n", timeout=20)
        assert processes[0].returncode == 0 and output.strip() == "WRITTEN", error
        output, error = processes[1].communicate("commit\n", timeout=20)
        assert processes[1].returncode == 0 and output.strip() == "FENCED", error
        assert json.loads((tmp_path / "mcp-tokens/fixture.json").read_text(encoding="utf-8"))["access_token"] == "winner"
    finally:
        for process in processes:
            if process.poll() is None:
                process.terminate()
                process.communicate(timeout=10)
