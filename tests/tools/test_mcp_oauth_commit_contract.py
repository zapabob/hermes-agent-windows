"""Token persistence must succeed before a provider publishes new credentials."""

import asyncio
import json
import sys
from types import SimpleNamespace

import httpx
import pytest
from mcp.shared.auth import OAuthToken

from tools import mcp_oauth
from tools.mcp_oauth_manager import HermesMCPOAuthProvider
from tools.mcp_oauth_provider import HermesProviderMixin


def _provider(kind: str, context):
    classes = {
        "manager": HermesMCPOAuthProvider,
        "legacy": mcp_oauth._get_hermes_oauth_provider_class(),
        "shared": HermesProviderMixin,
    }
    provider = classes[kind].__new__(classes[kind])
    provider.context = context
    return provider


@pytest.mark.parametrize("kind", ["manager", "legacy", "shared"])
@pytest.mark.parametrize("response_kind", ["exchange", "refresh"])
@pytest.mark.parametrize("winerror", [5, 32, 33])
@pytest.mark.asyncio
async def test_failed_atomic_replace_does_not_publish_credentials(
    tmp_path, monkeypatch, kind, response_kind, winerror
):
    storage = mcp_oauth.HermesTokenStorage("fixture", hermes_home=tmp_path)
    old = OAuthToken(access_token="OLD_FIXTURE", token_type="Bearer")
    await storage.set_tokens(old)
    path = storage._tokens_path()
    before = path.read_bytes()
    storage.loaded_issuer = "https://old.example.invalid"
    storage.bind_issuer("https://new.example.invalid")
    published = []
    context = SimpleNamespace(
        storage=storage,
        current_tokens=old,
        oauth_metadata=None,
        update_token_expiry=lambda token: published.append(token),
    )
    provider = _provider(kind, context)

    def deny_replace(source, destination):
        error = PermissionError("synthetic Windows sharing/access failure")
        error.winerror = winerror
        raise error

    monkeypatch.setattr(mcp_oauth.os, "replace", deny_replace)
    response = httpx.Response(
        200, json={"access_token": "NEW_FIXTURE", "token_type": "Bearer"}
    )
    handler = (
        provider._handle_token_response
        if response_kind == "exchange"
        else provider._handle_refresh_response
    )
    with pytest.raises(PermissionError):
        await handler(response)

    assert path.read_bytes() == before
    assert list(path.parent.iterdir()) == [path]
    assert context.current_tokens is old
    assert published == []
    assert storage.loaded_issuer == "https://old.example.invalid"


@pytest.mark.parametrize("kind", ["manager", "legacy", "shared"])
@pytest.mark.parametrize("response_kind", ["exchange", "refresh"])
@pytest.mark.asyncio
async def test_successful_response_persists_before_memory_publication(
    tmp_path, kind, response_kind
):
    storage = mcp_oauth.HermesTokenStorage("fixture", hermes_home=tmp_path)
    effects = []

    def publish_expiry(token):
        saved = json.loads(storage._tokens_path().read_text(encoding="utf-8"))
        assert saved["access_token"] == token.access_token
        effects.append("published_after_persistence")

    context = SimpleNamespace(
        storage=storage,
        current_tokens=None,
        oauth_metadata=None,
        update_token_expiry=publish_expiry,
    )
    provider = _provider(kind, context)
    response = httpx.Response(
        201,
        json={
            "access_token": "NEW_FIXTURE",
            "token_type": "Bearer",
            "expires_in": 3600,
        },
    )
    if response_kind == "exchange":
        await provider._handle_token_response(response)
    else:
        assert await provider._handle_refresh_response(response) is True
    assert context.current_tokens.access_token == "NEW_FIXTURE"
    assert effects == ["published_after_persistence"]


