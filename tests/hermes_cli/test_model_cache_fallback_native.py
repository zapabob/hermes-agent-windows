"""P03 public discovery/cache tests: real parsers, disk, clocks and threads."""
import json
import socket
import threading
import time
import urllib.request
import urllib.parse
from types import SimpleNamespace

import pytest


class Response:
    def __init__(self, payload):
        self.payload = payload

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def read(self):
        return json.dumps(self.payload).encode('utf-8')


@pytest.fixture
def native(tmp_path, monkeypatch):
    from hermes_cli import models, auth, urllib_security
    from hermes_constants import set_hermes_home_override, reset_hermes_home_override
    from providers import ProviderProfile, register_provider, list_providers

    real_open = urllib_security.open_credentialed_url

    home = tmp_path / 'P03 日本語 home'
    home.mkdir()
    for key in ('HERMES_HOME', 'HOME', 'USERPROFILE', 'CODEX_HOME'):
        monkeypatch.setenv(key, str(home))
    scope = set_hermes_home_override(home)
    requests, denied, vendor_rejections, optional_metadata_rejections = [], [], [], []
    state = SimpleNamespace(mode='failure', key='P03-synthetic-key', release=None, entered=None,
                            barrier=None, home_keys=None, transport_scopes=[])
    list_providers()  # Actual discovery before test-owned registrations.
    profiles = []
    for index, name in enumerate(('p03-native-a', 'p03-native-b', 'p03-native-c', 'p03-native-d')):
        # Documentation-only numeric hosts let the real URL floor run
        # without DNS; all connections still terminate at the leaf double.
        profile = ProviderProfile(name=name, base_url=f'https://192.0.2.{101 + index}/v1',
                                  fallback_models=('P03-curated',), env_vars=('P03_TEST_API_KEY',))
        register_provider(profile)
        profiles.append(profile)
    monkeypatch.setenv('P03_TEST_API_KEY', state.key)

    def credentials(provider, **kwargs):
        from hermes_constants import get_hermes_home
        key = (state.home_keys.get(str(get_hermes_home()), state.key)
               if state.home_keys is not None else state.key)
        if provider in ('copilot', 'copilot-acp'):
            return {'api_key': key, 'base_url': models.COPILOT_BASE_URL}
        for p in profiles:
            if provider == p.name:
                return {'api_key': key, 'base_url': p.base_url}
        return {'api_key': '', 'base_url': ''}

    monkeypatch.setattr(auth, 'resolve_api_key_provider_credentials', credentials)

    def transport(req, **kwargs):
        from hermes_constants import get_hermes_home
        url = req.full_url
        allowed = [models.COPILOT_MODELS_URL, 'http://127.0.0.1:41991/api/tags',
                   *(p.base_url + '/models' for p in profiles),
                   *(p.base_url.removesuffix('/v1') + '/models' for p in profiles)]
        if url not in allowed:
            denied.append(url)
            raise AssertionError('unexpected P03 request ' + url)
        requests.append((url, threading.current_thread().name))
        state.transport_scopes.append((str(get_hermes_home()), req.get_header('Authorization'),
                                       threading.current_thread().name))
        if state.barrier is not None:
            state.barrier.wait(10)
        if state.entered is not None:
            state.entered.set()
            assert state.release.wait(10), 'transport release timeout'
        if state.mode == 'failure':
            raise OSError('P03 synthetic transport unavailable')
        if state.mode == 'empty':
            return Response({'models': []} if url.endswith('/api/tags') else {'data': []})
        if url == models.COPILOT_MODELS_URL:
            return Response({'data': [{'id': 'p03-live-chat', 'capabilities': {'type': 'chat'}}]})
        return Response({'data': [{'id': 'p03-live-chat'}, {'id': 'p03-CURATED'}]})

    monkeypatch.setattr(models, '_urlopen_model_catalog_request', transport)
    monkeypatch.setattr(urllib_security, 'open_credentialed_url', transport)

    def refuse_remote_artifact(req, **kwargs):
        url = req.full_url if hasattr(req, 'full_url') else str(req)
        host = urllib.parse.urlsplit(url).hostname or ''
        if ('nous' in host or 'portal' in host or '/NousResearch/' in url
                or 'steward' in host or '/pm/' in url or '/artifacts/' in url):
            vendor_rejections.append(url)
        elif host == 'models.dev' or url == 'https://raw.githubusercontent.com/models-dev/models/main/api.json':
            optional_metadata_rejections.append(url)
        else:
            denied.append(url)
        raise OSError('P03 remote distribution/metadata refused at transport leaf')

    monkeypatch.setattr(urllib.request, 'urlopen', refuse_remote_artifact)

    def deny(*args, **kwargs):
        denied.append(repr(args[:1]))
        raise AssertionError('P03 sockets/DNS forbidden')

    monkeypatch.setattr(socket.socket, 'connect', deny)
    monkeypatch.setattr(socket.socket, 'connect_ex', deny)
    monkeypatch.setattr(socket, 'getaddrinfo', deny)
    # Only transport-memo fixture isolation. No cache owner/time/scheduling double.
    models._github_model_catalog_cache = None
    models._github_model_catalog_cache_key = None
    models._github_model_catalog_cache_time = 0
    models._OLLAMA_LOCAL_MODELS_CACHE.clear()
    models._OLLAMA_LOCAL_PROBE_FAILURE_CACHE.clear()
    models._OLLAMA_LOCAL_PROBE_REACHABLE.clear()
    assert not models._swr_refresh_inflight
    path = home / 'provider_models_cache.json'
    n = SimpleNamespace(mod=models, home=home, path=path, state=state, requests=requests,
                        profiles=profiles, slug=profiles[0].name, denied=denied,
                        real_open=real_open,
                        vendor_rejections=vendor_rejections,
                        optional_metadata_rejections=optional_metadata_rejections)
    try:
        yield n
    finally:
        if state.release is not None:
            state.release.set()
        for worker in list(threading.enumerate()):
            if worker.name.startswith('model-cache-swr-'):
                worker.join(10)
                assert not worker.is_alive()
        assert not models._swr_refresh_inflight
        (home / 'P03-transports.json').write_text(json.dumps({
            'provider_requests': requests, 'refused_vendor_requests': vendor_rejections,
            'observed_transport_scopes': state.transport_scopes,
            'refused_optional_metadata_requests': optional_metadata_rejections,
            'unexpected_requests_or_connections': denied,
        }, indent=2), encoding='utf-8')
        reset_hermes_home_override(scope)
        models._github_model_catalog_cache = None
        assert not denied, denied


