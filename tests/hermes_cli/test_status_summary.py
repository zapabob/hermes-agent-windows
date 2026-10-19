"""The default status is useful, bounded and observational."""

import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
from types import SimpleNamespace

import pytest

from hermes_cli import status
from hermes_cli.subcommands.status import build_status_parser


def test_status_parser_accepts_short_and_full_modes():
    parser = argparse.ArgumentParser()
    build_status_parser(parser.add_subparsers(), cmd_status=lambda args: None)
    assert parser.parse_args(["status", "--full"]).full
    assert parser.parse_args(["status", "--short"]).short
    with pytest.raises(SystemExit):
        parser.parse_args(["status", "--full", "--short"])


def test_default_summary_has_core_facts_without_detailed_key_inventory(tmp_path, monkeypatch, capsys):
    from gateway import config as gateway_config
    from hermes_cli import gateway

    monkeypatch.setattr(status, "load_config", lambda: {"model": {"default": "owned-local-model"}})
    monkeypatch.setattr(status, "get_hermes_home", lambda: tmp_path)
    monkeypatch.setattr(status, "_effective_provider_label", lambda: "Custom")
    monkeypatch.setattr(status, "_estop_status_line", lambda: None)
    monkeypatch.setattr(gateway, "get_gateway_runtime_snapshot", lambda: SimpleNamespace(running=True, manager="owned"))
    monkeypatch.setattr(gateway_config, "load_gateway_config", lambda: SimpleNamespace(get_connected_platforms=lambda: []))
    (tmp_path / "cron").mkdir()
    (tmp_path / "cron" / "jobs.json").write_text(json.dumps({"jobs": [{"enabled": True}, {"enabled": False}]}), encoding="utf-8")
    status.show_status(SimpleNamespace())
    output = capsys.readouterr().out
    assert "owned-local-model" in output
    assert "Custom" in output
    assert "Gateway:" in output and "running" in output
    assert "Platforms:" in output
    assert "1 active, 2 total" in output
    assert "--full" in output
    assert "◆ API Keys" not in output
    assert len(output.splitlines()) <= 15


def test_summary_probe_failure_is_unknown_and_keeps_other_rows(tmp_path, monkeypatch, capsys):
    from hermes_cli import gateway

    def failed():
        raise RuntimeError("synthetic observation failure")

    monkeypatch.setattr(status, "load_config", lambda: {"model": "owned-model"})
    monkeypatch.setattr(status, "get_hermes_home", lambda: tmp_path)
    monkeypatch.setattr(status, "_effective_provider_label", lambda: "Custom")
    monkeypatch.setattr(status, "_estop_status_line", lambda: None)
    monkeypatch.setattr(gateway, "get_gateway_runtime_snapshot", failed)
    status.show_status(SimpleNamespace())
    output = capsys.readouterr().out
    assert "owned-model" in output
    assert "Gateway:" in output and "unknown" in output.lower()
    assert "Jobs:" in output


def test_summary_does_not_create_home_or_probe_remote_endpoints(tmp_path, monkeypatch, capsys):
    import socket
    from gateway import config as gateway_config
    from hermes_cli import gateway

    home = tmp_path / "not-created"
    monkeypatch.setattr(status, "get_hermes_home", lambda: home)
    monkeypatch.setattr(status, "load_config", lambda: {"model": {"default": "local", "provider": "custom"}})
    monkeypatch.setattr(status, "_effective_provider_label", lambda: "Custom")
    monkeypatch.setattr(status, "_estop_status_line", lambda: None)
    monkeypatch.setattr(gateway, "get_gateway_runtime_snapshot", lambda: SimpleNamespace(running=False, manager="manual"))
    monkeypatch.setattr(gateway_config, "load_gateway_config", lambda: SimpleNamespace(get_connected_platforms=lambda: []))

    def forbidden(*args, **kwargs):
        pytest.fail("summary must not contact a remote endpoint")

    monkeypatch.setattr(socket, "create_connection", forbidden)
    status.show_status(SimpleNamespace())
    assert not home.exists()
    assert "stopped" in capsys.readouterr().out


