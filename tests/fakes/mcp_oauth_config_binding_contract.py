"""Actual SDK saved-connection authority across RPC, loopback and REST."""
from contextlib import contextmanager
from dataclasses import dataclass
import json
import threading
from urllib.error import HTTPError
from urllib.parse import urlencode
from urllib.request import urlopen

import pytest

from tests.fakes.mcp_oauth_issuer import serve_issuer
from tests.fakes.mcp_oauth_gateway import (
    finish, homes as homes, registry_effect, rpc, running_flow, scoped,
)
from tests.hermes_cli.test_mcp_oauth_rest_sdk_contract import (
    running_rest, settled, without_dashboard_cookie,
)


SURFACES = ("native", "relay", "rest")
CHANGES = ("replace", "remove", "rename", "disable")



@pytest.fixture(autouse=True)
def owned_protocol_evidence(request, monkeypatch):
    """Retain observed peer ledger and acquired thread settlement in JUnit."""
    original = serve_issuer

    @contextmanager
    def observed_peer(*args, **kwargs):
        owner = None
        try:
            with original(*args, **kwargs) as acquired:
                owner = acquired
                yield acquired
        finally:
            if owner is not None:
                with owner.lock:
                    ledger = [dict(row) for row in owner.ledger]
                    threads = [
                        {"name": thread.name, "ident": thread.ident, "alive": thread.is_alive()}
                        for thread in owner.request_threads
                    ]
                request.node.user_properties.append(("owned_loopback_peer", json.dumps({
                    "base": owner.base, "issuer": owner.issuer, "ledger": ledger,
                    "request_threads_after_peer_exit": threads,
                    "scope": "Actual owned synthetic loopback peer only; no external server/UI/login claim",
                }, ensure_ascii=False)))

    monkeypatch.setitem(globals(), "serve_issuer", observed_peer)


@dataclass
class ActualFlow:
    surface: str
    identity: str
    authorization_url: str
    bridge: object
    callback: object
    settle: object
    poll: object
    restart: object = None
    client: object = None


def start_actual(surface, owner, root, acquired, client=None):
    from tools import mcp_tool as core
    from tui_gateway import mcp_oauth_sessions as sessions
    from hermes_cli import web_server

    before = set(threading.enumerate())
    if surface == "rest":
        started = client.post("/api/mcp/servers/reports/auth?profile=work")
        assert started.status_code == 200, started.text
        data = started.json()
        bridge = web_server._mcp_oauth_flows[data["flow_id"]]
        identity, authorization_url = bridge.flow_id, data["authorization_url"]
        loops = acquired[-1]
    else:
        params = {"client_redirect_uri": "http://127.0.0.1:18889/callback"} if surface == "relay" else {}
        data = rpc("start", **params)
        assert data["ok"], data
        identity, authorization_url = data["session_id"], data["auth_url"]
        rec = sessions._sessions[identity]
        bridge, loops = rec["flow"], acquired[-1]
    workers = [
        thread for thread in threading.enumerate()
        if thread not in before and thread.name == "mcp-oauth-reports"
    ]
    assert len(workers) == 1
    worker = workers[0]
    if core._mcp_loop is not None:
        loops.append((core._mcp_loop, core._mcp_thread))
    assert owner.operations("registration") and owner.operations("get")

    if surface == "rest":
        def send(code, state):
            params = {"code": code, "state": state, "iss": owner.issuer, "profile": "other"}
            with without_dashboard_cookie(client):
                response = client.get("/api/mcp/oauth/callback/reports?" + urlencode(params))
            assert response.status_code in (200, 400, 404, 409), response.text
            return response.status_code == 200

        with without_dashboard_cookie(client):
            path = f"/api/mcp/oauth/flows/{identity}?profile=work"
            assert client.get(path).status_code == 401
            assert client.delete(path).status_code == 401
        return ActualFlow(
            surface, identity, authorization_url, bridge, send,
            lambda: settled(bridge, worker, loops),
            lambda: client.get(f"/api/mcp/oauth/flows/{identity}?profile=work").json(),
        )

    listeners = [
        thread for thread in threading.enumerate()
        if thread not in before and thread.name == "mcp-oauth-cb-reports"
    ]
    if surface == "native":
        assert len(listeners) == 1
        port = rec["httpd"].server_address[1]

        def settle():
            finish(rec, worker, listeners[0], port)

        def send(code, state):
            url = bridge.redirect_uri + "?" + urlencode(
                {"code": code, "state": state, "iss": owner.issuer}
            )
            try:
                with urlopen(url, timeout=3) as response:
                    assert response.status == 200
                    response.read()
                    return True
            except HTTPError as rejected:
                try:
                    assert rejected.code == 400
                    rejected.read()
                    return False
                finally:
                    rejected.close()
    else:
        assert not listeners
        assert rec["httpd"] is None

        def settle():
            assert bridge._worker_done.wait(12), bridge.snapshot()
            worker.join(timeout=3)
            assert not worker.is_alive()
            assert rec["httpd"] is None

        def send(code, state):
            result = rpc("callback", session_id=identity, code=code, state=state, iss=owner.issuer)
            assert isinstance(result["ok"], bool), result
            return result["ok"]

    return ActualFlow(
        surface, identity, authorization_url, bridge, send, settle,
        lambda: rpc("poll", session_id=identity),
    )