def disk(n):
    return json.loads(n.path.read_text(encoding='utf-8'))


def test_real_credentialed_opener_installs_redirect_policy_without_connection(native):
    from hermes_cli.urllib_security import SafeCredentialRedirectHandler

    calls = []

    class Opener:
        def open(self, request, *, timeout):
            calls.append((request.full_url, timeout))
            return Response({'data': []})

    def factory(handler):
        assert isinstance(handler, SafeCredentialRedirectHandler)
        redirected = handler.redirect_request(
            request, None, 302, 'Found', {}, 'https://192.0.2.201/models'
        )
        assert redirected.get_header('Authorization') is None
        return Opener()

    request = urllib.request.Request(
        'https://192.0.2.101/v1/models', headers={'Authorization': 'P03-synthetic-key'}
    )
    with native.real_open(request, timeout=7, opener_factory=factory) as response:
        assert json.loads(response.read()) == {'data': []}
    assert calls == [(request.full_url, 7)]
    assert not native.requests and not native.denied


def seed(n, slug, models, age=0, fallback=False):
    rows = disk(n) if n.path.exists() else {}
    row = {'fp': n.mod._credential_fingerprint(slug), 'at': time.time() - age, 'models': models}
    if fallback:
        row['fallback'] = True
    rows[slug] = row
    n.path.write_text(json.dumps(rows), encoding='utf-8')
    return row


