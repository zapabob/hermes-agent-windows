"""P05 actual registered RPC/cache effects, owned homes, credential/transport leaves."""
import base64
from concurrent.futures import ThreadPoolExecutor
import json
import os
from pathlib import Path
import socket
import sys
import threading
import time
from types import SimpleNamespace
import urllib.request

import pytest


class Response:
    def __init__(self, payload, status=200, etag='"p05"'):
        self.payload, self.status_code, self.headers = payload, status, {"ETag": etag}

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def read(self):
        return json.dumps(self.payload).encode("utf-8")

    def json(self):
        return self.payload

    def raise_for_status(self):
        assert self.status_code == 200


def registry(reasoning=False, name="P05 metadata"):
    return {"deepseek": {"id": "deepseek", "name": name, "models": {
        "deepseek-chat": {"id": "deepseek-chat", "name": name, "tool_call": True,
                          "reasoning": reasoning, "limit": {"context": 65536, "output": 4096}}}}}


@pytest.fixture
def native(tmp_path, monkeypatch):
    root = tmp_path / "P05 日本語 root"
    root.mkdir()
    user = root / "user"
    user.mkdir()
    for key in ("HERMES_HOME", "HOME", "USERPROFILE", "CODEX_HOME"):
        monkeypatch.setenv(key, str(root if key == "HERMES_HOME" else user))
    monkeypatch.setattr(Path, "home", lambda: user)
    monkeypatch.setenv("DEEPSEEK_API_KEY", "P05-synthetic")
    state = SimpleNamespace(records=[], unexpected=[], responses=[], entered=threading.Event(),
                            release=threading.Event(), held=False, status=200, failed=False,
                            payload=registry(), key="P05-key-A", endpoint="https://192.0.2.206",
                            policy_models=[], before={})

    def deny(*args, **kwargs):
        state.unexpected.append(str(args[:1]))
        raise AssertionError("P05 unexpected socket/DNS")

    def refused(*args, **kwargs):
        raise OSError("P05 optional transport refused")

    import requests
    monkeypatch.setattr(requests, "get", refused)
    monkeypatch.setattr(urllib.request, "urlopen", refused)
    monkeypatch.setattr(socket.socket, "connect", deny)
    monkeypatch.setattr(socket.socket, "connect_ex", deny)
    monkeypatch.setattr(socket, "getaddrinfo", deny)
    from agent import models_dev as md
    from hermes_cli import auth, models, model_catalog, nous_account
    from hermes_constants import get_hermes_home, set_hermes_home_override, reset_hermes_home_override
    import tui_gateway.server as server
    monkeypatch.setattr(md, "_models_dev_cache", {})
    monkeypatch.setattr(md, "_models_dev_cache_time", 0)
    monkeypatch.setattr(md, "_models_dev_retry_after", 0)
    monkeypatch.setattr(md, "_models_dev_refresh_in_flight", False)
    if hasattr(md, "_models_dev_states"):
        monkeypatch.setattr(md, "_models_dev_states", {})
    monkeypatch.setattr(models, "_pricing_cache", {})
    monkeypatch.setattr(models, "_pricing_cache_retry_after", {})
    monkeypatch.setattr(models, "_nous_reasoning_caps_cache", None)
    monkeypatch.setattr(models, "_nous_caps_disk_checked", False)
    monkeypatch.setattr(nous_account, "_account_info_cache", None)
    monkeypatch.setattr(model_catalog, "_catalog_cache", None)
    import yaml
    for name in ("work", "other"):
        home = root / "profiles" / name
        home.mkdir(parents=True)
        cfg = {"model": {"provider": "deepseek", "default": "deepseek-chat"},
               "agent": {"reasoning_effort": "high"}, "fast_mode": True,
               "model_catalog": {"enabled": False, "excluded_providers": sorted(
                   {p.slug for p in models.CANONICAL_PROVIDERS} - {"deepseek"})}}
        (home / "config.yaml").write_text(yaml.safe_dump(cfg), encoding="utf-8")
        token = set_hermes_home_override(home)
        try:
            models.update_provider_cache_entry("deepseek", ["deepseek-chat"])
        finally:
            reset_hermes_home_override(token)
    (root / "config.yaml").write_text("model: {provider: deepseek, default: ambient-current}\n", encoding="utf-8")
    state.before = {p: p.read_bytes() for p in root.rglob("config.yaml")}

    def credentials(provider, **kwargs):
        return {"api_key": "P05-synthetic" if provider == "deepseek" else "",
                "base_url": "https://192.0.2.205/v1"}

    def transport(req, **kwargs):
        url = req.full_url if hasattr(req, "full_url") else str(req)
        record = {"url": url, "home": str(get_hermes_home()),
                              "thread": threading.current_thread().name,
                              "conditional": kwargs.get("headers", {}).get("If-None-Match"),
                  "auth": req.get_header("Authorization") if hasattr(req, "get_header") else None}
        state.records.append(record)
        if "models.dev" in url or "192.0.2.210" in url or "192.0.2.211" in url:
            state.entered.set()
            if state.held:
                assert state.release.wait(10), "owned metadata leaf emergency release"
            record["home_after_release"] = str(get_hermes_home())
            if state.failed:
                raise OSError("P05 metadata failure")
            return Response(state.payload, state.status)
        if url in {"https://192.0.2.206/v1/models", "https://192.0.2.208/v1/models"}:
            if state.failed:
                raise OSError("P05 policy transport failure")
            if hasattr(state, "policy_payload"):
                return Response(state.policy_payload)
            return Response({"data": [{"id": m, "supported_parameters": [],
                                       "pricing": {"prompt": "0.000001", "completion": "0.000002"}}
                                      for m in state.policy_models]})
        raise OSError("P05 optional vendor transport refused")

    monkeypatch.setattr(auth, "resolve_api_key_provider_credentials", credentials)
    monkeypatch.setattr(auth, "resolve_nous_runtime_credentials", lambda **kw: {
        "api_key": state.key, "base_url": state.endpoint + "/v1"})
    monkeypatch.setattr(requests, "get", transport)
    monkeypatch.setattr(models, "_urlopen_model_catalog_request", transport)
    monkeypatch.setattr(urllib.request, "urlopen", transport)
    from hermes_cli import urllib_security
    monkeypatch.setattr(urllib_security, "open_credentialed_url", transport)
    pool = ThreadPoolExecutor(max_workers=server._pool._max_workers, thread_name_prefix="p05-rpc-owned")
    monkeypatch.setattr(server, "_pool", pool)
    threads = set(threading.enumerate())
    n = SimpleNamespace(root=root, state=state, md=md, models=models, server=server)
    try:
        yield n
    finally:
        state.release.set()
        for response in state.responses:
            assert response.done.wait(10)
        pool.shutdown(wait=True)
        for worker in set(threading.enumerate()) - threads:
            if worker.name.startswith(("models-dev-refresh", "model-cache-swr-", "reasoning-caps-warm")):
                worker.join(10)
                assert not worker.is_alive(), worker.name
        assert not state.unexpected
        assert all(p.read_bytes() == data for p, data in state.before.items())
        (root / "P05-observations.json").write_text(json.dumps({
            "transport": state.records, "unexpected": state.unexpected,
            "responses": [r.frames for r in state.responses],
            "rpc_seconds": [r.at - r.start for r in state.responses if r.at]}, indent=2), encoding="utf-8")