@contextmanager
def running(surface, owner, root, monkeypatch, *, initial=None):
    fixture = (
        running_rest(owner, root, monkeypatch, manual_start=True)
        if surface == "rest" else running_flow(owner, root, manual_start=True)
    )
    with fixture as acquired:
        client = acquired[0] if surface == "rest" else None
        if initial == "implicit":
            mapping = saved_servers(root)
            mapping["reports"].pop("auth")
            mapping["reports"]["env"] = {"OWNED_LABEL": "${OWNED_LABEL}"}
            replace_servers(root, mapping)
        actual = start_actual(surface, owner, root, acquired, client)
        actual.restart = lambda replacement: start_actual(surface, replacement, root, acquired, client)
        actual.client = client
        yield actual


def config_bytes(root, profile="work"):
    from hermes_cli.config import get_config_path

    with scoped(root / "profiles" / profile):
        return get_config_path().read_bytes()


def saved_servers(root, profile="work"):
    from hermes_cli.mcp_config import _get_mcp_servers

    with scoped(root / "profiles" / profile):
        return _get_mcp_servers()


def replace_servers(root, servers, profile="work"):
    from hermes_cli.mcp_config import _replace_mcp_servers

    with scoped(root / "profiles" / profile):
        ok, issues = _replace_mcp_servers(servers)
        assert ok and not issues, issues


def change_connection(root, foreign, change):
    cfg = saved_servers(root)["reports"]
    if change == "replace":
        cfg["url"] = foreign.mcp_url
        replacement = {"reports": cfg}
    elif change == "remove":
        replacement = {}
    elif change == "rename":
        replacement = {"renamed": cfg}
    else:
        assert change == "disable"
        cfg["enabled"] = False
        replacement = {"reports": cfg}
    replace_servers(root, replacement)
    assert saved_servers(root) == replacement
    return config_bytes(root)


def tokens(root, profile="work"):
    return root / "profiles" / profile / "mcp-tokens" / "reports.json"


def assert_foreign_absent(foreign, root):
    assert foreign.operations("get") == []
    assert foreign.operations("registration") == []
    assert foreign.operations("token_request") == []
    assert foreign.operations("mcp_request") == []
    assert foreign.operations("sentinel") == []
    assert not tokens(root, "other").exists()


def assert_stale_settled(actual, root, changed):
    actual.settle()
    status = actual.poll()
    assert status["status"] == "error", status
    message = status.get("error_message") or status.get("error") or ""
    assert "configuration changed" in message.lower(), status
    assert actual.bridge.worker_done
    assert config_bytes(root) == changed, "Old OAuth flow overwrote the newer saved configuration"
    assert not actual.bridge.tools


