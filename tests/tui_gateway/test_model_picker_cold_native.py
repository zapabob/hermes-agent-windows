"""Actual registered RPC, Windows workers, parser and cache; only leaf doubles."""
import json
from pathlib import Path
import socket
import threading
import time
from types import SimpleNamespace
import urllib.request

import pytest


class Response:
    def __init__(self, payload):
        self.payload = payload

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def read(self):
        return json.dumps(self.payload).encode("utf-8")


class RecordingTransport:
    def __init__(self, rid):
        self.rid = rid
        self.frames = []
        self.completed = threading.Event()
        self.written_at = None

    def write(self, frame):
        self.frames.append(frame)
        if frame.get("id") == self.rid:
            self.written_at = time.perf_counter()
            self.completed.set()
        return True

    def close(self):
        pass


@pytest.fixture
def native(tmp_path, monkeypatch):
    root = tmp_path / "P04 日本語 root"
    root.mkdir()
    user = root / "user"
    user.mkdir()
    for key in ("HERMES_HOME", "HOME", "USERPROFILE", "CODEX_HOME"):
        monkeypatch.setenv(key, str(root if key == "HERMES_HOME" else user))
    monkeypatch.setattr(Path, "home", lambda: user)
    monkeypatch.setenv("DEEPSEEK_API_KEY", "P04-synthetic-key")
    state = SimpleNamespace(hold="provider", entered=threading.Event(),
                            release=threading.Event(), records=[], refused=[], unexpected=[],
                            transports=[], credentials=[], empty=False, failed=False,
                            providers={"deepseek"}, timings=[])
    # Install denial before production imports, which may read optional
    # catalogs while constructing static provider floors.
    def bootstrap_refusal(req, **kwargs):
        url = req.full_url if hasattr(req, "full_url") else str(req)
        state.refused.append(url)
        raise OSError("P04 optional bootstrap transport refused")

    def deny(*args, **kwargs):
        state.unexpected.append(repr(args[:1]))
        raise AssertionError("P04 unexpected socket/DNS access")

    import requests
    monkeypatch.setattr(requests, "get", bootstrap_refusal)
    monkeypatch.setattr(urllib.request, "urlopen", bootstrap_refusal)
    monkeypatch.setattr(socket.socket, "connect", deny)
    monkeypatch.setattr(socket.socket, "connect_ex", deny)
    monkeypatch.setattr(socket, "getaddrinfo", deny)
    # The real registry initializes in the owned home before any timing starts.
    from hermes_cli import auth, models, urllib_security
    from providers import get_provider_profile
    from hermes_constants import get_hermes_home, get_hermes_home_override
    import tui_gateway.server as server
    profile = get_provider_profile("deepseek")
    assert profile is not None and profile.fetch_models.__func__.__module__ == "providers.base"
    assert get_hermes_home_override() is None
    allowed = {"deepseek"}
    excluded = sorted({p.slug for p in models.CANONICAL_PROVIDERS} - allowed)
    for name in ("work", "other"):
        home = root / "profiles" / name
        home.mkdir(parents=True)
        cfg = {"model": {"provider": "deepseek", "default": name + "-current",
                         "base_url": "https://192.0.2.204/v1"},
               "agent": {"reasoning_effort": "high"}, "fast_mode": True,
               "model_catalog": {"enabled": False, "excluded_providers": excluded}}
        (home / "config.yaml").write_text(__import__("yaml").safe_dump(cfg), encoding="utf-8")
    (root / "config.yaml").write_text("model:\n  provider: deepseek\n  default: ambient-current\n", encoding="utf-8")

    def held(kind):
        if state.hold == kind:
            state.entered.set()
            assert state.release.wait(5), "P04 owned leaf emergency release expired"

    def credentials(provider, **kwargs):
        if provider in state.providers:
            held("auth")
            state.credentials.append(str(get_hermes_home()))
            return {"api_key": "P04-synthetic-key", "base_url": "https://192.0.2.204/v1"}
        return {"api_key": "", "base_url": ""}

    def transport(req, **kwargs):
        url = req.full_url if hasattr(req, "full_url") else str(req)
        state.records.append({"url": url, "home": str(get_hermes_home()),
                              "thread": threading.current_thread().name})
        if url in {"https://192.0.2.204/v1/models", "https://192.0.2.205/v1/models",
                   "http://127.0.0.1:11434/api/tags"}:
            held("provider")
            if state.failed:
                raise OSError("P04 synthetic discovery failure")
            if url.endswith("/api/tags"):
                return Response({"models": [] if state.empty else [{"name": "p04-native-live"}]})
            return Response({"data": [] if state.empty else [{"id": "p04-live-only"}]})
        if "models.dev" in url or "models-dev/models" in url:
            import traceback
            state.records[-1]["stack"] = traceback.format_stack(limit=12)
            held("metadata")
            state.refused.append(url)
            raise OSError("P04 optional metadata transport refused")
        state.refused.append(url)
        raise OSError("P04 remote vendor/artifact/runtime transport refused")

    monkeypatch.setattr(auth, "resolve_api_key_provider_credentials", credentials)
    monkeypatch.setattr(urllib_security, "open_credentialed_url", transport)
    monkeypatch.setattr(models, "_urlopen_model_catalog_request", transport)
    monkeypatch.setattr(urllib.request, "urlopen", transport)
    monkeypatch.setattr(requests, "get", transport)
    monkeypatch.setattr(socket.socket, "connect", deny)
    monkeypatch.setattr(socket.socket, "connect_ex", deny)
    monkeypatch.setattr(socket, "getaddrinfo", deny)
    starting_threads = set(threading.enumerate())
    from concurrent.futures import ThreadPoolExecutor
    rpc_pool = ThreadPoolExecutor(max_workers=server._pool._max_workers, thread_name_prefix="p04-rpc-owned")
    monkeypatch.setattr(server, "_pool", rpc_pool)
    before = {p: p.read_bytes() for p in root.rglob("config.yaml")}
    n = SimpleNamespace(root=root, server=server, models=models, state=state, before=before)
    try:
        yield n
    finally:
        state.release.set()
        for transport_owner in state.transports:
            assert transport_owner.completed.wait(10), "owned RPC failed to finish"
        rpc_pool.shutdown(wait=True)
        for worker in set(threading.enumerate()) - starting_threads:
            if worker.name.startswith("model-cache-swr-"):
                worker.join(10)
                assert not worker.is_alive(), worker.name
        assert not models._swr_refresh_inflight
        assert get_hermes_home_override() is None
        (root / "P04-observations.json").write_text(json.dumps({
            "transports": state.records, "credentials": state.credentials,
            "refused": state.refused, "unexpected": state.unexpected,
            "responses": [t.frames for t in state.transports],
            "rpc_response_seconds": [t.written_at - at for t, at in state.timings if t.written_at],
        }, indent=2), encoding="utf-8")
        assert not state.unexpected
        assert all(p.read_bytes() == data for p, data in before.items())