def scoped(n, callback, profile="work"):
    from hermes_constants import set_hermes_home_override, reset_hermes_home_override
    token = set_hermes_home_override(n.root / "profiles" / profile)
    try:
        return callback()
    finally:
        reset_hermes_home_override(token)


def submit(n, profile="work", refresh=False, bound=1):
    r = SimpleNamespace(done=threading.Event(), frames=[], at=None,
                        start=time.perf_counter(), rid="p05-" + str(len(n.state.responses)))
    def write(frame):
        r.frames.append(frame)
        if frame.get("id") == r.rid:
            r.at = time.perf_counter()
            r.done.set()
        return True
    n.state.responses.append(r)
    assert n.server.dispatch({"jsonrpc": "2.0", "id": r.rid, "method": "model.options",
                              "params": {"profile": profile, "explicit_only": True, "refresh": refresh}},
                             transport=SimpleNamespace(write=write, close=lambda: None)) is None
    assert r.done.wait(max(0, bound - (time.perf_counter() - r.start))), "actual matching RPC write absent"
    assert r.at - r.start < bound
    assert len(r.frames) == 1 and "error" not in r.frames[0], r.frames
    return r.frames[0]["result"]


def wait_until(predicate, bound=5):
    deadline = time.perf_counter() + bound
    while time.perf_counter() < deadline:
        if predicate():
            return
        time.sleep(0.005)
    pytest.fail("owned cache effect did not complete")


