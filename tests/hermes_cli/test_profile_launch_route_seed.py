"""New profile routes inherit selected raw config, not resolved credentials."""
from copy import deepcopy
from pathlib import Path
import socket

import pytest
import yaml


@pytest.fixture
def launch(tmp_path, monkeypatch):
    home = tmp_path / ".hermes"
    home.mkdir()
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    monkeypatch.setenv("HERMES_HOME", str(home))
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("USERPROFILE", str(tmp_path))

    def deny(*_args, **_kwargs):
        raise AssertionError("Profile seed must not use a network connection")

    monkeypatch.setattr(socket.socket, "connect", deny)
    monkeypatch.setattr(socket.socket, "connect_ex", deny)
    monkeypatch.setattr(socket, "getaddrinfo", deny)
    from hermes_cli import profiles
    from hermes_cli.config import DEFAULT_CONFIG, read_user_config_raw

    def create(source, name="child", **kwargs):
        raw = {**deepcopy(source), "_config_version": DEFAULT_CONFIG["_config_version"]}
        source_path = home / "config.yaml"
        source_path.write_text(yaml.safe_dump(raw), encoding="utf-8")
        before = source_path.read_bytes()
        kwargs.setdefault("no_alias", True)
        kwargs.setdefault("no_skills", True)
        result = profiles.create_profile(name, **kwargs)
        assert source_path.read_bytes() == before
        return result, read_user_config_raw(result / "config.yaml")

    return home, create


@pytest.mark.parametrize("schema,provider,url_key", [
    ("providers", "lab", "api"),
    ("providers", "custom:lab", "baseUrl"),
    ("providers", "custom:display-name", "base_url"),
    ("custom_providers", "custom:display-name", "base_url"),
])
def test_fresh_create_keeps_selected_endpoint_and_raw_credentials(launch, schema, provider, url_key):
    _, create = launch
    endpoint = {"name": "Display Name", url_key: "http://127.0.0.1:14001/v1", "api_key": "${OWNED_TOKEN}",
                "key_env": "OWNED_TOKEN", "extra_headers": {"X-Owned-Key": "${OWNED_HEADER}"}}
    neighbor = {"name": "Other", "api": "http://127.0.0.1:14002/v1", "api_key": "${OTHER_TOKEN}"}
    source = {"model": {"provider": provider, "default": "vendor/owned-model", "max_tokens": 256},
              schema: {"lab": endpoint, "other": neighbor} if schema == "providers" else [endpoint, neighbor]}

    path, copied = create(source)

    assert copied.get("model") == source["model"]
    assert copied.get(schema) == ({"lab": endpoint} if schema == "providers" else [endpoint])
    assert "OTHER_TOKEN" not in (path / "config.yaml").read_text(encoding="utf-8")
    assert "${OWNED_TOKEN}" in (path / "config.yaml").read_text(encoding="utf-8")
    assert "${OWNED_HEADER}" in (path / "config.yaml").read_text(encoding="utf-8")
    assert all(not line.strip() or line.lstrip().startswith("#") for line in (path / ".env").read_text(encoding="utf-8").splitlines())


def test_routing_expands_for_selection_without_expanding_copied_values(launch, monkeypatch):
    _, create = launch
    monkeypatch.setenv("OWNED_PROVIDER", "custom:display-name")
    monkeypatch.setenv("OWNED_NAME", "Display Name")
    monkeypatch.setenv("OWNED_URL", "http://127.0.0.1:14001/v1")
    monkeypatch.setenv("OWNED_TOKEN", "owned-secret-not-for-config")
    endpoint = {"name": "${OWNED_NAME}", "api": "${OWNED_URL}", "api_key": "${OWNED_TOKEN}"}
    source = {"model": {"provider": "${OWNED_PROVIDER}", "default": "owned-model"}, "providers": {"selected": endpoint}}

    path, copied = create(source)

    assert copied.get("model") == source["model"]
    assert copied.get("providers") == source["providers"]
    assert "owned-secret-not-for-config" not in (path / "config.yaml").read_text(encoding="utf-8")


def test_bare_custom_preserves_model_endpoint_key_and_transport(launch):
    _, create = launch
    model = {"provider": "custom", "default": "owned-model", "base_url": "${OWNED_URL}",
             "api_key": "${OWNED_TOKEN}", "api_mode": "chat_completions", "reasoning_effort": "high"}

    _, copied = create({"model": model})

    assert copied.get("model") == model