@pytest.mark.parametrize('slug', ['copilot', 'copilot-acp', 'p03-native-a'])
def test_public_raw_failure_retains_provenance_and_curated_order(native, slug):
    n = native
    raw = n.mod.provider_model_ids(slug, force_refresh=True)
    assert isinstance(raw, list) and raw
    assert type(raw).__name__ == 'CuratedFallbackModels'
    expected = (list(n.profiles[0].fallback_models) if slug.startswith('p03-')
                else n.mod._PROVIDER_MODELS['copilot'])
    assert raw == expected
    served = n.mod.cached_provider_model_ids(slug, force_refresh=True)
    assert type(served) is list and served == raw
    assert disk(n)[slug]['fallback'] is True
    assert n.requests


def test_missing_generic_credential_is_degraded_without_probe(native):
    n = native
    n.state.key = ''
    raw = n.mod.provider_model_ids(n.slug)
    assert raw == list(n.profiles[0].fallback_models)
    assert type(raw).__name__ == 'CuratedFallbackModels'
    assert not n.requests


@pytest.mark.parametrize('slug', ['copilot', 'copilot-acp', 'p03-native-a'])
def test_real_clock_aged_disk_placeholder_revalidates_at_61_seconds(native, slug):
    n = native
    seed(n, slug, ['P03-placeholder'], fallback=True)
    assert n.mod.cached_provider_model_ids(slug) == ['P03-placeholder']
    assert not n.requests
    seed(n, slug, ['P03-placeholder'], age=61, fallback=True)
    n.state.mode = 'success'
    result = n.mod.cached_provider_model_ids(slug)
    assert 'p03-live-chat' in result and 'P03-placeholder' not in result
    assert n.requests
    assert not disk(n)[slug].get('fallback')


def test_successful_generic_merge_is_ordinary_and_deduped(native):
    n = native
    n.state.mode = 'success'
    raw = n.mod.provider_model_ids(n.slug)
    assert type(raw) is list
    assert raw == ['P03-curated', 'p03-live-chat']
    n.mod.update_provider_cache_entry(n.slug, raw)
    assert not disk(n)[n.slug].get('fallback')


@pytest.mark.parametrize('writer', ['blocking', 'direct', 'swr'])
def test_fallback_writers_preserve_success_exact_bytes_and_timestamp(native, writer):
    n = native
    n.state.mode = 'success'
    n.mod.cached_provider_model_ids(n.slug, force_refresh=True)
    seed(n, n.slug, ['P03-account-success'], age=7200)
    before = n.path.read_bytes()
    n.state.mode = 'failure'
    if writer == 'direct':
        n.mod.update_provider_cache_entry(n.slug, n.mod.provider_model_ids(n.slug))
    elif writer == 'blocking':
        assert n.mod.cached_provider_model_ids(n.slug, force_refresh=True) == ['P03-account-success']
    else:
        n.state.entered, n.state.release = threading.Event(), threading.Event()
        try:
            assert n.mod.cached_provider_model_ids(n.slug) == ['P03-account-success']
            assert n.state.entered.wait(5)
        finally:
            n.state.release.set()
            for worker in list(threading.enumerate()):
                if worker.name == 'model-cache-swr-' + n.slug:
                    worker.join(10)
                    assert not worker.is_alive()
    assert n.requests
    assert n.path.read_bytes() == before


def test_direct_raw_updater_stores_marker_and_success_removes_it(native):
    n = native
    raw = n.mod.provider_model_ids(n.slug)
    n.mod.update_provider_cache_entry(n.slug, raw)
    assert disk(n)[n.slug]['fallback'] is True
    n.state.mode = 'success'
    n.mod.update_provider_cache_entry(n.slug, n.mod.provider_model_ids(n.slug))
    assert not disk(n)[n.slug].get('fallback')


