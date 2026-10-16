"""Real SDK generator, issuer maintenance and disaster-recovery fencing."""
import asyncio
import json
import os
import subprocess
import sys
import time
from pathlib import Path
from types import SimpleNamespace
import zipfile

import httpx
import pytest
from mcp.shared.auth import OAuthToken, OAuthMetadata, OAuthClientMetadata, OAuthClientInformationFull

from tools.mcp_oauth import HermesTokenStorage
from tools.mcp_oauth_manager import HermesMCPOAuthProvider, MCPOAuthManager
from tools.mcp_oauth_state import StaleOAuthCommitError
from tools.mcp_dashboard_oauth import SavedMcpConfigBinding, McpOAuthConfigChangedError
from utils import atomic_yaml_write


@pytest.mark.asyncio
async def test_sdk_inflight_refresh_cannot_reacquire_restored_identity(tmp_path, monkeypatch):
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    storage = HermesTokenStorage("fixture", hermes_home=tmp_path)
    storage.bind_issuer("https://issuer.example.invalid")
    await storage.set_tokens(OAuthToken(access_token="OLD", refresh_token="REFRESH", token_type="Bearer", expires_in=0))
    await storage.set_client_info(OAuthClientInformationFull(client_id="fixture", redirect_uris=["http://127.0.0.1/callback"]))
    provider = HermesMCPOAuthProvider(server_name="fixture", preregistered=True, server_url="https://mcp.example.invalid", client_metadata=OAuthClientMetadata(redirect_uris=["http://127.0.0.1/callback"]), storage=storage)
    provider.context.oauth_metadata = OAuthMetadata(issuer="https://issuer.example.invalid", authorization_endpoint="https://issuer.example.invalid/authorize", token_endpoint="https://issuer.example.invalid/token", response_types_supported=["code"])
    storage.save_oauth_metadata(provider.context.oauth_metadata)

    async def request():
        return httpx.Request("POST", "https://issuer.example.invalid/token")

    provider._refresh_token = request
    provider._perform_authorization = request
    manager = MCPOAuthManager()
    monkeypatch.setattr(manager, "_build_provider", lambda *_: provider)
    monkeypatch.setattr("tools.mcp_oauth_manager.get_manager", lambda: manager)
    manager.get_or_build_provider("fixture", "https://mcp.example.invalid", {})
    entry = manager._entries[manager._key("fixture")]
    flow = provider.async_auth_flow(httpx.Request("GET", "https://mcp.example.invalid"))
    try:
        async with asyncio.timeout(10):
            outgoing = await flow.__anext__()
            assert str(outgoing.url) == "https://issuer.example.invalid/token"
            snapshot = storage.snapshot()
            owner = SimpleNamespace(provider_settlement_identity=lambda: (None, None, False))
            assert manager.remove("fixture", removal_owner=owner) is entry
            HermesTokenStorage("fixture", hermes_home=tmp_path).restore(snapshot)
            manager.restore_entry("fixture", entry, removal_owner=owner)
            assert await manager.invalidate_if_disk_changed("fixture")
            real_client = httpx.AsyncClient
            transport = httpx.MockTransport(lambda _: httpx.Response(200, json={"access_token": "NEW_WINNER", "token_type": "Bearer"}))
            monkeypatch.setattr(httpx, "AsyncClient", lambda *, timeout: real_client(timeout=timeout, transport=transport))
            assert await manager.force_login("fixture", "https://mcp.example.invalid", {})
            with pytest.raises(StaleOAuthCommitError):
                await flow.asend(httpx.Response(200, json={"access_token": "STALE_RESPONSE", "token_type": "Bearer"}))
            assert provider.context.current_tokens.access_token == "NEW_WINNER"
            assert (await storage.get_tokens()).access_token == "NEW_WINNER"
            assert not provider.context.lock.locked(), "revoked generator must release its SDK lock"
    finally:
        await flow.aclose()