def test_known_source_secret_is_never_serialized(launch, monkeypatch):
    _, create = launch
    secret = "owned-secret-must-remain-a-reference"
    monkeypatch.setenv("OWNED_TOKEN", secret)
    source = {"model": {"provider": "custom:lab", "default": "owned-model"},
              "providers": {"lab": {"api": "http://127.0.0.1:14001/v1", "api_key": "${OWNED_TOKEN}"}}}

    target, copied = create(source)

    assert secret not in (target / "config.yaml").read_text(encoding="utf-8")
    assert copied["providers"]["lab"]["api_key"] == "${OWNED_TOKEN}"
    assert copied["model"] == source["model"]


def test_builtin_name_does_not_inherit_a_same_named_custom_endpoint(launch):
    _, create = launch
    source = {"model": {"provider": "openrouter", "default": "vendor/owned-model"},
              "providers": {"openrouter": {"request_timeout_seconds": 150}},
              "custom_providers": [{"name": "OpenRouter", "base_url": "http://127.0.0.1:14002/v1"}]}

    _, copied = create(source)

    assert copied.get("model") == source["model"]
    assert copied.get("providers") == source["providers"]
    assert not copied.get("custom_providers")


def test_explicit_clone_keeps_its_model_and_endpoints(launch):
    home, create = launch
    source_dir = home / "profiles" / "configured"
    source_dir.mkdir(parents=True)
    clone = {"model": {"provider": "custom:kept", "default": "kept-model"},
             "providers": {"kept": {"api": "http://127.0.0.1:14003/v1", "api_key": "${KEPT_TOKEN}"}}}
    (source_dir / "config.yaml").write_text(yaml.safe_dump(clone), encoding="utf-8")

    _, copied = create({"model": {"provider": "openrouter", "default": "not-selected"}},
                       clone_from="configured", clone_config=True, no_skills=False)

    assert copied["model"] == clone["model"]
    assert copied["providers"] == clone["providers"]


def test_existing_profile_name_collision_keeps_every_existing_byte(launch):
    home, create = launch
    existing = home / "profiles" / "child"
    existing.mkdir(parents=True)
    snapshots = {"config.yaml": b"model: keep\n", ".env": b"OWNED_TOKEN=keep\n", "auth.json": b"{}\n"}
    for name, value in snapshots.items():
        (existing / name).write_bytes(value)

    with pytest.raises(FileExistsError):
        create({"model": {"provider": "openrouter", "default": "not-selected"}}, name="Child")

    assert {name: (existing / name).read_bytes() for name in snapshots} == snapshots