def metadata_calls(n):
    return [r for r in n.state.records if "models.dev" in r["url"] or "192.0.2.21" in r["url"]]


def test_normal_rpc_cold_metadata_starts_existing_worker_and_recovers(native):
    n = native
    n.state.held = True
    first = submit(n)
    assert first["model"] == "deepseek-chat"
    assert n.state.entered.wait(1), "normal RPC never starts existing metadata refresh"
    assert not n.state.release.is_set()
    n.state.release.set()
    home = n.root / "profiles/work"
    wait_until(lambda: (home / "models_dev_cache.json").exists())
    second = submit(n)
    row = next(r for r in second["providers"] if r["slug"] == "deepseek")
    assert row["capabilities"]["deepseek-chat"]["reasoning"] is False
    assert len(metadata_calls(n)) == 1
    assert metadata_calls(n)[0]["home"] == str(home)
    assert not (n.root / "models_dev_cache.json").exists()
    assert metadata_calls(n)[0]["home_after_release"] == str(home)


def setup_nous(n, profile="work"):
    import yaml
    home = n.root / "profiles" / profile
    path = home / "config.yaml"
    cfg = yaml.safe_load(path.read_text(encoding="utf-8"))
    ids = n.models.get_curated_nous_model_ids(cache_only=True)[:2]
    assert len(ids) == 2
    cfg["model"] = {"provider": "nous", "default": ids[0], "base_url": "https://192.0.2.206/v1"}
    cfg["model_catalog"]["excluded_providers"] = sorted({p.slug for p in n.models.CANONICAL_PROVIDERS} - {"nous"})
    path.write_text(yaml.safe_dump(cfg), encoding="utf-8")
    n.state.before[path] = path.read_bytes()
    claims = {"sub": "P05-owned", "org_id": "P05-org", "exp": int(time.time()+3600),
              "scope": "inference:invoke", "paid_access": False, "policy_present": True}
    part = lambda v: base64.urlsafe_b64encode(json.dumps(v).encode()).decode().rstrip("=")
    jwt = part({"alg": "none"}) + "." + part(claims) + ".synthetic"
    (home / "auth.json").write_text(json.dumps({"version": 1, "providers": {"nous": {
        "access_token": jwt, "inference_base_url": "https://192.0.2.206/v1",
        "portal_base_url": "https://192.0.2.207", "scope": "inference:invoke"}}}), encoding="utf-8")
    return ids


def test_public_rpc_current_credential_policy_partition(native):
    n = native
    a, b = setup_nous(n)
    n.state.policy_models = [a]
    first = submit(n)
    assert next(r for r in first["providers"] if r["slug"] == "nous")["models"] == [a]
    n.state.key = "P05-key-B"
    n.state.policy_models = [b]
    second = submit(n)
    row = next(r for r in second["providers"] if r["slug"] == "nous")
    assert a not in row["models"] and b in row["models"], "another credential's catalogue reused"
    # The existing reasoning memo may still hold A's known detail; an unknown
    # new route must omit a positive grant until that owner's own refresh.
    assert row["capabilities"][b].get("reasoning") is not True
    assert row["free_tier"] is True and b in row["unavailable_models"]


def test_public_policy_expiry_300_boundary(native, monkeypatch):
    n = native
    a, b = setup_nous(n)
    clock = SimpleNamespace(now=1000.)
    monkeypatch.setattr(n.models.time, "monotonic", lambda: clock.now)
    n.state.policy_models = [a]
    assert scoped(n, n.models.nous_policy_allowed_ids) == {a}
    n.state.policy_models = [b]
    clock.now = 1299.999
    assert scoped(n, n.models.nous_policy_allowed_ids) == {a}
    clock.now = 1300.
    assert scoped(n, n.models.nous_policy_allowed_ids) == {b}, "successful policy cache never expires"


