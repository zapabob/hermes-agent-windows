"""Profile-scoped Router contracts through the existing provider entry points."""
from __future__ import annotations

from contextlib import contextmanager
import importlib.util
from pathlib import Path
import sys
import threading
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from hermes_constants import (
    get_hermes_home,
    reset_hermes_home_override,
    set_hermes_home_override,
)


@contextmanager
def profile(home):
    token = set_hermes_home_override(home)
    try:
        yield
    finally:
        reset_hermes_home_override(token)


def catalog(level):
    return [{"id": "shared-model", "router": {"capabilities": {
        "reasoning": {"supported": True, "efforts": [{"value": level}]}
    }}}]


@pytest.fixture
def router_module(monkeypatch, tmp_path):
    name = "_router_scope_adoption_fixture"
    path = Path(__file__).resolve().parents[1] / "plugins/model-providers/router/__init__.py"
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    monkeypatch.setitem(sys.modules, name, module)
    monkeypatch.setenv("HERMES_HOME", str(tmp_path / "launch home"))
    with profile(None), patch("providers.register_provider"):
        spec.loader.exec_module(module)
    return module


def test_reasoning_catalog_is_isolated_between_profile_homes(router_module, tmp_path):
    module = router_module
    a, b = tmp_path / "profile A 日本語", tmp_path / "profile B"
    with profile(a):
        module._seed_efforts(catalog("low"))
    with profile(b):
        module._seed_efforts(catalog("high"))
        assert module.router.supported_reasoning_efforts("shared-model") == ("high",)
    with profile(a):
        assert module.router.supported_reasoning_efforts("shared-model") == ("low",), "Profile B must not overwrite A's capabilities"
    assert (a / "cache/router_catalog.json").is_file()
    assert (b / "cache/router_catalog.json").is_file()


def test_disk_checked_flag_is_per_profile(router_module, tmp_path, monkeypatch):
    module = router_module
    observed = []
    monkeypatch.setattr(module, "_load_disk", lambda: (observed.append(get_hermes_home()) or None, 0.0))
    a, b = tmp_path / "A", tmp_path / "B"
    with profile(a):
        assert module._efforts_cache_only() is None
        assert module._efforts_cache_only() is None
    with profile(b):
        assert module._efforts_cache_only() is None
    assert observed == [a, b], "An empty disk lookup in A must not suppress B's lookup"


def test_warmers_keep_scheduling_context_and_once_flags_per_home(router_module, tmp_path, monkeypatch):
    module = router_module
    monkeypatch.delenv("PYTEST_CURRENT_TEST", raising=False)
    monkeypatch.setattr(module, "_resolve_api_key", lambda: "synthetic-no-network-key")
    release = threading.Event()
    original_thread = threading.Thread
    threads, fetched, saved = [], [], []
    lock = threading.Lock()

    def fetch():
        assert release.wait(5), "Test warmer did not receive release"
        with lock:
            fetched.append(get_hermes_home())
        return catalog("medium")

    def save(items):
        with lock:
            saved.append(get_hermes_home())

    def make_thread(*args, **kwargs):
        thread = original_thread(*args, **kwargs)
        threads.append(thread)
        return thread

    monkeypatch.setattr(module, "_fetch_catalog_items", fetch)
    monkeypatch.setattr(module, "_save_disk", save)
    # Do not mutate the shared threading module: other suite workers may use it.
    monkeypatch.setattr(module, "threading", SimpleNamespace(Thread=make_thread))
    a, b = tmp_path / "warmer A 日本語", tmp_path / "warmer B"
    try:
        with profile(a):
            module._warm_efforts_async()
            module._warm_efforts_async()
        with profile(b):
            module._warm_efforts_async()
        # Both workers finish only after the scheduling scopes have exited.
        release.set()
        for thread in threads:
            thread.join(5)
        assert all(not thread.is_alive() for thread in threads)
        assert len(threads) == 2, "Each profile needs its own once-only warmer"
        assert set(fetched) == {a, b}, "Worker fetch must retain the scheduling profile"
        assert set(saved) == {a, b}, "Worker mirror must retain the scheduling profile"
    finally:
        release.set()
        for thread in threads:
            thread.join(5)


def test_router_endpoint_prefers_scoped_dotenv(router_module, tmp_path, monkeypatch):
    monkeypatch.setenv("RAMP_ROUTER_BASE_URL", "https://launch.invalid/v1")
    with patch("hermes_cli.config.get_env_value_prefer_dotenv", return_value="https://profile.invalid/v1/"):
        with profile(tmp_path / "profile"):
            assert router_module._base_url() == "https://profile.invalid/v1"


def test_legacy_unscoped_cache_slots_remain_supported(router_module, monkeypatch):
    monkeypatch.setattr(router_module, "_efforts_cache", {"shared-model": ["low"]})
    with profile(None):
        assert router_module.router.supported_reasoning_efforts("shared-model") == ("low",)