def submit(n, profile="work", refresh=False, rid=None, session_id=None):
    rid = rid or "p04-" + str(len(n.state.transports))
    owner = RecordingTransport(rid)
    n.state.transports.append(owner)
    started = time.perf_counter()
    n.state.timings.append((owner, started))
    returned = n.server.dispatch({"jsonrpc": "2.0", "id": rid, "method": "model.options",
                                 "params": {"profile": profile, "explicit_only": True,
                                            "refresh": refresh, "session_id": session_id}}, transport=owner)
    assert returned is None  # Submission alone is deliberately insufficient.
    return owner, started


def positive(owner, started, current="work-current", bound=1.0):
    assert owner.completed.wait(max(0, bound - (time.perf_counter() - started))), (
        "actual matching transport.write did not arrive within cold response bound")
    assert owner.written_at - started < bound
    frames = [f for f in owner.frames if f.get("id") == owner.rid]
    assert len(frames) == 1 and "error" not in frames[0], frames
    payload = frames[0]["result"]
    assert payload["model"] == current
    assert payload["providers"] and any(r["models"] for r in payload["providers"])
    return payload


def finish_refresh(n, profile="work", live="p04-live-only", key="deepseek"):
    n.state.release.set()
    path = n.root / "profiles" / profile / "provider_models_cache.json"
    deadline = time.perf_counter() + 5
    while time.perf_counter() < deadline:
        if path.exists():
            try:
                entry = json.loads(path.read_text(encoding="utf-8")).get(key, {})
                if live in entry.get("models", []) and not n.models._swr_refresh_inflight:
                    return entry
            except (OSError, ValueError):
                # Windows atomic replacement may briefly deny a polling read.
                pass
        time.sleep(0.005)
    pytest.fail("real parser/SWR did not persist released live-only model")