def test_inflight_failed_transport_cannot_replace_latest_success(native):
    n = native
    n.state.entered, n.state.release = threading.Event(), threading.Event()
    result, errors = [], []
    def failure():
        try:
            result.append(n.mod.cached_provider_model_ids(n.slug, force_refresh=True))
        except BaseException as exc:
            errors.append(exc)
    worker = threading.Thread(target=failure, name='P03-failure-worker')
    worker.start()
    try:
        assert n.state.entered.wait(5)
        n.mod.update_provider_cache_entry(n.slug, ['P03-latest-success'])
        n.mod.update_provider_cache_entry('moa', ['P03-unrelated'])
        before = n.path.read_bytes()
    finally:
        n.state.release.set()
        worker.join(10)
    assert not worker.is_alive() and not errors
    assert result == [['P03-latest-success']]
    assert n.path.read_bytes() == before


def test_changed_real_fingerprint_does_not_protect_old_account(native):
    n = native
    old = seed(n, 'copilot', ['P03-old-account'], age=7200)
    # Existing fingerprint policy includes actual auth.json metadata.
    (n.home / 'auth.json').write_text('{}', encoding='utf-8')
    assert n.mod._credential_fingerprint('copilot') != old['fp']
    result = n.mod.cached_provider_model_ids('copilot', force_refresh=True)
    assert 'P03-old-account' not in result
    assert disk(n)['copilot']['fallback'] is True


def test_static_moa_is_authoritative_without_transport(native):
    n = native
    raw = n.mod.provider_model_ids('moa')
    assert type(raw) is list and raw
    assert n.mod.cached_provider_model_ids('moa') == raw
    assert not disk(n)['moa'].get('fallback')
    assert not n.requests


def test_expired_placeholder_is_not_resurrected_on_empty_discovery(native):
    from dataclasses import replace
    from providers import register_provider
    n = native
    profile = replace(n.profiles[0], fallback_models=())
    register_provider(profile)
    n.profiles[0] = profile
    seed(n, n.slug, ['P03-expired-placeholder'], age=61, fallback=True)
    n.state.mode = 'empty'
    assert n.mod.cached_provider_model_ids(n.slug) == []
    assert n.requests


def test_parallel_public_provider_and_custom_writers_keep_unrelated_rows(native):
    from concurrent.futures import ThreadPoolExecutor
    n = native
    n.state.mode = 'success'
    n.state.barrier = threading.Barrier(4)
    seed(n, 'moa', ['P03-unrelated-success'])
    unchanged = disk(n)['moa']
    slugs = [p.name for p in n.profiles[:3]]
    def discover(index):
        if index == 3:
            return n.mod.cached_fetch_api_models(n.state.key, n.profiles[3].base_url, force_refresh=True)
        return n.mod.cached_provider_model_ids(slugs[index], force_refresh=True)
    with ThreadPoolExecutor(max_workers=4, thread_name_prefix='P03-real-writer') as pool:
        result = list(pool.map(discover, range(4)))
    assert all('p03-live-chat' in row for row in result)
    rows = disk(n)
    assert rows['moa'] == unchanged
    assert all(s in rows for s in slugs)
    assert 'custom:' + n.profiles[3].base_url in rows


@pytest.mark.parametrize('age', [0, 301])
def test_native_ollama_empty_authority_and_short_lifetime(native, age):
    n = native
    (n.home / 'config.yaml').write_text('providers:\n  ollama:\n    base_url: http://127.0.0.1:41991\n', encoding='utf-8')
    seed(n, 'moa', ['P03-unrelated-success'])
    seed(n, 'ollama', [], age=age)
    unchanged = disk(n)['moa']
    n.state.mode = 'empty'
    assert n.mod.cached_provider_model_ids('ollama') == []
    assert bool(n.requests) is bool(age)
    assert disk(n)['ollama']['models'] == []
    assert disk(n)['moa'] == unchanged