def put_metadata(n, *, age=14401, profile="work", data=None, etag='"old"'):
    path = scoped(n, n.md._get_cache_path, profile)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data or registry(reasoning=True)), encoding="utf-8")
    stamp = time.time() - age
    os.utime(path, (stamp, stamp))
    path.with_suffix(".etag").write_text(etag, encoding="utf-8")
    return path


def settled(n, profile="work"):
    return not scoped(n, n.md._get_models_dev_state, profile)._models_dev_refresh_in_flight


@pytest.mark.parametrize("cached", [False, True])
def test_allow_network_false_is_pure_even_with_force_and_non_blocking(native, cached):
    n = native
    if cached:
        put_metadata(n)
    data = scoped(n, lambda: n.md.fetch_models_dev(force_refresh=True, allow_network=False,
                                                 non_blocking=True))
    assert bool(data) is cached
    assert not metadata_calls(n) and not n.state.entered.is_set()


def test_stale_public_rpc_is_immediate_then_changed_capability(native):
    n = native
    put_metadata(n)
    n.state.held = True
    first = submit(n)
    assert next(r for r in first["providers"] if r["slug"] == "deepseek")["capabilities"]["deepseek-chat"]["reasoning"] is True
    assert n.state.entered.wait(1)
    n.state.release.set()
    wait_until(lambda: settled(n))
    second = submit(n)
    assert next(r for r in second["providers"] if r["slug"] == "deepseek")["capabilities"]["deepseek-chat"]["reasoning"] is False
    assert len(metadata_calls(n)) == 1 and metadata_calls(n)[0]["conditional"] == '"old"'


def test_metadata_14400_boundary(native, monkeypatch):
    n = native
    base = time.time()
    clock = SimpleNamespace(now=base)
    monkeypatch.setattr(n.md.time, "time", lambda: clock.now)
    put_metadata(n, age=0)
    clock.now = base + 14399.99
    submit(n)
    assert not metadata_calls(n)
    clock.now = base + 14400
    submit(n)
    assert n.state.entered.wait(1)
    wait_until(lambda: settled(n))
    assert len(metadata_calls(n)) == 1


def test_stale_304_confirms_existing_bytes_and_etag(native):
    n = native
    path = put_metadata(n)
    raw, sidecar = path.read_bytes(), path.with_suffix(".etag").read_bytes()
    n.state.status = 304
    submit(n)
    assert n.state.entered.wait(1)
    wait_until(lambda: settled(n))
    assert path.read_bytes() == raw and path.with_suffix(".etag").read_bytes() == sidecar
    submit(n)
    assert len(metadata_calls(n)) == 1
    assert metadata_calls(n)[0]["conditional"] == '"old"'


@pytest.mark.parametrize("stale", [False, True])
def test_failure_backoff_300_is_per_source_with_boundary(native, monkeypatch, stale):
    n = native
    if stale:
        path = put_metadata(n)
        raw = path.read_bytes()
    clock = SimpleNamespace(now=time.time())
    monkeypatch.setattr(n.md.time, "time", lambda: clock.now)
    n.state.failed = True
    submit(n)
    assert n.state.entered.wait(1)
    wait_until(lambda: settled(n))
    state = scoped(n, n.md._get_models_dev_state)
    assert state._models_dev_retry_after == clock.now + 300
    if stale:
        assert path.read_bytes() == raw
    clock.now += 299.999
    submit(n)
    assert len(metadata_calls(n)) == 1
    clock.now += .001
    n.state.failed = False
    n.state.entered.clear()
    submit(n)
    assert n.state.entered.wait(1)
    wait_until(lambda: settled(n))
    assert len(metadata_calls(n)) == 2 and state._models_dev_retry_after == 0


def test_rpc_same_profile_singleflight_distinct_profiles_and_context_reset(native):
    n = native
    n.state.held = True
    submit(n)
    assert n.state.entered.wait(1)
    submit(n)
    submit(n, "other")
    wait_until(lambda: len(metadata_calls(n)) == 2)
    assert sorted(r["home"] for r in metadata_calls(n)) == sorted(
        str(n.root / "profiles" / name) for name in ("work", "other"))
    assert all(r["thread"] == "models-dev-refresh" for r in metadata_calls(n))
    from hermes_constants import get_hermes_home, get_hermes_home_override
    assert get_hermes_home_override() is None and get_hermes_home() == n.root
    n.state.release.set()
    wait_until(lambda: settled(n) and settled(n, "other"))
    assert all((n.root / "profiles" / name / "models_dev_cache.json").exists()
               for name in ("work", "other"))
    assert not (n.root / "models_dev_cache.json").exists()
    assert all(r["home_after_release"] == r["home"] for r in metadata_calls(n))