@pytest.mark.parametrize("leaf", ["provider", "auth", "metadata"])
def test_cold_registered_dispatch_positive_before_held_leaf(native, leaf):
    n = native
    n.state.hold = leaf
    owner, started = submit(n)
    payload = positive(owner, started)
    assert payload["provider"] == "deepseek"
    assert not n.state.release.is_set()
    if leaf != "metadata":
        assert n.state.entered.wait(1), "discovery leaf was never exercised"
    else:
        assert n.state.entered.wait(1), "normal RPC did not start the existing metadata worker"
        from agent import models_dev
        from hermes_constants import set_hermes_home_override, reset_hermes_home_override

        token = set_hermes_home_override(n.root / "profiles/work")
        try:
            metadata_state = models_dev._get_models_dev_state()
        finally:
            reset_hermes_home_override(token)
        metadata_workers = [t for t in threading.enumerate() if t.name == "models-dev-refresh"]
        assert metadata_state._models_dev_refresh_in_flight and metadata_workers
    finish_refresh(n)
    if leaf == "metadata":
        for worker in metadata_workers:
            worker.join(5)
            assert not worker.is_alive()
        assert not metadata_state._models_dev_refresh_in_flight
        assert metadata_state._models_dev_retry_after > time.time()
        metadata_requests = [r for r in n.state.records if "models.dev" in r["url"]]
        assert len(metadata_requests) == 1
        assert Path(metadata_requests[0]["home"]) == n.root / "profiles/work"
    second, at = submit(n)
    recovered = positive(second, at)
    assert "p04-live-only" in next(r["models"] for r in recovered["providers"] if r["slug"] == "deepseek")
    if leaf == "metadata":
        assert len([r for r in n.state.records if "models.dev" in r["url"]]) == 1
    from hermes_constants import get_hermes_home
    assert get_hermes_home() == n.root
    assert all(Path(r["home"]) == n.root / "profiles/work" for r in n.state.records
               if r["url"].endswith("/models"))
    assert not (n.root / "provider_models_cache.json").exists()


def test_forced_refresh_waits_for_existing_live_policy(native):
    n = native
    owner, started = submit(n, refresh=True)
    assert n.state.entered.wait(2)
    assert not owner.completed.wait(0.05)
    n.state.release.set()
    payload = positive(owner, started, bound=5)
    assert "p04-live-only" in next(r["models"] for r in payload["providers"] if r["slug"] == "deepseek")


def test_same_profile_owners_dedupe_but_distinct_profiles_refresh(native):
    n = native
    first, a = submit(n, rid="owner-a")
    positive(first, a)
    assert n.state.entered.wait(1)
    second, b = submit(n, rid="owner-b")
    positive(second, b)
    other, c = submit(n, profile="other", rid="owner-c")
    positive(other, c, current="other-current")
    deadline = time.perf_counter() + 1
    while len([r for r in n.state.records if r["url"].endswith("/models")]) < 2 and time.perf_counter() < deadline:
        time.sleep(0.005)
    calls = [r for r in n.state.records if r["url"].endswith("/models")]
    assert sorted(r["home"] for r in calls) == sorted(str(n.root / "profiles" / p) for p in ("work", "other"))
    finish_refresh(n)
    finish_refresh(n, profile="other")


def test_successful_stale_disk_is_immediate_without_selection_change(native):
    n = native
    from hermes_constants import set_hermes_home_override, reset_hermes_home_override
    home = n.root / "profiles/work"
    token = set_hermes_home_override(home)
    try:
        n.models.update_provider_cache_entry("deepseek", ["p04-stale-success"])
    finally:
        reset_hermes_home_override(token)
    path = home / "provider_models_cache.json"
    rows = json.loads(path.read_text(encoding="utf-8"))
    rows["deepseek"]["at"] = time.time() - 3601
    path.write_text(json.dumps(rows), encoding="utf-8")
    owner, at = submit(n)
    payload = positive(owner, at)
    assert "p04-stale-success" in next(r["models"] for r in payload["providers"] if r["slug"] == "deepseek")
    assert n.state.entered.wait(1)
    finish_refresh(n)


def configure(n, model, *, providers=None, catalog=None):
    """Write only this test's config; establish its immutable request baseline."""
    import yaml
    path = n.root / "profiles/work/config.yaml"
    cfg = yaml.safe_load(path.read_text(encoding="utf-8"))
    cfg["model"].update(model)
    if providers is not None:
        cfg["providers"] = providers
    if catalog is not None:
        cfg["model_catalog"].update(catalog)
    path.write_text(yaml.safe_dump(cfg), encoding="utf-8")
    n.before[path] = path.read_bytes()
    return cfg