def test_custom_cache_only_cannot_serve_expired_fallback(native):
    n = native
    base = n.profiles[0].base_url
    fp = n.mod._custom_endpoint_fingerprint(n.state.key, None, None)
    row = {'fp': fp, 'at': time.time() - 61, 'models': ['P03-placeholder'], 'fallback': True}
    n.path.write_text(json.dumps({'custom:' + base: row}), encoding='utf-8')
    assert n.mod.cached_fetch_api_models(n.state.key, base, cache_only=True) is None
    assert not n.requests


@pytest.mark.parametrize('failure_mode', ['failure', 'empty'])
def test_prefetch_owner_preserves_failed_live_success_timestamp(native, failure_mode):
    from hermes_cli.model_switch import _prefetch_provider_models_parallel
    n = native
    seed(n, n.slug, ['P03-account-success'], age=8 * 24 * 3600)
    before = n.path.read_bytes()
    n.state.mode = failure_mode
    _prefetch_provider_models_parallel([n.slug])
    assert n.requests
    assert n.path.read_bytes() == before


def test_prefetch_does_not_block_on_success_within_swr_tier(native):
    from hermes_cli.model_switch import _prefetch_provider_models_parallel
    n = native
    seed(n, n.slug, ['P03-account-success'], age=7200)
    before = n.path.read_bytes()
    _prefetch_provider_models_parallel([n.slug])
    assert not n.requests
    assert n.path.read_bytes() == before


@pytest.mark.parametrize('slug', ['copilot', 'copilot-acp'])
@pytest.mark.parametrize('writer', ['blocking', 'direct', 'swr'])
def test_copilot_failing_real_transport_preserves_seeded_success(native, slug, writer):
    n = native
    seed(n, slug, ['P03-account-success'], age=7200)
    before = n.path.read_bytes()
    if writer == 'direct':
        n.mod.update_provider_cache_entry(slug, n.mod.provider_model_ids(slug))
    elif writer == 'blocking':
        assert n.mod.cached_provider_model_ids(slug, force_refresh=True) == ['P03-account-success']
    else:
        n.state.entered, n.state.release = threading.Event(), threading.Event()
        try:
            assert n.mod.cached_provider_model_ids(slug) == ['P03-account-success']
            assert n.state.entered.wait(5)
        finally:
            n.state.release.set()
            for worker in list(threading.enumerate()):
                if worker.name == 'model-cache-swr-' + slug:
                    worker.join(10)
                    assert not worker.is_alive()
    assert n.requests
    assert n.path.read_bytes() == before


def test_prefetch_owner_uses_fallback_lifetime_and_keeps_marker(native):
    from hermes_cli.model_switch import _prefetch_provider_models_parallel
    n = native
    seed(n, n.slug, ['P03-placeholder'], age=61, fallback=True)
    _prefetch_provider_models_parallel([n.slug])
    assert n.requests
    assert disk(n)[n.slug]['fallback'] is True