@pytest.mark.parametrize("change", CHANGES)
@pytest.mark.parametrize("boundary", ("callback", "token-response"))
def test_changed_connection_cannot_adopt_actual_grant(homes, monkeypatch, request, surface, change, boundary):
    from tools.mcp_oauth import HermesTokenStorage

    persistence = []
    original = HermesTokenStorage.set_tokens

    async def observe_real_write(storage, token):
        attempt = {"returned": False, "exception": None}
        persistence.append(attempt)
        try:
            await original(storage, token)
        except Exception as exc:
            attempt["exception"] = str(exc)
            raise
        else:
            attempt["returned"] = True
        finally:
            try:
                observed_bytes = storage._tokens_path().read_bytes()
            except FileNotFoundError:
                observed_bytes = None
            attempt["file_exists_after_original"] = observed_bytes is not None
            attempt["complete_bytes_after_original_hex"] = (
                observed_bytes.hex() if observed_bytes is not None else None
            )
            request.node.user_properties.append(("actual_token_persistence_attempt", json.dumps(attempt)))

    monkeypatch.setattr(HermesTokenStorage, "set_tokens", observe_real_write)
    with serve_issuer() as owner, serve_issuer() as foreign:
        foreign.token = "different-owned-peer-token"
        if boundary == "token-response":
            owner.token_release.clear()
        with running(surface, owner, homes, monkeypatch) as actual:
            code, state, _ = owner.issue_code(actual.authorization_url)
            try:
                if boundary == "token-response":
                    assert actual.callback(code, state)
                    assert owner.token_started.wait(5)
                    assert owner.operations("token_redemption") == []
                changed = change_connection(homes, foreign, change)
                if boundary == "callback":
                    assert actual.callback(code, state) is False, "Stale saved connection admitted a callback"
                    assert actual.bridge._callback is None
            finally:
                owner.token_release.set()
            assert_stale_settled(actual, homes, changed)
            assert not tokens(homes).exists(), "Old target grant persisted under a replacement server identity"
            if boundary == "callback":
                assert owner.operations("token_request") == []
                assert persistence == []
            else:
                assert len(owner.operations("token_request")) == 1
                assert len(owner.operations("token_redemption")) == 1
                # The operation lease now rejects this response at the SDK
                # boundary, before the real setter may even attempt a save.
                assert persistence == [], "Retired grant reached the storage setter"
            assert owner.operations("sentinel") == []
            assert_foreign_absent(foreign, homes)


@pytest.mark.parametrize("newer_state", ("none", "different", "same"))
def test_changed_after_actual_token_write_discards_only_owned_bytes(
    homes, monkeypatch, surface, newer_state,
):
    import asyncio
    from mcp.shared.auth import OAuthToken
    from tools import mcp_oauth
    from tools.mcp_oauth import HermesTokenStorage
    from tools.mcp_oauth_manager import get_manager
    from tools.mcp_dashboard_oauth import get_dashboard_oauth_flow

    written, release = threading.Event(), threading.Event()
    original = HermesTokenStorage.set_tokens

    async def after_real_write(storage, token):
        await original(storage, token)
        if getattr(token, "access_token", None) == owner.token and get_dashboard_oauth_flow() is not None:
            written.set()
            assert release.wait(12), "Owned actual persistence barrier timed out"

    monkeypatch.setattr(HermesTokenStorage, "set_tokens", after_real_write)
    with serve_issuer() as owner, serve_issuer() as foreign:
        foreign.token = "different-owned-peer-token"
        with running(surface, owner, homes, monkeypatch) as actual:
            code, state, _ = owner.issue_code(actual.authorization_url)
            try:
                assert actual.callback(code, state)
                assert written.wait(5)
                assert json.loads(tokens(homes).read_text(encoding="utf-8"))["access_token"] == owner.token
                assert len(owner.operations("token_redemption")) == 1
                changed = change_connection(homes, foreign, "replace")
                marker, replacement_provider = None, None
                if newer_state != "none":
                    old_bytes = tokens(homes).read_bytes()
                    old_data = json.loads(old_bytes)
                    with scoped(homes / "profiles" / "work"):
                        assert get_dashboard_oauth_flow() is None
                        competing = HermesTokenStorage("reports")
                        if newer_state == "same":
                            competing.bind_issuer(old_data.get("hermes_issuer"))
                            value = OAuthToken.model_validate({
                                key: val for key, val in old_data.items()
                                if key not in {"hermes_issuer", "expires_at"}
                            })
                            fixed_clock = old_data["expires_at"] - old_data["expires_in"]
                            with monkeypatch.context() as clock:
                                clock.setattr(mcp_oauth.time, "time", lambda: fixed_clock)
                                asyncio.run(competing.set_tokens(value))
                        else:
                            value = OAuthToken(
                                access_token=foreign.token, token_type="Bearer", expires_in=3600,
                            )
                            asyncio.run(competing.set_tokens(value))
                        marker = tokens(homes).read_bytes()
                        if newer_state == "same":
                            assert marker == old_bytes, "Same-byte competing write setup differed"
                        else:
                            assert json.loads(marker)["access_token"] == foreign.token
                        cfg = saved_servers(homes)["reports"]
                        replacement_provider = get_manager().get_or_build_provider(
                            "reports", cfg["url"], cfg.get("oauth"),
                        )
                        assert replacement_provider is not None
                        assert replacement_provider.context.storage is not competing
            finally:
                release.set()
            assert_stale_settled(actual, homes, changed)
            if newer_state != "none":
                assert tokens(homes).read_bytes() == marker, "Old rollback removed newer OAuth state"
                with scoped(homes / "profiles" / "work"):
                    cfg = saved_servers(homes)["reports"]
                    assert get_manager().get_or_build_provider(
                        "reports", cfg["url"], cfg.get("oauth"),
                    ) is replacement_provider, "Old rollback displaced the newer provider owner"
            else:
                assert not tokens(homes).exists(), "Unadopted owned grant was retained after config changed"
            assert owner.operations("sentinel") == []
            assert_foreign_absent(foreign, homes)