def change_mirror(n, url):
    import yaml
    path = n.root / "profiles/work/config.yaml"
    cfg = yaml.safe_load(path.read_text(encoding="utf-8"))
    cfg["models_dev"] = {"url": url}
    path.write_text(yaml.safe_dump(cfg), encoding="utf-8")
    n.state.before[path] = path.read_bytes()


def test_configured_mirrors_separate_paths_and_held_worker_source(native):
    n = native
    default = put_metadata(n, age=0)
    default_bytes = default.read_bytes()
    change_mirror(n, "https://192.0.2.210/api.json")
    first_path = scoped(n, n.md._get_cache_path)
    n.state.held = True
    submit(n)
    assert n.state.entered.wait(1)
    change_mirror(n, "https://192.0.2.211/api.json")
    second_path = scoped(n, n.md._get_cache_path)
    submit(n)
    wait_until(lambda: len(metadata_calls(n)) == 2)
    assert first_path != second_path and first_path != default and second_path != default
    n.state.release.set()
    wait_until(lambda: all("home_after_release" in r for r in metadata_calls(n)))
    assert all(r["home_after_release"] == r["home"] for r in metadata_calls(n))
    wait_until(lambda: first_path.exists() and second_path.exists())
    assert default.read_bytes() == default_bytes
    assert {r["url"] for r in metadata_calls(n)} == {
        "https://192.0.2.210/api.json", "https://192.0.2.211/api.json"}
    change_mirror(n, "https://192.0.2.210/api.json")
    submit(n)
    assert len(metadata_calls(n)) == 2


def test_nous_endpoint_partition_same_profile_credential(native):
    n = native
    a, b = setup_nous(n)
    n.state.policy_models = [a]
    assert scoped(n, n.models.nous_policy_allowed_ids) == {a}
    n.state.endpoint = "https://192.0.2.208"
    n.state.policy_models = [b]
    assert scoped(n, n.models.nous_policy_allowed_ids) == {b}
    n.state.endpoint = "https://192.0.2.206"
    assert scoped(n, n.models.nous_policy_allowed_ids) == {a}


@pytest.mark.parametrize("payload", [None, {"data": None}, {"data": [None]}])
def test_malformed_policy_revalidation_never_reinserts_known_denied_rows(native, monkeypatch, payload):
    n = native
    a, _b = setup_nous(n)
    clock = SimpleNamespace(now=1000.)
    monkeypatch.setattr(n.models.time, "monotonic", lambda: clock.now)
    n.state.policy_models = [a]
    assert next(r for r in submit(n)["providers"] if r["slug"] == "nous")["models"] == [a]
    n.state.policy_payload = payload
    clock.now += 300
    row = next(r for r in submit(n)["providers"] if r["slug"] == "nous")
    assert row["models"] == [a], "malformed response dropped this identity's known deny"


def test_default_fetch_remains_blocking_force_bypasses_backoff(native):
    n = native
    n.state.held = True
    result = []
    worker = threading.Thread(target=lambda: result.append(scoped(n, lambda: n.md.fetch_models_dev())),
                              name="p05-owned-foreground")
    worker.start()
    try:
        assert n.state.entered.wait(1)
        assert worker.is_alive() and not result
    finally:
        n.state.release.set()
        worker.join(5)
    assert not worker.is_alive() and result == [registry()]
    state = scoped(n, n.md._get_models_dev_state)
    state._models_dev_retry_after = time.time() + 300
    n.state.payload = registry(reasoning=True)
    assert scoped(n, lambda: n.md.fetch_models_dev(force_refresh=True)) == registry(reasoning=True)
    assert len(metadata_calls(n)) == 2 and state._models_dev_retry_after == 0