@pytest.mark.parametrize('named_profile', [False, True])
@pytest.mark.parametrize('vendor_manifest_blocked', [False, True])
def test_real_picker_listing_runs_parallel_prefetch_without_relabeling(native, monkeypatch, vendor_manifest_blocked, named_profile):
    from dataclasses import replace
    from providers import get_provider_profile, register_provider
    from hermes_cli import auth
    from hermes_cli.model_switch import list_authenticated_providers
    from hermes_constants import get_hermes_home, set_hermes_home_override, reset_hermes_home_override
    n = native
    ambient = n.home
    ambient_before = None
    ambient_fingerprints = {}
    token = None
    # The real picker enumerates canonical providers; use actual public
    # profile registration for those names and their existing auth registry.
    names = ['arcee', 'gmi', 'novita', 'stepfun']
    originals = [get_provider_profile(name) for name in names]
    n.profiles[:] = [replace(p, name=name) for p, name in zip(n.profiles, names)]
    for p in n.profiles:
        register_provider(p)
        for env in auth.PROVIDER_REGISTRY[p.name].api_key_env_vars:
            monkeypatch.setenv(env, 'P03-synthetic-key')
    if named_profile:
        (ambient / 'auth.json').write_text('{"scope": "ambient"}', encoding='utf-8')
        seed(n, 'moa', ['P03-ambient-control'])
        ambient_before = n.path.read_bytes()
        ambient_fingerprints = {s: n.mod._credential_fingerprint(s) for s in names}
        n.home = ambient / 'profiles' / 'P03 名前付き'
        n.home.mkdir(parents=True)
        (n.home / 'auth.json').write_text('{"scope": "named"}', encoding='utf-8')
        n.path = n.home / 'provider_models_cache.json'
        n.state.home_keys = {str(ambient): 'P03-ambient-key', str(n.home): 'P03-named-key'}
        token = set_hermes_home_override(n.home)
        n.state.mode = 'success'
        n.state.barrier = threading.Barrier(4)
    # Synthetic fresh models.dev fixture read by the real cache/parser.
    metadata = {p.name: {'id': p.name, 'name': p.name, 'env': ['P03_TEST_API_KEY'],
                         'models': {'P03-curated': {'id': 'P03-curated', 'tool_call': True}}}
                for p in n.profiles}
    (n.home / 'models_dev_cache.json').write_text(json.dumps(metadata), encoding='utf-8')
    # Both the disabled control and actual refusal of the enabled optional
    # manifest must leave these bounded public owners usable.
    cfg = ('model_catalog:\n  enabled: true\n  url: https://hermes-agent.nousresearch.com/docs/api/model-catalog.json\n'
           if vendor_manifest_blocked else 'model_catalog:\n  enabled: false\n')
    (n.home / 'config.yaml').write_text(cfg, encoding='utf-8')
    from agent import models_dev
    models_dev._models_dev_cache = None  # Fixture memo isolation only.
    models_dev._models_dev_cache_time = 0
    excluded = [s for s in auth.PROVIDER_REGISTRY if s not in names]
    try:
        from hermes_cli.model_switch import _collect_authed_provider_slugs
        slugs = _collect_authed_provider_slugs(metadata, n.mod._PROVIDER_MODELS, excluded)
        assert len(slugs) > 3, slugs
        rows = list_authenticated_providers(excluded_providers=excluded)
        assert rows
        assert any(name.startswith('model-cache-prefetch') for _, name in n.requests)
        if named_profile:
            scoped = [row for row in n.state.transport_scopes
                      if row[2].startswith('model-cache-prefetch')]
            assert len(scoped) == 4, scoped
            assert all(row[0] == str(n.home) and row[1] == 'Bearer P03-named-key'
                       for row in scoped), scoped
            assert (ambient / 'provider_models_cache.json').read_bytes() == ambient_before
            for s in names:
                assert disk(n)[s]['fp'] == n.mod._credential_fingerprint(s)
                assert disk(n)[s]['fp'] != ambient_fingerprints[s]
                assert not disk(n)[s].get('fallback')
                assert 'p03-live-chat' in disk(n)[s]['models']
            assert get_hermes_home() == n.home
        else:
            assert all(disk(n)[s].get('fallback') is True for s in names)
        # Same public owners complete while vendor artifacts/Portal/PM/steward
        # transports are refused; no simulated manifest success is supplied.
        if vendor_manifest_blocked:
            assert n.vendor_rejections, 'negative control did not attempt blocked artifact'
        n.state.barrier = None
        n.state.mode = 'failure'
        assert n.mod.cached_provider_model_ids('moa')
        assert n.mod.cached_provider_model_ids('copilot')
        assert disk(n)['copilot']['fallback'] is True
        assert not n.denied
    finally:
        n.state.barrier = None
        if token is not None:
            reset_hermes_home_override(token)
        for profile in originals:
            assert profile is not None
            register_provider(profile)
        models_dev._models_dev_cache = None