@pytest.mark.parametrize("kind", ["named", "bare", "grouped"])
def test_current_custom_rpc_is_cold_nonblocking_then_recovers(native, monkeypatch, kind):
    n = native
    monkeypatch.delenv("DEEPSEEK_API_KEY")
    endpoint = "https://192.0.2.205/v1"
    providers = {} if kind == "bare" else {"edge": {"name": "Edge", "base_url": endpoint,
                                                     "model": "work-current"}}
    if kind == "grouped":
        providers["edge-extra"] = {"name": "Edge - second", "base_url": endpoint,
                                   "model": "p04-config-extra"}
    configure(n, {"provider": "custom" if kind == "bare" else "edge", "base_url": endpoint},
              providers=providers)
    owner, at = submit(n)
    payload = positive(owner, at)
    assert any("work-current" in row["models"] for row in payload["providers"])
    assert n.state.entered.wait(1)
    finish_refresh(n, key="custom:" + endpoint)
    second, at = submit(n)
    recovered = positive(second, at)
    assert any("p04-live-only" in row["models"] for row in recovered["providers"])


@pytest.mark.parametrize("allowlist", [False, True])
def test_saved_custom_discovery_gate_is_pure_cache_only(native, monkeypatch, allowlist):
    n = native
    monkeypatch.delenv("DEEPSEEK_API_KEY")
    endpoint = "https://192.0.2.205/v1"
    entry = {"name": "Edge", "base_url": endpoint, "model": "work-current"}
    if allowlist:
        entry["models"] = ["work-current"]
    else:
        entry["discover_models"] = False
    configure(n, {"provider": "edge", "base_url": endpoint}, providers={"edge": entry})
    owner, at = submit(n)
    positive(owner, at)
    assert not n.state.entered.is_set()
    assert not n.models._swr_refresh_inflight
    assert not [r for r in n.state.records if r["url"].endswith("/models")]


@pytest.mark.parametrize("failed", [False, True])
def test_custom_stale_refresh_is_actual_live_and_failure_cannot_retimestamp(native, monkeypatch, failed):
    n = native
    monkeypatch.delenv("DEEPSEEK_API_KEY")
    endpoint = "https://192.0.2.205/v1"
    configure(n, {"provider": "edge", "base_url": endpoint},
              providers={"edge": {"name": "Edge", "base_url": endpoint, "model": "work-current"}})
    path = n.root / "profiles/work/provider_models_cache.json"
    key = "custom:" + endpoint
    fp = n.models._custom_endpoint_fingerprint("", None, None)
    path.write_text(json.dumps({key: {"fp": fp, "at": time.time() - 3601,
                                     "models": ["p04-stale-custom"]}}), encoding="utf-8")
    before = path.read_bytes()
    n.state.failed = failed
    owner, at = submit(n)
    payload = positive(owner, at)
    assert any("p04-stale-custom" in r["models"] for r in payload["providers"])
    assert n.state.entered.wait(1), "stale custom row must invoke the actual transport"
    n.state.release.set()
    if failed:
        deadline = time.perf_counter() + 5
        while n.models._swr_refresh_inflight and time.perf_counter() < deadline:
            time.sleep(0.005)
        assert path.read_bytes() == before
    else:
        finish_refresh(n, key=key)


def test_native_authoritative_empty_after_background_recovery(native, monkeypatch):
    n = native
    monkeypatch.delenv("DEEPSEEK_API_KEY")
    endpoint = "http://127.0.0.1:11434/v1"
    configure(n, {"provider": "ollama", "base_url": endpoint},
              providers={"ollama": {"name": "Ollama", "base_url": endpoint, "model": "work-current"}},
              catalog={"excluded_providers": sorted({p.slug for p in n.models.CANONICAL_PROVIDERS})})
    n.state.empty = True
    owner, at = submit(n)
    positive(owner, at)
    assert n.state.entered.wait(1)
    n.state.release.set()
    path = n.root / "profiles/work/provider_models_cache.json"
    deadline = time.perf_counter() + 5
    while n.models._swr_refresh_inflight and time.perf_counter() < deadline:
        time.sleep(0.005)
    rows = json.loads(path.read_text(encoding="utf-8"))
    assert rows["custom:" + endpoint]["models"] == []
    assert rows["custom:" + endpoint]["native"] is True
    second, at = submit(n)
    assert second.completed.wait(1)
    payload = next(f["result"] for f in second.frames if f.get("id") == second.rid)
    row = next(r for r in payload["providers"] if r.get("native_catalog_empty"))
    assert row["models"] == [] and payload["model"] == "work-current"
    assert len([r for r in n.state.records if r["url"].endswith("/api/tags")]) == 1