@pytest.mark.parametrize("change", ("none", "unrelated-server", "other-profile"))
def test_unchanged_connection_keeps_actual_sdk_nonce_effect(homes, monkeypatch, surface, change):
    with serve_issuer() as owner, serve_issuer() as foreign:
        foreign.token = "different-owned-peer-token"
        with running(surface, owner, homes, monkeypatch) as actual:
            if change == "unrelated-server":
                mapping = saved_servers(homes)
                mapping["unrelated"] = {"url": foreign.mcp_url, "enabled": False}
                replace_servers(homes, mapping)
            elif change == "other-profile":
                replace_servers(homes, {"reports": {"url": foreign.mcp_url, "auth": "oauth"}}, "other")
            changed = config_bytes(homes)
            code, state, _ = owner.issue_code(actual.authorization_url)
            assert actual.callback(code, state)
            actual.settle()
            assert actual.poll()["status"] == "approved"
            assert config_bytes(homes) == changed
            assert json.loads(tokens(homes).read_text(encoding="utf-8"))["access_token"] == owner.token
            assert len(owner.operations("token_redemption")) == 1
            registry_effect(owner, homes / "profiles" / "work", "unchanged-" + surface + "-" + change)
            assert len(owner.operations("sentinel")) == 1
            assert_foreign_absent(foreign, homes)


def test_wrong_state_then_real_callback_and_replay_keep_one_grant(homes, monkeypatch, surface):
    with serve_issuer() as owner:
        owner.token_release.clear()
        with running(surface, owner, homes, monkeypatch) as actual:
            code, state, _ = owner.issue_code(actual.authorization_url)
            try:
                assert actual.callback(code, state + "-forged") is False
                assert not actual.bridge._callback_ready.is_set()
                assert owner.operations("token_request") == []
                assert actual.callback(code, state)
                assert owner.token_started.wait(5)
                assert actual.callback(code, state) is False
                assert not actual.bridge.worker_done
            finally:
                owner.token_release.set()
            actual.settle()
            assert actual.poll()["status"] == "approved"
            assert len(owner.operations("token_request")) == len(owner.operations("token_redemption")) == 1
            registry_effect(owner, homes / "profiles" / "work", "one-grant-" + surface)
            assert len(owner.operations("sentinel")) == 1