def test_public_short_status_in_fresh_process_is_observational(tmp_path):
    home = tmp_path / "cli-home"
    home.mkdir()
    configuration = "model:\n  provider: custom\n  default: owned-local-model\n  base_url: http://127.0.0.1:9/v1\n"
    (home / "config.yaml").write_text(configuration, encoding="utf-8")
    environment = dict(os.environ, HERMES_HOME=str(home), HERMES_TEST_ISOLATION=str(home),
                       PYTHONUTF8="1", PYTHONDONTWRITEBYTECODE="1")
    program = """
import sys
attempts = []
def audit(event, args):
    if event in {'socket.connect', 'socket.getaddrinfo'}:
        attempts.append(event)
        raise RuntimeError('status must not access a network endpoint')
sys.addaudithook(audit)
from hermes_cli.main import main
sys.argv = ['hermes', 'status', '--short']
try:
    main()
except SystemExit as exc:
    if exc.code not in (None, 0):
        raise
assert not attempts, attempts
"""
    result = subprocess.run([sys.executable, "-B", "-c", program],
                            cwd=Path(__file__).resolve().parents[2], env=environment,
                            capture_output=True, text=True, encoding="utf-8", timeout=60)
    assert result.returncode == 0, result.stderr
    assert "owned-local-model" in result.stdout
    assert "Gateway:" in result.stdout
    assert "◆ API Keys" not in result.stdout
    assert (home / "config.yaml").read_text(encoding="utf-8") == configuration
    assert not (home / "cron" / "jobs.json").exists()


@pytest.mark.parametrize("state", [
    "configured", "empty", "corrupt-catalog", "invalid-catalog", "invalid-auth", "unreadable-catalog",
])
def test_summary_lists_connected_provider_names_without_probe(
    state, tmp_path, monkeypatch, capsys,
):
    """Exercise the real local inventory, including a failed catalog read."""
    import yaml

    from hermes_cli import gateway

    configuration = {
        "model": {"provider": "openrouter", "default": "選択中モデル"},
    }
    expected = "none connected"
    if state == "configured":
        configuration["providers"] = {
            "one": {"name": "研究用", "base_url": "http://127.0.0.1:9/v1"},
            "two": {"name": "研究用", "base_url": "http://127.0.0.1:8/v1"},
        }
        monkeypatch.setenv("OPENAI_API_KEY", "synthetic-status-key")
        expected = "OpenAI API, 研究用"
    (tmp_path / "config.yaml").write_text(
        yaml.safe_dump(configuration, allow_unicode=True), encoding="utf-8",
    )
    (tmp_path / "SOUL.md").write_text("User-owned test identity.", encoding="utf-8")
    if state == "corrupt-catalog":
        (tmp_path / "models_dev_cache.json").write_text("{broken", encoding="utf-8")
        expected = "unknown"
    if state == "invalid-catalog":
        (tmp_path / "models_dev_cache.json").write_text(
            json.dumps({"status-test-lab": {"env": "NOT-A-LIST"}}), encoding="utf-8",
        )
        expected = "unknown"
    if state == "invalid-auth":
        (tmp_path / "auth.json").write_text(
            json.dumps({"providers": {"openai-codex": "invalid"}}), encoding="utf-8",
        )
        expected = "unknown"
    if state == "unreadable-catalog":
        import builtins

        cache = tmp_path / "models_dev_cache.json"
        cache.write_text('{"lab": {}}', encoding="utf-8")
        actual_open = builtins.open

        def denied(path, *args, **kwargs):
            if path == cache:
                raise PermissionError("synthetic inaccessible catalog")
            return actual_open(path, *args, **kwargs)

        monkeypatch.setattr(builtins, "open", denied)
        expected = "unknown"
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    monkeypatch.setattr(status, "_effective_provider_label", lambda: "Selected Provider")
    monkeypatch.setattr(status, "_estop_status_line", lambda: None)
    monkeypatch.setattr(gateway, "get_gateway_runtime_snapshot", lambda: SimpleNamespace(running=False))
    before = {p.name: p.read_bytes() for p in tmp_path.iterdir() if p.is_file()}
    status.show_status(SimpleNamespace())
    output = capsys.readouterr().out
    assert f"  Providers:    {expected}\n" in output
    assert "  Provider:     Selected Provider\n" in output
    assert "  Model:        選択中モデル\n" in output
    assert {p.name: p.read_bytes() for p in tmp_path.iterdir() if p.is_file()} == before