@pytest.mark.parametrize("provider", ["lab", "custom:lab"])
def test_public_profile_rpc_inherits_endpoint_before_reporting_success(launch, monkeypatch, provider):
    home, _ = launch
    from hermes_cli import profiles
    from hermes_cli.config import DEFAULT_CONFIG, read_user_config_raw
    import tui_gateway.server as server
    monkeypatch.setattr(profiles, "seed_profile_skills", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(profiles, "check_alias_collision", lambda _name: True)
    endpoint = {"name": "Lab Display", "api": "http://127.0.0.1:14001/v1", "api_key": "${OWNED_TOKEN}"}
    source = {"model": {"provider": provider, "default": "vendor/owned-model", "max_tokens": 256},
              "providers": {"lab": endpoint}, "_config_version": DEFAULT_CONFIG["_config_version"]}
    source_path = home / "config.yaml"
    source_path.write_text(yaml.safe_dump(source), encoding="utf-8")
    before = source_path.read_bytes()

    response = server._methods["profiles.create"]("owned-create", {"name": "child", "no_skills": True, "share_auth": True})

    assert "error" not in response, response
    assert response["result"]["mirrored"]["model_inherited"] is True
    copied = read_user_config_raw(Path(response["result"]["path"]) / "config.yaml")
    assert copied["model"] == source["model"]
    assert copied.get("providers") == source["providers"]
    assert source_path.read_bytes() == before


@pytest.mark.parametrize("params", [{"mirror_credentials": False}, {"provider": "openrouter", "model": "owned-pinned"}])
def test_public_profile_rpc_preserves_mirror_opt_out_and_explicit_pin(launch, monkeypatch, params):
    home, _ = launch
    from hermes_cli import profiles
    from hermes_cli.config import DEFAULT_CONFIG, read_user_config_raw
    import tui_gateway.server as server
    monkeypatch.setattr(profiles, "seed_profile_skills", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(profiles, "check_alias_collision", lambda _name: True)
    source = {"model": {"provider": "lab", "default": "vendor/owned-model"},
              "providers": {"lab": {"api": "http://127.0.0.1:14001/v1", "api_key": "${OWNED_TOKEN}"}},
              "_config_version": DEFAULT_CONFIG["_config_version"]}
    (home / "config.yaml").write_text(yaml.safe_dump(source), encoding="utf-8")

    response = server._methods["profiles.create"]("owned-create", {"name": "child", "no_skills": True, **params})

    assert "error" not in response, response
    assert response["result"]["mirrored"]["model_inherited"] is False
    copied = read_user_config_raw(Path(response["result"]["path"]) / "config.yaml")
    assert not copied.get("providers", {}).get("lab")
    if params.get("mirror_credentials") is False:
        assert not copied.get("model")
    else:
        assert copied["model"]["provider"] == "openrouter"
        assert copied["model"]["default"] == "owned-pinned"


def test_seed_selector_uses_only_supplied_config_and_never_reads_credentials(monkeypatch):
    from hermes_cli import profiles, runtime_provider

    def deny(*_args, **_kwargs):
        raise AssertionError("Metadata selection cannot load another config or resolve a credential")

    monkeypatch.setattr(runtime_provider, "load_config", deny)
    monkeypatch.setattr(runtime_provider, "_getenv", deny)
    source = {"model": {"provider": "custom:lab", "default": "owned-model"},
              "providers": {"lab": {"api": "http://127.0.0.1:14001/v1", "api_key": "${OWNED_TOKEN}",
                                    "key_env": "OWNED_TOKEN", "key_cmd": "must-never-run"}}}
    before = deepcopy(source)

    assert profiles._launch_profile_model_seed(source) == source
    assert source == before


@pytest.mark.parametrize("stale", [
    {"providers": {"stale": {"name": "Lab", "api": "http://127.0.0.1:14002/v1"}}},
    {"providers": {"lab": {"request_timeout_seconds": 9}, "stale": {"name": "Lab", "enabled": False}}},
    {"custom_providers": [{"name": "Lab", "base_url": "http://127.0.0.1:14002/v1"}]},
])
def test_endpoint_merge_removes_cross_schema_aliases_but_keeps_unrelated_settings(stale):
    from hermes_cli import profiles, runtime_provider
    seed = {"model": {"provider": "custom:lab", "default": "owned-model"},
            "custom_providers": [{"name": "Lab", "base_url": "http://127.0.0.1:14001/v1", "api_key": "${OWNED_TOKEN}"}]}
    destination = {**deepcopy(stale), "tts": {"provider": "edge"}}
    before = deepcopy(destination)

    merged = profiles._merge_profile_endpoint_seed(destination, seed)

    selected = runtime_provider._get_named_custom_provider("custom:lab", config=merged, resolve_credentials=False)
    assert selected["base_url"] == "http://127.0.0.1:14001/v1"
    assert not merged.get("providers")
    assert merged["custom_providers"] == seed["custom_providers"]
    assert merged["tts"] == {"provider": "edge"}
    assert destination == before


@pytest.mark.parametrize("competing", [
    {"model": {"provider": "openrouter", "default": "concurrent-choice"}},
    {"tts": {"provider": "openai"}},
])
def test_inheritance_reads_destination_after_selecting_source(launch, monkeypatch, competing):
    home, _ = launch
    from hermes_cli import profiles
    from hermes_cli.config import read_user_config_raw, save_config
    from hermes_constants import reset_hermes_home_override, set_hermes_home_override
    target = home / "profiles" / "child"
    target.mkdir(parents=True)
    source = {"model": {"provider": "openrouter", "default": "source-choice"}}
    (home / "config.yaml").write_text(yaml.safe_dump(source), encoding="utf-8")
    select = profiles._launch_profile_model_seed

    def competing_save(config):
        seed = select(config)
        token = set_hermes_home_override(str(target))
        try:
            save_config(competing)
        finally:
            reset_hermes_home_override(token)
        return seed

    monkeypatch.setattr(profiles, "_launch_profile_model_seed", competing_save)
    inherited = profiles.inherit_profile_model(target)
    saved = read_user_config_raw(target / "config.yaml")
    if competing.get("model"):
        assert inherited is False
        assert saved["model"] == competing["model"]
    else:
        assert inherited is True
        assert saved["tts"] == competing["tts"]
        assert saved["model"] == source["model"]


@pytest.mark.parametrize("policy", ["package", "model", "providers", "custom_providers"])
def test_rpc_does_not_claim_inheritance_when_managed_route_refuses_it(launch, monkeypatch, policy):
    home, _ = launch
    from hermes_cli import profiles
    from hermes_cli.config import read_user_config_raw
    import tui_gateway.server as server
    monkeypatch.setattr(profiles, "seed_profile_skills", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(profiles, "check_alias_collision", lambda _name: True)
    source = {"model": {"provider": "lab", "default": "source-choice"},
              "providers": {"lab": {"api": "http://127.0.0.1:14001/v1", "api_key": "${OWNED_TOKEN}"}}}
    (home / "config.yaml").write_text(yaml.safe_dump(source), encoding="utf-8")
    if policy == "package":
        monkeypatch.setenv("HERMES_MANAGED", "true")
    else:
        managed = home.parent / "managed"
        managed.mkdir()
        values = {"model": {"default": "admin-choice"}} if policy == "model" else {
            policy: {"lab": {"api": "http://127.0.0.1:14003/v1"}} if policy == "providers" else [{"name": "Admin"}]}
        (managed / "config.yaml").write_text(yaml.safe_dump(values), encoding="utf-8")
        monkeypatch.setenv("HERMES_MANAGED_DIR", str(managed))

    response = server._methods["profiles.create"]("owned-create", {"name": "child", "no_skills": True, "share_auth": True})

    assert "error" not in response, response
    assert response["result"]["mirrored"]["model_inherited"] is False
    copied = read_user_config_raw(Path(response["result"]["path"]) / "config.yaml")
    assert not copied.get("model")
    assert not copied.get("providers")


def test_inheritance_retains_existing_process_fence_through_canonical_save(launch, monkeypatch):
    import json
    import os
    import subprocess
    import sys
    import time
    from hermes_cli import profiles
    from hermes_cli.config import read_user_config_raw
    import utils
    home, _ = launch
    target = home / "profiles" / "child"
    target.mkdir(parents=True)
    (home / "config.yaml").write_text(yaml.safe_dump({"model": {"provider": "openrouter", "default": "source-choice"}}), encoding="utf-8")
    ready, acquired = home.parent / "ready", home.parent / "acquired"
    competing = {"model": {"provider": "openrouter", "default": "later-explicit-choice"}}
    manifest_path = home.parent / "competing.json"
    manifest_path.write_text(json.dumps({"home": str(target), "ready": str(ready), "acquired": str(acquired), "config": competing}), encoding="utf-8")
    actual_write = utils.atomic_yaml_write
    workers = []

    def observing_write(path, config, **kwargs):
        with (home.parent / "competing.log").open("w", encoding="utf-8") as log:
            worker = subprocess.Popen([sys.executable, "-B", "-m", "tests.hermes_cli.profile_seed_config_worker", str(manifest_path)],
                                      cwd=Path(__file__).resolve().parents[2], env={**os.environ, "HERMES_HOME": str(target)},
                                      stdout=log, stderr=subprocess.STDOUT)
        workers.append(worker)
        deadline = time.monotonic() + 15
        while not ready.exists() and worker.poll() is None and time.monotonic() < deadline:
            time.sleep(0.01)
        assert ready.exists(), "Competing canonical writer never reached the process fence"
        time.sleep(0.15)
        assert not acquired.exists(), "Seed released its process fence before saving"
        return actual_write(path, config, **kwargs)

    monkeypatch.setattr(utils, "atomic_yaml_write", observing_write)
    try:
        assert profiles.inherit_profile_model(target) is True
    finally:
        for worker in workers:
            try:
                worker.wait(timeout=15)
            finally:
                if worker.poll() is None:
                    worker.kill()
                    worker.wait(timeout=5)
    assert len(workers) == 1 and workers[0].returncode == 0
    assert acquired.exists()
    assert json.loads((home.parent / "config-worker-audit.json").read_text(encoding="utf-8"))["violations"] == []
    assert read_user_config_raw(target / "config.yaml")["model"] == competing["model"]