def test_changed_flow_settles_then_fresh_current_target_owns_grant(homes, monkeypatch, surface):
    with serve_issuer() as owner, serve_issuer() as foreign:
        foreign.token = "different-owned-peer-token"
        with running(surface, owner, homes, monkeypatch) as actual:
            old_code, old_state, _ = owner.issue_code(actual.authorization_url)
            changed = change_connection(homes, foreign, "replace")
            assert actual.callback(old_code, old_state) is False
            assert_stale_settled(actual, homes, changed)
            fresh = actual.restart(foreign)
            assert fresh.identity != actual.identity
            code, state, _ = foreign.issue_code(fresh.authorization_url)
            assert state != old_state
            assert fresh.callback(old_code, old_state) is False
            assert not fresh.bridge._callback_ready.is_set()
            assert foreign.operations("token_request") == []
            assert fresh.callback(code, state)
            fresh.settle()
            assert fresh.poll()["status"] == "approved"
            assert len(foreign.operations("token_request")) == len(foreign.operations("token_redemption")) == 1
            assert owner.operations("token_request") == owner.operations("sentinel") == []
            registry_effect(foreign, homes / "profiles" / "work", "fresh-current-" + surface)
            assert len(foreign.operations("sentinel")) == 1


def test_implicit_auth_commit_preserves_template_and_reusable_provider(homes, monkeypatch, surface):
    import asyncio
    from mcp.shared.auth import OAuthToken
    from tools.mcp_oauth_manager import get_manager

    monkeypatch.setenv("OWNED_LABEL", "synthetic-owned-profile-label")
    with serve_issuer() as owner, serve_issuer() as foreign:
        foreign.token = "different-owned-peer-token"
        with running(surface, owner, homes, monkeypatch, initial="implicit") as actual:
            assert saved_servers(homes)["reports"].get("auth") is None
            code, state, _ = owner.issue_code(actual.authorization_url)
            assert actual.callback(code, state)
            actual.settle()
            assert actual.poll()["status"] == "approved"
            assert saved_servers(homes)["reports"]["auth"] == "oauth"
            raw = config_bytes(homes)
            assert b"${OWNED_LABEL}" in raw
            assert b"synthetic-owned-profile-label" not in raw
            with scoped(homes / "profiles" / "work"):
                cfg = saved_servers(homes)["reports"]
                provider = get_manager().get_or_build_provider("reports", cfg["url"], cfg.get("oauth"))
                assert provider is not None
            registry_effect(owner, homes / "profiles" / "work", "implicit-cached-" + surface)
            with scoped(homes / "profiles" / "work"):
                assert get_manager().get_or_build_provider("reports", cfg["url"], cfg.get("oauth")) is provider
            assert len(owner.operations("sentinel")) == 1
            changed = change_connection(homes, foreign, "replace")
            with pytest.raises(RuntimeError, match="configuration changed"):
                asyncio.run(provider.context.storage.set_tokens(
                    OAuthToken(access_token=owner.token, token_type="Bearer", expires_in=3600)
                ))
            assert config_bytes(homes) == changed
            assert_foreign_absent(foreign, homes)


@pytest.mark.parametrize("invalid", ("malformed", "non-mapping", "directory"))
def test_actual_invalid_config_cannot_authorize_saved_flow(homes, monkeypatch, surface, invalid):
    with serve_issuer() as owner:
        with running(surface, owner, homes, monkeypatch) as actual:
            path = homes / "profiles" / "work" / "config.yaml"
            before = path.read_bytes()
            code, state, _ = owner.issue_code(actual.authorization_url)
            if invalid == "directory":
                backup = path.with_name("owned-config-before-directory.yaml")
                assert not backup.exists()
                path.rename(backup)
                path.mkdir()
                changed = None
            else:
                changed = b"mcp_servers: [" if invalid == "malformed" else b"- owned-non-mapping-root\n"
                path.write_bytes(changed)
            assert actual.callback(code, state) is False
            assert actual.bridge._callback is None
            actual.settle()
            status = actual.poll()
            assert status["status"] == "error", status
            assert "configuration changed" in (status.get("error_message") or status.get("error") or "").lower()
            assert not tokens(homes).exists()
            assert owner.operations("token_request") == owner.operations("sentinel") == []
            if invalid == "directory":
                assert path.is_dir()
                assert list(path.iterdir()) == []
                assert backup.read_bytes() == before
            else:
                assert path.read_bytes() == changed