@pytest.mark.asyncio
@pytest.mark.parametrize("recorded_issuer", [None, "https://old.example.invalid"])
async def test_issuer_maintenance_preserves_next_valid_refresh(tmp_path, recorded_issuer):
    from tools.mcp_oauth_provider import enforce_refresh_token_issuer
    storage = HermesTokenStorage("fixture", hermes_home=tmp_path)
    payload = {"access_token": "OLD", "refresh_token": "REFRESH", "token_type": "Bearer"}
    if recorded_issuer:
        payload["hermes_issuer"] = recorded_issuer
    storage._tokens_path().parent.mkdir(parents=True, exist_ok=True)
    storage._tokens_path().write_text(json.dumps(payload), encoding="utf-8")
    context = SimpleNamespace(storage=storage, current_tokens=await storage.get_tokens(), oauth_metadata=SimpleNamespace(issuer="https://new.example.invalid"), update_token_expiry=lambda _: None)
    enforce_refresh_token_issuer(context)
    provider = HermesMCPOAuthProvider.__new__(HermesMCPOAuthProvider)
    provider.context = context
    assert await provider._handle_refresh_response(httpx.Response(200, json={"access_token": "VALID", "token_type": "Bearer"}))
    assert context.current_tokens.access_token == "VALID"


def test_archive_cannot_restore_generation_journal_or_lock(tmp_path):
    from hermes_cli import backup
    a = {"mcp_servers": {"fixture": {"url": "https://a.example.invalid", "auth": "oauth"}}}
    b = {"mcp_servers": {"fixture": {"url": "https://b.example.invalid", "auth": "oauth"}}}
    atomic_yaml_write(tmp_path / "config.yaml", a)
    binding = SavedMcpConfigBinding.capture(str(tmp_path), "fixture")
    journal = tmp_path / ".mcp-oauth-state/generations.json"
    archived = journal.read_bytes()
    atomic_yaml_write(tmp_path / "config.yaml", b)
    atomic_yaml_write(tmp_path / "config.yaml", a)
    current = journal.read_bytes()
    archive = tmp_path / "old.zip"
    with zipfile.ZipFile(archive, "w") as stream:
        stream.writestr(".mcp-oauth-state/generations.json", archived)
        stream.writestr(".mcp-oauth-state/lock", b"REPLACED_LOCK")
    with zipfile.ZipFile(archive) as stream:
        for member in stream.namelist():
            assert backup._should_exclude(Path(member))
            backup._extract_member_atomically(stream, member, tmp_path / member)
    assert journal.read_bytes() == current
    assert (tmp_path / ".mcp-oauth-state/lock").read_bytes() != b"REPLACED_LOCK"
    with pytest.raises(McpOAuthConfigChangedError):
        binding.assert_current()


def test_quick_snapshot_repairs_malformed_config(tmp_path):
    from hermes_cli import backup
    snapshot = tmp_path / "state-snapshots/fixture"
    snapshot.mkdir(parents=True)
    (tmp_path / "config.yaml").write_text("mcp_servers: [\n", encoding="utf-8")
    (snapshot / "config.yaml").write_text("mcp_servers: {}\n", encoding="utf-8")
    (snapshot / "manifest.json").write_text(json.dumps({"files": {"config.yaml": (snapshot / "config.yaml").stat().st_size}}), encoding="utf-8")
    assert backup.restore_quick_snapshot("fixture", hermes_home=tmp_path)
    assert (tmp_path / "config.yaml").read_text(encoding="utf-8") == "mcp_servers: {}\n"


