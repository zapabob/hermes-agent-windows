"""Actual Windows threads and profile-owned JSON cache; controlled refresh/I/O delays, no network."""
import contextvars
import json
import socket
import threading
from pathlib import Path
import pytest


@pytest.fixture
def cache(tmp_path, monkeypatch):
    from hermes_cli import models
    from hermes_constants import set_hermes_home_override, reset_hermes_home_override, get_hermes_home
    home = tmp_path / '起動プロフィール'
    home.mkdir()
    monkeypatch.setenv('HERMES_HOME', str(home))
    monkeypatch.setenv('HOME', str(home))
    monkeypatch.setenv('USERPROFILE', str(home))
    token = set_hermes_home_override(home)
    attempts, threads = [], []
    original = threading.Thread
    class OwnedThread(original):
        def start(self):
            threads.append(self)
            return super().start()
    monkeypatch.setattr(models.threading, 'Thread', OwnedThread)
    def deny(*args, **kwargs):
        attempts.append(str(args[:1]))
        raise AssertionError('upstream runtime and provider access denied')
    monkeypatch.setattr(socket.socket, 'connect', deny)
    monkeypatch.setattr(socket, 'getaddrinfo', deny)
    assert not models._swr_refresh_inflight
    try:
        yield models, home, threads, set_hermes_home_override, reset_hermes_home_override, get_hermes_home
    finally:
        for thread in threads:
            thread.join(10)
            assert not thread.is_alive(), thread.name
        assert not models._swr_refresh_inflight
        reset_hermes_home_override(token)
        assert not attempts, attempts


def entry(name):
    return {'fp': 'owned-fingerprint', 'at': 100.0, 'models': [name]}


def test_background_refresh_keeps_the_calling_profile_after_scope_exit(cache):
    mod, launch, threads, set_home, reset_home, get_home = cache
    profile = launch / 'profiles/仕事'
    profile.mkdir(parents=True)
    release = threading.Event()
    seen = []
    def refresh():
        assert release.wait(5)
        seen.append(get_home())
        return entry('work-model')
    token = set_home(profile)
    try:
        mod._spawn_swr_refresh('owned', refresh)
    finally:
        reset_home(token)
        release.set()
    for thread in threads:
        thread.join(10)
    assert seen == [profile]
    assert json.loads((profile / 'provider_models_cache.json').read_text(encoding='utf-8'))['owned']['models'] == ['work-model']
    assert not (launch / 'provider_models_cache.json').exists()


def test_same_provider_different_profiles_refresh_independently(cache):
    mod, launch, threads, set_home, reset_home, get_home = cache
    release = threading.Event()
    began = [threading.Event(), threading.Event()]
    profiles = [launch / 'profiles/A', launch / 'profiles/B']
    for home in profiles:
        home.mkdir(parents=True)
    def refresh(index):
        began[index].set()
        assert release.wait(5)
        return entry('model-' + str(index))
    try:
        for index, home in enumerate(profiles):
            token = set_home(home)
            try:
                mod._spawn_swr_refresh('same-provider', lambda i=index: refresh(i))
            finally:
                reset_home(token)
        assert all(event.wait(2) for event in began), 'one profile suppressed another profile refresh'
    finally:
        release.set()
        for thread in threads:
            thread.join(10)
    for index, home in enumerate(profiles):
        assert json.loads((home / 'provider_models_cache.json').read_text(encoding='utf-8'))['same-provider']['models'] == ['model-' + str(index)]


def test_repeated_opens_same_profile_have_one_refresh(cache):
    mod, launch, threads, *_ = cache
    release = threading.Event()
    calls = []
    def refresh():
        calls.append('fetch')
        assert release.wait(5)
        return entry('one-model')
    try:
        for _ in range(10):
            mod._spawn_swr_refresh('same-provider', refresh)
        assert len(threads) == 1
    finally:
        release.set()
        for thread in threads:
            thread.join(10)
    assert calls == ['fetch']


def test_concurrent_refreshes_preserve_each_others_latest_disk_rows(cache, monkeypatch):
    mod, home, threads, *_ = cache
    real_load = mod._load_provider_models_cache
    both_read = threading.Event()
    reads = []
    read_lock = threading.Lock()
    def delayed_read():
        snapshot = real_load()
        with read_lock:
            reads.append(snapshot)
            if len(reads) == 2:
                both_read.set()
        # Controlled disk-read delay: unlocked writers can both observe old
        # bytes, while serialized writers get the previous successful write.
        both_read.wait(1)
        return snapshot
    monkeypatch.setattr(mod, '_load_provider_models_cache', delayed_read)
    mod._spawn_swr_refresh('provider-a', lambda: entry('model-a'))
    mod._spawn_swr_refresh('provider-b', lambda: entry('model-b'))
    for thread in threads:
        thread.join(10)
    data = json.loads((home / 'provider_models_cache.json').read_text(encoding='utf-8'))
    assert data['provider-a']['models'] == ['model-a']
    assert data['provider-b']['models'] == ['model-b']


def test_failed_refresh_retains_last_success_and_can_recover(cache):
    mod, home, threads, *_ = cache
    mod._save_provider_models_cache({'provider': entry('last-success')})
    before = (home / 'provider_models_cache.json').read_bytes()
    def failed():
        raise TimeoutError('owned failed refresh')
    mod._spawn_swr_refresh('provider', failed)
    threads[-1].join(10)
    assert (home / 'provider_models_cache.json').read_bytes() == before
    mod._spawn_swr_refresh('provider', lambda: entry('recovered'))
    threads[-1].join(10)
    assert json.loads((home / 'provider_models_cache.json').read_text(encoding='utf-8'))['provider']['models'] == ['recovered']


def test_matching_upstream_lifetimes_do_not_need_new_timers_or_runtime(cache):
    mod, *_ = cache
    from agent import models_dev
    assert models_dev._MODELS_DEV_CACHE_TTL == 4 * 3600
    assert mod._PROVIDER_MODELS_CACHE_TTL == 3600
    assert mod._PROVIDER_MODELS_STALE_SERVE_MAX == 7 * 24 * 3600
    assert mod._OLLAMA_LOCAL_MODELS_CACHE_TTL == 300


def test_custom_catalogue_wrapper_serves_stale_then_updates_only_its_profile(cache, monkeypatch):
    mod, launch, threads, set_home, reset_home, get_home = cache
    import time
    profile = launch / 'profiles/公開一覧'
    profile.mkdir(parents=True)
    url = 'http://127.0.0.1:9/v1'
    fingerprint = mod._custom_endpoint_fingerprint('owned-placeholder', None, None)
    key = 'custom:' + url
    release = threading.Event()
    token = set_home(profile)
    seen = []
    def fetch(*args, **kwargs):
        assert release.wait(5)
        seen.append(get_home())
        return ['new-model']
    monkeypatch.setattr(mod, 'fetch_api_models', fetch)
    try:
        mod._save_provider_models_cache({key: {'fp': fingerprint, 'at': time.time() - mod._PROVIDER_MODELS_CACHE_TTL - 1, 'models': ['old-model']}})
        assert mod.cached_fetch_api_models('owned-placeholder', url) == ['old-model']
        assert not seen, 'interactive catalogue waited for network'
    finally:
        reset_home(token)
        release.set()
        for thread in threads:
            thread.join(10)
    assert seen == [profile]
    assert json.loads((profile / 'provider_models_cache.json').read_text(encoding='utf-8'))[key]['models'] == ['new-model']
    assert not (launch / 'provider_models_cache.json').exists()