@pytest.mark.parametrize("mode", [[], ["--short"]], ids=["default", "short"])
@pytest.mark.parametrize(
    "state", [
        "configured", "empty", "stale-catalog", "mirror-catalog", "corrupt-catalog", "corrupt-auth",
        "bedrock", "profile-fallback",
    ],
)
def test_public_provider_summary_observes_real_local_owners(tmp_path, state, mode):
    """No catalog/network mocks: audit the public CLI and protect local bytes."""
    import yaml
    from hermes_cli.models import provider_label

    root = tmp_path / "owned-root"
    home = root / "profiles" / "research" if state == "profile-fallback" else tmp_path / "cli-home"
    home.mkdir(parents=True)
    (home / "SOUL.md").write_text("User-owned test identity.", encoding="utf-8")
    configuration = {"model": {"provider": "openrouter", "default": "観測用モデル"}}
    environment = dict(os.environ, HERMES_HOME=str(home), HERMES_TEST_ISOLATION=str(home),
                       PYTHONUTF8="1", PYTHONDONTWRITEBYTECODE="1")
    expected_names = []
    if state in {"configured", "stale-catalog", "mirror-catalog"}:
        configuration["providers"] = {
            "alpha": {"name": "研究用", "base_url": "http://127.0.0.1:9/v1"},
            "beta": {"name": "研究用", "base_url": "http://127.0.0.1:8/v1"},
        }
        configuration["custom_providers"] = [
            {"name": "旧形式", "base_url": "http://127.0.0.1:7/v1", "model": "legacy"},
        ]
        environment["OPENAI_API_KEY"] = "synthetic-env-key"
        (home / "auth.json").write_text(json.dumps({
            "version": 1,
            "providers": {"openai-codex": {"access_token": "synthetic-oauth-token"}},
            "credential_pool": {"anthropic": [{"api_key": "synthetic-pool-key"}]},
        }), encoding="utf-8")
        expected_names = [provider_label(slug) for slug in ("openai-api", "openai-codex", "anthropic")]
        expected_names += ["研究用", "旧形式", "Cached Lab"]
        (home / "models_dev_cache.json").write_text(json.dumps({
            "status-test-lab": {"id": "status-test-lab", "name": "Cached Lab",
                                "env": ["STATUS_TEST_LAB_API_KEY"], "models": {}},
        }), encoding="utf-8")
        environment["STATUS_TEST_LAB_API_KEY"] = "synthetic-cached-key"
        if state == "stale-catalog":
            # An old cache must never start a refresh worker.
            os.utime(home / "models_dev_cache.json", (1, 1))
        if state == "mirror-catalog":
            from agent.models_dev import _get_cache_path

            url = "https://example.invalid/status-catalog"
            configuration["models_dev"] = {"url": url}
            mirror_cache = _get_cache_path(home=home, url=url)
            mirror_cache.parent.mkdir()
            mirror_cache.write_bytes((home / "models_dev_cache.json").read_bytes())
            (home / "models_dev_cache.json").write_bytes(b"{unrelated-source-corruption")
    (home / "config.yaml").write_text(yaml.safe_dump(configuration, allow_unicode=True), encoding="utf-8")
    if state == "corrupt-catalog":
        (home / "models_dev_cache.json").write_bytes(b"{broken-catalog")
    if state == "corrupt-auth":
        (home / "auth.json").write_bytes(b"{broken-auth")
    if state == "bedrock":
        environment["AWS_BEARER_TOKEN_BEDROCK"] = "synthetic-aws-bearer"
        expected_names = [provider_label("bedrock")]
    if state == "profile-fallback":
        (root / "auth.json").write_text(json.dumps({
            "credential_pool": {"openai-codex": [{"api_key": "synthetic-root-key"}]},
        }), encoding="utf-8")
        (home / "auth.json").write_text(json.dumps({
            "credential_pool": {"openai-codex": []},
        }), encoding="utf-8")
        expected_names = [provider_label("openai-codex")]
    (home / "cron").mkdir()
    (home / "cron" / "jobs.json").write_bytes(b'{"jobs": [{"enabled": true}, {"enabled": false}]}')
    user_home = tmp_path / "user-home"
    (user_home / ".codex").mkdir(parents=True)
    (user_home / ".codex" / "auth.json").write_bytes(b'{"sentinel": "external-not-for-status"}')
    for key in ("HOME", "USERPROFILE", "APPDATA", "LOCALAPPDATA", "XDG_CONFIG_HOME", "XDG_CACHE_HOME"):
        environment[key] = str(user_home)
    before = {p.relative_to(tmp_path): p.read_bytes() for p in tmp_path.rglob("*") if p.is_file()}
    program = r'''
import json
import os
from pathlib import Path
import sys
import threading

attempts = []
def audit(event, args):
    if event in {'os.rename', 'os.remove'} and 'models_dev' in str(args[0]):
        attempts.append(event)
        raise AssertionError('status must not quarantine/remove catalog files')
    if event == 'open' and str(args[0]).replace('\\', '/').endswith('/.codex/auth.json'):
        attempts.append('external-auth-read')
        raise AssertionError('status must not load external credentials')
    if event in {
        'socket.connect', 'socket.getaddrinfo', 'socket.gethostbyname',
        'socket.gethostbyaddr', 'socket.sendto', 'socket.sendmsg',
        'winreg.SetValue', 'winreg.CreateKey', 'winreg.DeleteKey', 'winreg.DeleteValue',
    }:
        attempts.append(event)
        raise AssertionError('status attempted external I/O: ' + event)
sys.addaudithook(audit)

# Suppress machine repair and external secret loading, as in the owned runner.
# The status/config/auth/catalog implementations themselves stay real.
from hermes_cli import _install_repair, env_loader
_install_repair.ensure_windows_bin_launchers = lambda *a, **kw: None
actual_load = env_loader.load_hermes_dotenv
def owned_load(*, hermes_home=None, project_env=None, load_external_secrets=True):
    return actual_load(hermes_home=Path(os.environ['HERMES_HOME']),
                       project_env=None, load_external_secrets=False)
env_loader.load_hermes_dotenv = owned_load
sys.argv = ['hermes', 'status', *json.loads(sys.argv[1])]
from hermes_cli.main import main
from hermes_cli import status, inventory
root = Path.cwd().resolve()
for module in (status, inventory):
    assert Path(module.__file__).resolve().is_relative_to(root), module.__file__
actual_inventory = inventory.list_connected_provider_names
actual_start = threading.Thread.start
observing_inventory = False
def observed_inventory():
    global observing_inventory
    observing_inventory = True
    previous_profile = sys.getprofile()
    def no_runtime_auth(frame, event, arg):
        if event != 'call':
            return
        module = frame.f_globals.get('__name__', '')
        name = frame.f_code.co_name
        if (module == 'agent.credential_pool' and name == 'load_pool'
                or module.startswith(('boto3', 'botocore', 'azure.identity'))
                or module == 'hermes_cli.auth' and name in {'get_auth_status', '_load_auth_store'}):
            attempts.append('runtime-auth:' + module + ':' + name)
            raise AssertionError('provider inventory must only observe stored auth')
    sys.setprofile(no_runtime_auth)
    try:
        return actual_inventory()
    finally:
        sys.setprofile(previous_profile)
        observing_inventory = False
def no_background(self):
    if observing_inventory:
        attempts.append('thread.start')
        raise AssertionError('provider inventory must not start background work')
    return actual_start(self)
inventory.list_connected_provider_names = observed_inventory
threading.Thread.start = no_background
try:
    main()
except SystemExit as exc:
    if exc.code not in (None, 0):
        raise
assert not attempts, attempts
sys.stdout.write('STATUS_OBSERVATION_AUDIT=' + json.dumps(attempts) + '\n')
'''
    result = subprocess.run([sys.executable, "-B", "-c", program, json.dumps(mode)],
                            cwd=Path(__file__).resolve().parents[2], env=environment,
                            capture_output=True, text=True, encoding="utf-8", timeout=60)
    assert result.returncode == 0, result.stdout + result.stderr
    rows = dict(line.strip().split(":", 1) for line in result.stdout.splitlines()
                if line.startswith("  ") and ":" in line)
    assert "Providers" in rows, result.stdout
    actual = rows["Providers"].strip()
    if expected_names:
        names = actual.split(", ")
        assert set(names) == set(expected_names)
        assert len(names) == len(set(names))
    else:
        assert actual == ("unknown" if state.startswith("corrupt-") else "none connected"), result.stderr
    assert rows["Provider"].strip() == "OpenRouter"
    assert rows["Model"].strip() == "観測用モデル"
    assert rows["Jobs"].strip() == "1 active, 2 total"
    assert "STATUS_OBSERVATION_AUDIT=[]" in result.stdout
    assert "◆ API Keys" not in result.stdout
    assert "synthetic-" not in result.stdout + result.stderr
    after = {
        p.relative_to(tmp_path): p.read_bytes() for p in tmp_path.rglob("*")
        if p.is_file() and not p.is_relative_to(home / "logs")
    }
    assert after == before