@pytest.mark.parametrize("kind", ["manager", "legacy", "shared"])
@pytest.mark.parametrize("response_kind", ["exchange", "refresh"])
@pytest.mark.asyncio
async def test_cancelled_storage_does_not_publish_credentials(
    tmp_path, monkeypatch, kind, response_kind
):
    storage = mcp_oauth.HermesTokenStorage("fixture", hermes_home=tmp_path)
    old = OAuthToken(access_token="OLD_FIXTURE", token_type="Bearer")
    await storage.set_tokens(old)
    before = storage._tokens_path().read_bytes()
    started = asyncio.Event()
    published = []

    async def blocked_store(token):
        started.set()
        await asyncio.Event().wait()

    monkeypatch.setattr(storage, "set_tokens", blocked_store)
    context = SimpleNamespace(
        storage=storage,
        current_tokens=old,
        oauth_metadata=None,
        update_token_expiry=lambda token: published.append(token),
    )
    provider = _provider(kind, context)
    response = httpx.Response(
        200, json={"access_token": "NEW_FIXTURE", "token_type": "Bearer"}
    )
    handler = (
        provider._handle_token_response
        if response_kind == "exchange"
        else provider._handle_refresh_response
    )
    task = asyncio.create_task(handler(response))
    try:
        await asyncio.wait_for(started.wait(), timeout=3)
    finally:
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
    assert storage._tokens_path().read_bytes() == before
    assert context.current_tokens is old
    assert published == []


@pytest.mark.skipif(
    sys.platform != "win32", reason="Native NTFS sharing-handle contract"
)
@pytest.mark.windows_only
@pytest.mark.parametrize("kind", ["manager", "legacy", "shared"])
@pytest.mark.parametrize("response_kind", ["exchange", "refresh"])
@pytest.mark.asyncio
async def test_native_locked_token_file_preserves_disk_and_memory(
    tmp_path, kind, response_kind
):
    import ctypes
    from ctypes import wintypes

    storage = mcp_oauth.HermesTokenStorage("fixture", hermes_home=tmp_path)
    old = OAuthToken(access_token="OLD_FIXTURE", token_type="Bearer")
    await storage.set_tokens(old)
    path = storage._tokens_path()
    before = path.read_bytes()
    published = []
    context = SimpleNamespace(
        storage=storage,
        current_tokens=old,
        oauth_metadata=None,
        update_token_expiry=lambda token: published.append(token),
    )
    provider = _provider(kind, context)
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.CreateFileW.argtypes = [
        wintypes.LPCWSTR,
        wintypes.DWORD,
        wintypes.DWORD,
        wintypes.LPVOID,
        wintypes.DWORD,
        wintypes.DWORD,
        wintypes.HANDLE,
    ]
    kernel.CreateFileW.restype = wintypes.HANDLE
    kernel.CloseHandle.argtypes = [wintypes.HANDLE]
    kernel.CloseHandle.restype = wintypes.BOOL
    # A real reader permits other readers/writers, but denies replacement.
    handle = kernel.CreateFileW(str(path), 0x80000000, 3, None, 3, 0x80, None)
    assert handle != wintypes.HANDLE(-1).value, ctypes.get_last_error()
    response = httpx.Response(
        200, json={"access_token": "NEW_FIXTURE", "token_type": "Bearer"}
    )
    handler = (
        provider._handle_token_response
        if response_kind == "exchange"
        else provider._handle_refresh_response
    )
    try:
        with pytest.raises(PermissionError) as caught:
            await handler(response)
        assert caught.value.winerror in (5, 32, 33)
        assert path.read_bytes() == before
        assert list(path.parent.iterdir()) == [path]
        assert context.current_tokens is old
        assert published == []
    finally:
        assert kernel.CloseHandle(handle), ctypes.get_last_error()