@pytest.mark.parametrize("route", ("replace", "remove", "enabled", "schema", "raw"))
def test_actual_rest_config_mutation_rejects_old_callback(homes, monkeypatch, route):
    import yaml

    with serve_issuer() as owner, serve_issuer() as foreign:
        foreign.token = "different-owned-peer-token"
        with running("rest", owner, homes, monkeypatch) as actual:
            code, state, _ = owner.issue_code(actual.authorization_url)
            client = actual.client
            cfg = saved_servers(homes)["reports"]
            cfg["url"] = foreign.mcp_url
            if route == "replace":
                response = client.put("/api/mcp/servers?profile=work", json={"servers": {"reports": cfg}})
            elif route == "remove":
                response = client.delete("/api/mcp/servers/reports?profile=work")
            elif route == "enabled":
                response = client.put("/api/mcp/servers/reports/enabled?profile=work", json={"enabled": False})
            elif route == "schema":
                response = client.put("/api/config?profile=work", json={"config": {"mcp_servers": {"reports": cfg}}})
            else:
                response = client.put("/api/config/raw?profile=work", json={
                    "yaml_text": yaml.safe_dump({"mcp_servers": {"reports": cfg}}, allow_unicode=True),
                })
            assert response.status_code == 200, response.text
            changed = config_bytes(homes)
            assert actual.callback(code, state) is False
            assert_stale_settled(actual, homes, changed)
            assert owner.operations("token_request") == owner.operations("sentinel") == []
            assert_foreign_absent(foreign, homes)


def test_actual_rpc_secret_reference_mutation_rejects_old_callback(homes, monkeypatch):
    from tui_gateway import server

    with serve_issuer() as owner:
        with running("relay", owner, homes, monkeypatch) as actual:
            code, state, _ = owner.issue_code(actual.authorization_url)
            result = server._methods["mcp.servers.set_api_key"](20, {
                "profile": "work", "name": "reports", "value": "synthetic-owned-api-key",
            })
            assert "error" not in result and result["result"]["ok"], result
            changed = config_bytes(homes)
            assert b"${MCP_REPORTS_API_KEY}" in changed
            assert b"synthetic-owned-api-key" not in changed
            assert actual.callback(code, state) is False
            assert_stale_settled(actual, homes, changed)
            assert owner.operations("token_request") == owner.operations("sentinel") == []


def test_changed_after_actual_probe_cannot_commit_old_connection(homes, monkeypatch, request, surface):
    from hermes_cli import mcp_config
    from tools.mcp_oauth_manager import MCPOAuthManager

    completed, release = threading.Event(), threading.Event()
    original = mcp_config._probe_single_server
    original_adopt = MCPOAuthManager.adopt_dashboard_flow
    observations = []

    def after_real_probe(*args, **kwargs):
        result = original(*args, **kwargs)
        observations.append({"name": args[0], "tools": list(result)})
        return result

    def before_real_adoption(manager, flow, storage, tools):
        present = storage.has_cached_tokens()
        assert present and len(observations) == 1
        observations[0]["actual_token_presence"] = present
        completed.set()
        assert release.wait(12), "Owned actual probe completion barrier timed out"
        return original_adopt(manager, flow, storage, tools)

    monkeypatch.setattr(mcp_config, "_probe_single_server", after_real_probe)
    monkeypatch.setattr(MCPOAuthManager, "adopt_dashboard_flow", before_real_adoption)
    with serve_issuer() as owner, serve_issuer() as foreign:
        foreign.token = "different-owned-peer-token"
        with running(surface, owner, homes, monkeypatch) as actual:
            code, state, _ = owner.issue_code(actual.authorization_url)
            try:
                assert actual.callback(code, state)
                assert completed.wait(5), actual.bridge.snapshot()
                assert len(observations) == 1 and observations[0]["tools"]
                assert len(owner.operations("token_redemption")) == 1
                assert owner.operations("mcp_request")
                assert not actual.bridge.worker_done
                changed = change_connection(homes, foreign, "replace")
            finally:
                release.set()
                request.node.user_properties.append((
                    "actual_probe_before_final_adoption", json.dumps(observations),
                ))
            assert_stale_settled(actual, homes, changed)
            assert not tokens(homes).exists()
            assert owner.operations("sentinel") == []
            assert_foreign_absent(foreign, homes)