def test_provider_inventory_does_not_create_an_absent_home(tmp_path, monkeypatch):
    from hermes_cli.inventory import list_connected_provider_names

    home = tmp_path / "absent-home"
    monkeypatch.setenv("HERMES_HOME", str(home))
    assert list_connected_provider_names() == []
    assert not home.exists()


@pytest.mark.parametrize("provider", ["zai", "kimi-coding", "opencode-zen"])
def test_provider_inventory_keeps_auth_registry_identity(provider, tmp_path, monkeypatch):
    from hermes_cli.inventory import list_connected_provider_names
    from hermes_cli.models import provider_label

    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    (tmp_path / "auth.json").write_text(json.dumps({
        "providers": {provider: {"access_token": "synthetic-stored-token"}},
    }), encoding="utf-8")
    assert list_connected_provider_names() == [provider_label(provider)]


@pytest.mark.parametrize("signals,configured", [
    ({"AWS_BEARER_TOKEN_BEDROCK": "synthetic-bearer"}, True),
    ({"AWS_ACCESS_KEY_ID": "synthetic-id", "AWS_SECRET_ACCESS_KEY": "synthetic-secret"}, True),
    ({"AWS_PROFILE": "owned-profile"}, True),
    ({"AWS_ACCESS_KEY_ID": "partial-id"}, False),
])
def test_provider_inventory_observes_scoped_bedrock_signals(
    tmp_path, monkeypatch, signals, configured,
):
    from agent import secret_scope
    from hermes_cli.inventory import list_connected_provider_names
    from hermes_cli.models import provider_label

    home = tmp_path / "observed-home"
    monkeypatch.setenv("HERMES_HOME", str(home))
    monkeypatch.setattr(secret_scope, "_MULTIPLEX_ACTIVE", True)
    scope = secret_scope.set_secret_scope(signals)
    try:
        assert (provider_label("bedrock") in list_connected_provider_names()) is configured
    finally:
        secret_scope.reset_secret_scope(scope)
    assert not home.exists()