@pytest.mark.parametrize("kind", ["manager", "legacy", "shared"])
@pytest.mark.parametrize("response_kind", ["exchange", "refresh"])
@pytest.mark.parametrize("expires_in", [0, 60, None])
@pytest.mark.asyncio
async def test_storage_latency_does_not_extend_sdk_token_expiry(
    tmp_path, monkeypatch, kind, response_kind, expires_in
):
    from mcp.client.auth import oauth2
    from mcp.shared import auth_utils
    from mcp.shared.auth import OAuthClientMetadata
    from tools import mcp_oauth_provider

    clock = [100.0]
    fake_clock = SimpleNamespace(time=lambda: clock[0])
    monkeypatch.setattr(auth_utils, "time", fake_clock)
    monkeypatch.setattr(mcp_oauth, "time", fake_clock)
    monkeypatch.setattr(mcp_oauth_provider, "time", fake_clock, raising=False)
    storage = mcp_oauth.HermesTokenStorage("fixture", hermes_home=tmp_path)
    original_set = storage.set_tokens

    async def slow_storage(token):
        await original_set(token)
        clock[0] += 5.0

    monkeypatch.setattr(storage, "set_tokens", slow_storage)
    context = oauth2.OAuthContext(
        server_url="https://mcp.example.invalid",
        client_metadata=OAuthClientMetadata(
            redirect_uris=["http://127.0.0.1/callback"]
        ),
        storage=storage,
        redirect_handler=None,
        callback_handler=None,
    )
    provider = _provider(kind, context)
    response = httpx.Response(
        200,
        json={
            "access_token": "NEW_FIXTURE",
            "token_type": "Bearer",
            "expires_in": expires_in,
        },
    )
    handler = (
        provider._handle_token_response
        if response_kind == "exchange"
        else provider._handle_refresh_response
    )
    await handler(response)
    expected = None if expires_in is None else 100.0 + expires_in
    assert context.token_expiry_time == expected
    saved = json.loads(storage._tokens_path().read_text(encoding="utf-8"))
    assert saved.get("expires_at") == expected


@pytest.mark.parametrize("kind", ["manager", "legacy", "shared"])
@pytest.mark.parametrize("response_kind", ["exchange", "refresh"])
@pytest.mark.asyncio
async def test_saved_config_rejection_preserves_credentials_and_expiry(
    tmp_path, kind, response_kind
):
    from mcp.client.auth.oauth2 import OAuthContext
    from mcp.shared.auth import OAuthClientMetadata
    from tools.mcp_dashboard_oauth import (
        McpOAuthConfigChangedError,
        SavedMcpConfigBinding,
    )

    config = tmp_path / "config.yaml"
    config.write_text(
        "mcp_servers:\n  fixture:\n    url: https://old.example.invalid\n    auth: oauth\n",
        encoding="utf-8",
    )
    storage = mcp_oauth.HermesTokenStorage("fixture", hermes_home=tmp_path)
    old = OAuthToken(access_token="OLD_FIXTURE", token_type="Bearer")
    await storage.set_tokens(old)
    before = storage._tokens_path().read_bytes()
    storage = mcp_oauth.HermesTokenStorage(
        "fixture",
        hermes_home=tmp_path,
        binding=SavedMcpConfigBinding.capture(str(tmp_path), "fixture"),
    )
    storage.loaded_issuer = "https://old.example.invalid"
    storage.bind_issuer("https://new.example.invalid")
    context = OAuthContext(
        server_url="https://old.example.invalid",
        client_metadata=OAuthClientMetadata(
            redirect_uris=["http://127.0.0.1/callback"]
        ),
        storage=storage,
        redirect_handler=None,
        callback_handler=None,
        current_tokens=old,
        token_expiry_time=50.0,
    )
    provider = _provider(kind, context)
    config.write_text(
        "mcp_servers:\n  fixture:\n    url: https://changed.example.invalid\n    auth: oauth\n",
        encoding="utf-8",
    )
    response = httpx.Response(
        200,
        json={"access_token": "NEW_FIXTURE", "token_type": "Bearer", "expires_in": 60},
    )
    handler = (
        provider._handle_token_response
        if response_kind == "exchange"
        else provider._handle_refresh_response
    )
    with pytest.raises(McpOAuthConfigChangedError):
        await handler(response)
    assert storage._tokens_path().read_bytes() == before
    assert context.current_tokens is old
    assert context.token_expiry_time == 50.0
    assert storage.loaded_issuer == "https://old.example.invalid"