def test_foreground_environment_change_keeps_bound_disk_writer(native, monkeypatch):
    n = native
    a, b = (n.root / "profiles" / p for p in ("work", "other"))
    monkeypatch.setenv("HERMES_HOME", str(a))
    n.state.held = True
    results, errors = [], []

    def foreground():
        try:
            # No ContextVar home override: exercise the existing foreground
            # caller while another CLI/profile application changes the env.
            results.append(n.md.fetch_models_dev())
        except Exception as exc:
            errors.append(exc)

    worker = threading.Thread(target=foreground, name="p05-owned-env-foreground")
    worker.start()
    try:
        assert n.state.entered.wait(1)
        assert worker.is_alive() and not results
        monkeypatch.setenv("HERMES_HOME", str(b))
    finally:
        n.state.release.set()
        worker.join(5)
    assert not worker.is_alive() and not errors and results == [registry()]
    assert json.loads((a / "models_dev_cache.json").read_text(encoding="utf-8")) == registry()
    assert (a / "models_dev_cache.etag").read_text(encoding="utf-8") == '"p05"'
    assert not (b / "models_dev_cache.json").exists()
    assert not (b / "models_dev_cache.etag").exists()
    assert n.md.fetch_models_dev(allow_network=False) == {}
    monkeypatch.setenv("HERMES_HOME", str(a))
    assert n.md.fetch_models_dev(allow_network=False) == registry()


@pytest.mark.parametrize("axis", ["mirror", "environment"])
def test_public_fetch_identity_snapshot_survives_real_switch_between_reads(native, monkeypatch, axis):
    n = native
    from hermes_cli.config import cfg_get, load_config_readonly
    from hermes_constants import hermes_home_key
    import requests
    import yaml

    a, b = (n.root / "profiles" / p for p in ("work", "other"))
    url_a, url_b = "https://192.0.2.210/api.json", "https://192.0.2.211/api.json"

    def write_source(home, url):
        path = home / "config.yaml"
        stamp = path.stat()
        cfg = yaml.safe_load(path.read_text(encoding="utf-8"))
        cfg["models_dev"] = {"url": url}
        path.write_text(yaml.safe_dump(cfg), encoding="utf-8")
        os.utime(path, ns=(stamp.st_atime_ns, stamp.st_mtime_ns + 1_000_000))
        n.state.before[path] = path.read_bytes()

    write_source(a, url_a)
    write_source(b, url_b)
    monkeypatch.setenv("HERMES_HOME", str(a))
    leaf = requests.get

    def source_transport(req, **kwargs):
        response = leaf(req, **kwargs)
        response.payload = registry(name="source-A" if str(req) == url_a else "source-B")
        return response

    monkeypatch.setattr(requests, "get", source_transport)
    captured, resume = threading.Event(), threading.Event()
    results, errors, observed = [], [], []

    def trace(frame, event, arg):
        if (event == "return" and frame.f_code is n.md._get_models_dev_state.__code__
                and not captured.is_set()):
            observed.append({"state_key": list(frame.f_locals["key"])})
            captured.set()
            assert resume.wait(5), "owned identity scheduling barrier"
        return trace

    def fetch():
        sys.settrace(trace)
        try:
            results.append(n.md.fetch_models_dev())
        except Exception as exc:
            errors.append(exc)
        finally:
            sys.settrace(None)

    worker = threading.Thread(target=fetch, name="p05-owned-identity-snapshot")
    worker.start()
    try:
        assert captured.wait(2)
        assert observed == [{"state_key": [hermes_home_key(a), url_a]}]
        if axis == "mirror":
            write_source(a, url_b)
        else:
            monkeypatch.setenv("HERMES_HOME", str(b))
        # Read the actual config owner, without replacing its implementation
        # or mutating the returned readonly dict. Its signature sees the edit.
        assert cfg_get(load_config_readonly(), "models_dev", "url") == url_b
    finally:
        resume.set()
        worker.join(5)
    assert not worker.is_alive() and not errors and len(results) == 1
    if axis == "mirror":
        write_source(a, url_a)
    else:
        monkeypatch.setenv("HERMES_HOME", str(a))
    cached_a = n.md.fetch_models_dev(allow_network=False)
    n.state.records.append({"url": "p05-owned://identity-observation", "identity_switch_axis": axis, "captured": observed,
                            "first_result": results[0], "cache_only_a": cached_a})
    assert cached_a == registry(name="source-A"), "state(A) admitted registry from source/profile(B)"
    assert results == [registry(name="source-A")]
    path_a = n.md._get_cache_path()
    assert json.loads(path_a.read_text(encoding="utf-8")) == registry(name="source-A")
    assert path_a.with_suffix(".etag").read_text(encoding="utf-8") == '"p05"'
    assert metadata_calls(n)[0]["url"] == url_a
    assert Path(metadata_calls(n)[0]["home"]) == a