@pytest.mark.windows_only
@pytest.mark.skipif(sys.platform != "win32", reason="Native Windows filename identity")
def test_windows_config_case_alias_cannot_revive_aba_binding(tmp_path):
    a = {"mcp_servers": {"fixture": {"url": "https://a.example.invalid", "auth": "oauth"}}}
    b = {"mcp_servers": {"fixture": {"url": "https://b.example.invalid", "auth": "oauth"}}}
    atomic_yaml_write(tmp_path / "config.yaml", a)
    binding = SavedMcpConfigBinding.capture(str(tmp_path), "fixture")
    atomic_yaml_write(tmp_path / "CONFIG.YAML", b)
    atomic_yaml_write(tmp_path / "CONFIG.YAML", a)
    assert (tmp_path / "config.yaml").samefile(tmp_path / "CONFIG.YAML")
    with pytest.raises(McpOAuthConfigChangedError):
        binding.assert_current()


@pytest.mark.asyncio
async def test_imported_credentials_fence_pending_writer(tmp_path):
    from hermes_cli import backup
    storage = HermesTokenStorage("fixture", hermes_home=tmp_path)
    await storage.set_tokens(OAuthToken(access_token="OLD", token_type="Bearer"))
    path = storage._tokens_path()
    archive = tmp_path / "credentials.zip"
    with zipfile.ZipFile(archive, "w") as stream:
        stream.writestr("mcp-tokens/fixture.json", json.dumps({"access_token": "RESTORED", "token_type": "Bearer"}))
    with zipfile.ZipFile(archive) as stream:
        backup._extract_member_atomically(stream, "mcp-tokens/fixture.json", path)
    with pytest.raises(StaleOAuthCommitError):
        await storage.set_tokens(OAuthToken(access_token="STALE", token_type="Bearer"))
    assert json.loads(path.read_text(encoding="utf-8"))["access_token"] == "RESTORED"


@pytest.mark.windows_only
@pytest.mark.skipif(sys.platform != "win32", reason="Real Windows byte-range lock contention")
def test_native_contending_writer_rechecks_cas_after_os_lock(tmp_path):
    from tools.mcp_oauth_state import oauth_state_lock
    storage = HermesTokenStorage("fixture", hermes_home=tmp_path)
    asyncio.run(storage.set_tokens(OAuthToken(access_token="INITIAL", token_type="Bearer")))
    script = '''import asyncio, sys, msvcrt
from pathlib import Path
from mcp.shared.auth import OAuthToken
from tools.mcp_oauth import HermesTokenStorage
from tools.mcp_oauth_state import StaleOAuthCommitError
home=Path(sys.argv[1]); storage=HermesTokenStorage('fixture', hermes_home=home)
original=msvcrt.locking
def observed(fd, mode, count):
    try:
        return original(fd, mode, count)
    except OSError:
        if mode == msvcrt.LK_NBLCK:
            (home/'native-blocked').write_text('real OS contention', encoding='utf-8')
        raise
msvcrt.locking=observed
(home/'ready').write_text('ready', encoding='utf-8')
sys.stdin.readline()
try:
    asyncio.run(storage.set_tokens(OAuthToken(access_token='STALE', token_type='Bearer')))
except StaleOAuthCommitError:
    print('FENCED', flush=True)
else:
    raise AssertionError('stale native writer committed')
'''
    process = subprocess.Popen([sys.executable, "-B", "-c", script, str(tmp_path)], cwd=Path(__file__).resolve().parents[2], env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"}, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, encoding="utf-8")

    def wait_for(path):
        deadline = time.monotonic() + 15
        while not path.exists():
            assert process.poll() is None
            assert time.monotonic() < deadline, "native process did not reach lock barrier"
            time.sleep(0.01)

    try:
        wait_for(tmp_path / "ready")
        with oauth_state_lock(tmp_path):
            process.stdin.write("commit\n")
            process.stdin.flush()
            wait_for(tmp_path / "native-blocked")
            asyncio.run(storage.set_tokens(OAuthToken(access_token="WINNER", token_type="Bearer")))
        output, error = process.communicate(timeout=20)
        assert process.returncode == 0 and output.strip() == "FENCED", error
        assert (asyncio.run(storage.get_tokens())).access_token == "WINNER"
    finally:
        if process.poll() is None:
            process.terminate()
            process.communicate(timeout=10)