@pytest.mark.parametrize("age", [0, 301])
@pytest.mark.parametrize("kind", ["keyed", "saved"])
def test_saved_native_empty_obeys_300s_ttl_without_fetch_or_swr(native, age, kind):
    n = native
    endpoint = "http://127.0.0.1:11434/v1"
    configure(n, {}, providers={"ollama": {"name": "Saved Ollama", "base_url": endpoint,
                                           "model": "p04-saved-native"}})
    if kind == "saved":
        import yaml
        cfgpath = n.root / "profiles/work/config.yaml"
        cfg = yaml.safe_load(cfgpath.read_text(encoding="utf-8"))
        cfg.pop("providers")
        cfg["custom_providers"] = [{"name": "Saved Ollama", "base_url": endpoint,
                                    "model": "p04-saved-native"}]
        cfgpath.write_text(yaml.safe_dump(cfg), encoding="utf-8")
        n.before[cfgpath] = cfgpath.read_bytes()
    path = n.root / "profiles/work/provider_models_cache.json"
    path.write_text(json.dumps({"custom:" + endpoint: {
        "fp": n.models._custom_endpoint_fingerprint("", None, None),
        "at": time.time() - age, "models": [], "native": True,
    }}), encoding="utf-8")
    owner, at = submit(n)
    payload = positive(owner, at)
    row = next(r for r in payload["providers"] if r["name"] == "Saved Ollama")
    if age == 0:
        assert row["native_catalog_empty"] is True and row["models"] == []
    else:
        assert not row["native_catalog_empty"] and row["models"] == ["p04-saved-native"]
    assert not [r for r in n.state.records if "127.0.0.1" in r["url"]]
    assert not any("127.0.0.1" in str(key) for key in n.models._swr_refresh_inflight)
    finish_refresh(n)


def test_failed_stale_refresh_preserves_exact_successful_disk_bytes(native):
    n = native
    from hermes_constants import set_hermes_home_override, reset_hermes_home_override
    home = n.root / "profiles/work"
    token = set_hermes_home_override(home)
    try:
        n.models.update_provider_cache_entry("deepseek", ["p04-previous-success"])
    finally:
        reset_hermes_home_override(token)
    path = home / "provider_models_cache.json"
    rows = json.loads(path.read_text(encoding="utf-8"))
    rows["deepseek"]["at"] = time.time() - 3601
    path.write_text(json.dumps(rows), encoding="utf-8")
    before = path.read_bytes()
    n.state.failed = True
    owner, at = submit(n)
    positive(owner, at)
    assert n.state.entered.wait(1)
    n.state.release.set()
    deadline = time.perf_counter() + 5
    while n.models._swr_refresh_inflight and time.perf_counter() < deadline:
        time.sleep(0.005)
    assert path.read_bytes() == before


def test_optional_vendor_manifest_and_override_refused_without_required_runtime(native):
    n = native
    configure(n, {}, catalog={"enabled": True, "url": "https://p04.invalid/artifacts/master.json",
                             "providers": {"nous": {"url": "https://p04.invalid/artifacts/nous.json"}}})
    owner, at = submit(n)
    positive(owner, at)
    assert not [r for r in n.state.records if "/artifacts/" in r["url"]]
    finish_refresh(n)


def test_options_never_mutates_active_selection_effort_or_fast(native):
    n = native
    session = {"model": "work-current", "provider": "deepseek", "reasoning_effort": "high", "fast_mode": True}
    # Install a real test-owned session record; no handler or agent factory double.
    n.server._sessions["p04-owned-session"] = session
    try:
        owner, at = submit(n, session_id="p04-owned-session")
        positive(owner, at)
        assert all(session[key] == value for key, value in {
            "model": "work-current", "provider": "deepseek", "reasoning_effort": "high", "fast_mode": True,
        }.items())
        assert ("deepseek", "work-current") in session["model_options_catalogue"]
        finish_refresh(n)
    finally:
        n.server._sessions.pop("p04-owned-session")