@pytest.mark.parametrize("writer", ("helper", "schema"))
def test_actual_config_rmw_preserves_later_whole_map_replacement(homes, monkeypatch, request, writer):
    from hermes_cli import config, mcp_config, web_server

    snapshot, release = threading.Event(), threading.Event()
    classified, newer_done = threading.Event(), threading.Event()
    errors, attempts, observed_reads = [], [], []
    original_lock = config._CONFIG_LOCK

    class ObservedConfigLock:
        """Delegate every acquisition to the actual shared RLock."""

        def __enter__(self):
            if threading.current_thread().name == "owned-config-newer-rmw":
                acquired = original_lock.acquire(blocking=False)
                attempts.append(acquired)
                classified.set()
                if not acquired:
                    original_lock.acquire()
            else:
                original_lock.acquire()
            return self

        def __exit__(self, *_exc):
            original_lock.release()

    with serve_issuer() as owner, serve_issuer() as foreign:
        with running_rest(owner, homes, monkeypatch, manual_start=True) as acquired:
            client = acquired[0]
            replacement = {"reports": dict(saved_servers(homes)["reports"], url=foreign.mcp_url)}
            monkeypatch.setattr(config, "_CONFIG_LOCK", ObservedConfigLock())
            if writer == "helper":
                original_read = mcp_config._read_raw_mcp_config

                def after_real_read(*args, **kwargs):
                    value = original_read(*args, **kwargs)
                    if threading.current_thread().name == "owned-config-stale-rmw":
                        observed_reads.append(value["mcp_servers"]["reports"]["url"])
                        snapshot.set()
                        assert release.wait(12), "Owned helper config read barrier timed out"
                    return value

                monkeypatch.setattr(mcp_config, "_read_raw_mcp_config", after_real_read)
            else:
                original_read = web_server.read_raw_config

                def after_real_read(*args, **kwargs):
                    value = original_read(*args, **kwargs)
                    observed_reads.append(value["mcp_servers"]["reports"]["url"])
                    snapshot.set()
                    assert release.wait(12), "Owned REST config read barrier timed out"
                    return value

                monkeypatch.setattr(web_server, "read_raw_config", after_real_read)

            def stale_write():
                try:
                    if writer == "helper":
                        with scoped(homes / "profiles" / "work"):
                            assert mcp_config._save_mcp_server(
                                "unrelated", {"url": owner.mcp_url, "enabled": False},
                            )
                    else:
                        response = client.put("/api/config?profile=work", json={
                            "config": {"terminal": {"lifetime_seconds": 4321}},
                        })
                        assert response.status_code == 200, response.text
                except BaseException as exc:
                    errors.append(("stale", repr(exc)))

            def newer_write():
                try:
                    replace_servers(homes, replacement)
                except BaseException as exc:
                    errors.append(("newer", repr(exc)))
                finally:
                    newer_done.set()

            stale = threading.Thread(target=stale_write, name="owned-config-stale-rmw")
            newer = threading.Thread(target=newer_write, name="owned-config-newer-rmw")
            newer_started = False
            try:
                stale.start()
                assert snapshot.wait(5), errors
                newer.start()
                newer_started = True
                assert classified.wait(5), errors
                # A genuine successful acquisition allows B to finish before
                # releasing A. A genuine blocked acquisition releases A first.
                # This decision uses the actual RLock, never a timing guess.
                if attempts[0]:
                    assert newer_done.wait(5), errors
            finally:
                release.set()
                stale.join(timeout=12)
                if newer_started:
                    newer.join(timeout=12)
                request.node.user_properties.append(("actual_config_rmw_contention", json.dumps({
                    "writer": writer, "newer_actual_nonblocking_acquisitions": attempts,
                    "actual_read_urls": observed_reads, "errors": errors,
                    "stale_alive": stale.is_alive(), "newer_alive": newer.is_alive(),
                    "scope": "Actual same-process config RMW only; no OAuth/external-process claim",
                })))
            assert not stale.is_alive() and not newer.is_alive()
            assert not errors, errors
            assert observed_reads == [owner.mcp_url]
            assert saved_servers(homes) == replacement, "Earlier stale RMW resurrected the old server map"