def test_nous_profile_partition_same_endpoint_credential(native):
    n = native
    a, b = setup_nous(n)
    setup_nous(n, "other")
    n.state.policy_models = [a]
    assert scoped(n, n.models.nous_policy_allowed_ids) == {a}
    n.state.policy_models = [b]
    assert scoped(n, n.models.nous_policy_allowed_ids, "other") == {b}
    assert scoped(n, n.models.nous_policy_allowed_ids) == {a}


def test_failed_policy_refresh_keeps_only_same_identity_known_deny(native, monkeypatch):
    n = native
    a, b = setup_nous(n)
    clock = SimpleNamespace(now=1000.)
    monkeypatch.setattr(n.models.time, "monotonic", lambda: clock.now)
    n.state.policy_models = [a]
    assert scoped(n, n.models.nous_policy_allowed_ids) == {a}
    clock.now += 300
    n.state.failed = True
    assert scoped(n, n.models.nous_policy_allowed_ids) == {a}
    row = next(r for r in submit(n)["providers"] if r["slug"] == "nous")
    assert row["models"] == [a] and row["capabilities"][a]["reasoning"] is False
    assert row["free_tier"] is True and a in row["unavailable_models"]
    n.state.key = "P05-key-B"
    assert scoped(n, n.models.nous_policy_allowed_ids) is None
    clock.now += 120
    n.state.failed = False
    n.state.policy_models = [b]
    assert scoped(n, n.models.nous_policy_allowed_ids) == {b}


def test_anonymous_catalog_never_supplies_authenticated_policy(native):
    n = native
    a, b = setup_nous(n)
    n.state.key = ""
    n.state.policy_models = [a]
    assert scoped(n, lambda: n.models.get_pricing_for_provider("nous"))
    assert scoped(n, n.models.nous_policy_allowed_ids) is None
    n.state.key = "P05-authenticated"
    n.state.policy_models = [b]
    assert scoped(n, n.models.nous_policy_allowed_ids) == {b}


def test_policy_force_refresh_uses_existing_parser_and_owner(native):
    n = native
    a, b = setup_nous(n)
    n.state.policy_models = [a]
    assert scoped(n, n.models.nous_policy_allowed_ids) == {a}
    n.state.policy_models = [b]
    assert scoped(n, lambda: n.models.nous_policy_allowed_ids(force_refresh=True)) == {b}
    assert scoped(n, lambda: n.models.get_pricing_for_provider("nous")) == {
        b: {"prompt": "0.000001", "completion": "0.000002"}}
    assert len([r for r in n.state.records if r["url"].endswith("/v1/models")]) == 2


@pytest.mark.parametrize("axis", ["cache", "retry", "inflight"])
def test_environmental_home_switch_without_context_override_isolated(native, monkeypatch, axis):
    n = native
    from hermes_constants import get_hermes_home_override
    assert get_hermes_home_override() is None
    if axis == "cache":
        n.state.payload = registry(reasoning=True)
        assert n.md.fetch_models_dev() == registry(reasoning=True)
    elif axis == "retry":
        n.state.failed = True
        assert n.md.fetch_models_dev() == {}
    else:
        n.state.held = True
        assert n.md.fetch_models_dev(non_blocking=True) == {}
        assert n.state.entered.wait(1)
    monkeypatch.setenv("HERMES_HOME", str(n.root / "profiles/other"))
    assert get_hermes_home_override() is None
    assert n.md.fetch_models_dev(allow_network=False) == {}, "default URL cache crossed environmental homes"
    n.state.failed = False
    n.state.held = True
    n.state.entered.clear()
    n.md.fetch_models_dev(non_blocking=True)
    wait_until(lambda: len(metadata_calls(n)) == 2, bound=1)
    assert {r["home"] for r in metadata_calls(n)} == {str(n.root), str(n.root / "profiles/other")}
    n.state.release.set()
    wait_until(lambda: all("home_after_release" in r for r in metadata_calls(n)))
    assert all(r["home_after_release"] == r["home"] for r in metadata_calls(n))