def test_four_authenticated_generic_providers_do_not_wait_for_prefetch(native, monkeypatch):
    n = native
    from hermes_cli.auth import PROVIDER_REGISTRY
    from providers import get_provider_profile
    slugs = {"deepseek", "xai", "arcee", "kilocode"}
    n.state.providers = slugs
    for slug in slugs:
        assert get_provider_profile(slug).fetch_models.__func__.__module__ == "providers.base"
        monkeypatch.setenv(PROVIDER_REGISTRY[slug].api_key_env_vars[0], "P04-synthetic-key")
    configure(n, {}, catalog={"excluded_providers": sorted({p.slug for p in n.models.CANONICAL_PROVIDERS} - slugs)})
    owner, at = submit(n)
    positive(owner, at)
    assert n.state.entered.wait(1)
    n.state.release.set()
    deadline = time.perf_counter() + 5
    while n.models._swr_refresh_inflight and time.perf_counter() < deadline:
        time.sleep(0.005)
    rows = json.loads((n.root / "profiles/work/provider_models_cache.json").read_text(encoding="utf-8"))
    assert slugs <= rows.keys()


@pytest.mark.parametrize("paid_access", [False, None])
def test_warm_same_account_nous_rpc_preserves_authoritative_denials(native, monkeypatch, paid_access):
    """Nous keeps its existing restriction owners, outside cold latency scope."""
    import base64
    from hermes_cli import auth
    from hermes_constants import set_hermes_home_override, reset_hermes_home_override
    n = native
    monkeypatch.delenv("DEEPSEEK_API_KEY")
    home = n.root / "profiles/work"
    endpoint = "https://192.0.2.206"
    model = n.models.get_curated_nous_model_ids()[0]
    claims = {"sub": "P04-owned-account", "org_id": "P04-owned-org",
              "exp": int(time.time() + 3600), "scope": "inference:invoke",
              "paid_access": paid_access, "policy_present": paid_access is False}
    def part(value):
        return base64.urlsafe_b64encode(json.dumps(value).encode()).decode().rstrip("=")
    jwt = part({"alg": "none"}) + "." + part(claims) + ".synthetic"
    (home / "auth.json").write_text(json.dumps({"version": 1, "providers": {"nous": {
        "access_token": jwt, "inference_base_url": endpoint + "/v1",
        "portal_base_url": "https://192.0.2.207", "scope": "inference:invoke",
    }}}), encoding="utf-8")
    configure(n, {"provider": "nous", "default": model, "base_url": endpoint + "/v1"},
              catalog={"excluded_providers": sorted({p.slug for p in n.models.CANONICAL_PROVIDERS} - {"nous"})})
    monkeypatch.setattr(auth, "resolve_nous_runtime_credentials", lambda **kwargs: {
        "api_key": "P04-account-key", "base_url": endpoint + "/v1"})
    # Reset existing global mirrors, then populate them through the real
    # JSON parser and profile disk writer, never by a catalog/handler double.
    for name in ("_nous_reasoning_caps_cache", "_free_tier_cache"):
        monkeypatch.setattr(n.models, name, None)
    monkeypatch.setattr(n.models, "_nous_caps_disk_checked", False)
    monkeypatch.setattr(n.models, "_pricing_cache", {})
    def catalog_leaf(req, **kwargs):
        assert req.full_url == endpoint + "/v1/models"
        n.state.records.append({"url": req.full_url, "home": str(home), "thread": threading.current_thread().name})
        return Response({"data": [{"id": model, "supported_parameters": [],
                                   "pricing": {"prompt": "0.000001", "completion": "0.000002"}}]})
    monkeypatch.setattr(n.models, "_urlopen_model_catalog_request", catalog_leaf)
    token = set_hermes_home_override(home)
    try:
        n.models.fetch_models_with_pricing("P04-account-key", endpoint, force_refresh=True, include_sale_original=True)
        from hermes_cli.nous_account import get_nous_portal_account_info, nous_policy_present
        assert nous_policy_present() is (paid_access is False)
        assert get_nous_portal_account_info().paid_service_access is paid_access
    finally:
        reset_hermes_home_override(token)
    owner, at = submit(n)
    payload = positive(owner, at, current=model)
    row = next(r for r in payload["providers"] if r["slug"] == "nous")
    if paid_access is False:
        assert set(row["models"]) == {model}  # Known policy keeps no other curated row.
    else:
        assert model in row["models"]
        assert all("reasoning" not in detail for mid, detail in row["capabilities"].items() if mid != model)
    assert row["capabilities"][model]["reasoning"] is False
    if paid_access is False:
        assert row["free_tier"] is True and model in row["unavailable_models"]
    else:
        assert "free_tier" not in row and "unavailable_models" not in row
    assert len([r for r in n.state.records if r["url"] == endpoint + "/v1/models"]) == 1