@pytest.mark.parametrize("local_entries", [None, [], [{"api_key": "synthetic-local-key"}]])
def test_provider_inventory_uses_owned_global_pool_fallback_with_profile_precedence(
    tmp_path, monkeypatch, local_entries,
):
    from hermes_cli.inventory import list_connected_provider_names
    from hermes_cli.models import provider_label

    root = tmp_path / "owned-root"
    profile = root / "profiles" / "research"
    profile.mkdir(parents=True)
    monkeypatch.setenv("HERMES_HOME", str(profile))
    # A bad, shadowed global entry must not replace a real profile pool.
    global_entries = "shadowed-invalid" if local_entries else [{"api_key": "synthetic-root-key"}]
    (root / "auth.json").write_text(json.dumps({
        "credential_pool": {"openai-codex": global_entries},
    }), encoding="utf-8")
    pool = {} if local_entries is None else {"openai-codex": local_entries}
    (profile / "auth.json").write_text(json.dumps({"credential_pool": pool}), encoding="utf-8")
    (profile / "config.yaml").write_text("model:\n  provider: openrouter\n", encoding="utf-8")
    before = {p.relative_to(root): p.read_bytes() for p in root.rglob("*") if p.is_file()}
    assert list_connected_provider_names() == [provider_label("openai-codex")]
    assert {p.relative_to(root): p.read_bytes() for p in root.rglob("*") if p.is_file()} == before


@pytest.mark.parametrize("payload", ["{broken", "[]", "{}"])
def test_readonly_catalog_preserves_bytes_and_default_loader_still_quarantines(
    tmp_path, monkeypatch, payload,
):
    from agent.models_dev import _load_disk_cache
    from hermes_cli.models import _xai_curated_models

    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    cache = tmp_path / "models_dev_cache.json"
    cache.write_text(payload, encoding="utf-8")
    etag = cache.with_suffix(".etag")
    etag.write_text("owned-etag", encoding="utf-8")
    before = {p.name: p.read_bytes() for p in tmp_path.iterdir() if p.is_file()}
    with pytest.raises(ValueError):
        _load_disk_cache(read_only=True)
    assert _xai_curated_models()  # useful static fallback, without import-time repair
    assert {p.name: p.read_bytes() for p in tmp_path.iterdir() if p.is_file()} == before
    assert _load_disk_cache() == {}  # the established mutating path retains repair
    assert not cache.exists()
    assert cache.with_suffix(".json.corrupt").read_bytes() == payload.encode("utf-8")
    assert not etag.exists()


@pytest.mark.parametrize("flag", ["full", "all", "deep"])
def test_detailed_status_keeps_its_existing_dispatch(flag, monkeypatch):
    from hermes_cli import inventory

    class DetailedRendererReached(Exception):
        pass

    def unexpected_summary():
        pytest.fail("detailed status must not call the summary inventory")

    def detailed_header(*args):
        raise DetailedRendererReached

    monkeypatch.setattr(inventory, "list_connected_provider_names", unexpected_summary)
    monkeypatch.setattr(status, "color", detailed_header)
    with pytest.raises(DetailedRendererReached):
        status.show_status(SimpleNamespace(**{flag: True}))
