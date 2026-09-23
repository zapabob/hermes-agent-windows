"""Read-path contracts exercise real temporary files and the existing config owner."""
from copy import deepcopy
import json
from pathlib import Path
import time

import pytest


def peeker():
    from hermes_cli import config
    fn = getattr(config, 'peek_effective_config', None)
    if fn is None:
        pytest.fail('Side-effect-free effective config snapshot is not implemented', pytrace=False)
    return config, fn


def test_cold_config_observation_never_creates_or_loads(tmp_path, monkeypatch):
    config, peek = peeker()
    path = tmp_path / 'nonexistent-home' / 'config.yaml'
    def forbidden(*a, **kw):
        raise AssertionError('Observation invoked a creating/config-loading helper')
    monkeypatch.setattr(config, 'ensure_hermes_home', forbidden)
    monkeypatch.setattr(config, 'load_config', forbidden)
    monkeypatch.setattr(config, '_load_config_impl', forbidden)
    assert peek(path) is None
    assert not path.parent.exists()


def test_config_peek_is_a_copy_and_rejects_stale_or_env_drift(tmp_path, monkeypatch):
    config, peek = peeker()
    from hermes_cli import managed_scope
    monkeypatch.setattr(managed_scope, 'get_managed_dir', lambda: None)
    path = tmp_path / 'config.yaml'
    path.write_text('auxiliary: {}', encoding='utf-8')
    st = path.stat()
    expected = {'auxiliary': {'engineering_worker': {'provider': 'fixture', 'model': 'worker'}}}
    cache = {str(path): (st.st_mtime_ns, st.st_size, 0, 0, deepcopy(expected), {'CONTROL_TEST_VAR': 'a'})}
    monkeypatch.setattr(config, '_LOAD_CONFIG_CACHE', cache)
    monkeypatch.setenv('CONTROL_TEST_VAR', 'a')
    result = peek(path)
    assert result == expected
    result['auxiliary'].clear()
    assert cache[str(path)][4] == expected
    monkeypatch.setenv('CONTROL_TEST_VAR', 'b')
    assert peek(path) is None
    monkeypatch.setenv('CONTROL_TEST_VAR', 'a')
    path.write_text('auxiliary: {changed: true}', encoding='utf-8')
    assert peek(path) is None


def make_source(control_module, tmp_path, **kwargs):
    return control_module('observations').HermesObservations(
        homes={'p1': tmp_path / 'p1', 'p2': tmp_path / 'p2'},
        registered_slots=('engineering_worker',), **kwargs)


def test_routes_cold_cache_is_unknown_not_empty_success(control_module, tmp_path):
    source = make_source(control_module, tmp_path)
    result = source.routes('p1')
    assert result['state'] == 'UNKNOWN'
    assert result['reason'] == 'config_not_observed'
    assert not (tmp_path / 'p1').exists()


def test_runtime_projection_excludes_tokens_paths_and_unsupported_claims(control_module, tmp_path):
    home = tmp_path / 'p1'
    home.mkdir()
    status = {'updated_at': '2026-09-23T00:00:00Z', 'pid': 12, 'status': 'running',
              'api_key': 'SYNTHETIC-SECRET', 'path': 'C:/private/vault', 'active_agents': 3}
    (home / 'gateway_state.json').write_text(json.dumps(status), encoding='utf-8')
    source = make_source(control_module, tmp_path)
    result = source.runtime('p1')
    assert result['state'] == 'STALE'
    assert result['process_ownership'] == 'UNKNOWN'
    assert 'SYNTHETIC' not in json.dumps(result)
    assert 'C:/private' not in json.dumps(result)
    assert result['producer_observed_at'] == status['updated_at']


def test_missing_and_malformed_runtime_are_not_stopped(control_module, tmp_path):
    source = make_source(control_module, tmp_path)
    assert source.runtime('p1')['state'] == 'ABSENT'
    assert not (tmp_path / 'p1').exists()
    (tmp_path / 'p1').mkdir()
    (tmp_path / 'p1' / 'gateway_state.json').write_bytes(b'\xffbroken')
    assert source.runtime('p1')['state'] == 'UNKNOWN'


def test_directory_and_legacy_stage_event_do_not_prove_live_run(control_module, tmp_path):
    source = make_source(control_module, tmp_path)
    run = tmp_path / 'p1' / 'plugin-data' / 'implementation_router' / ('eng-' + 'a'*32)
    run.mkdir(parents=True)
    (run / 'events.jsonl').write_text('{"kind":"stage_start"}\n', encoding='utf-8')
    result = source.run('p1', run.name)
    assert result['state'] == 'UNKNOWN'
    assert result['reason'] == 'live_owner_not_observed'
    assert source.evidence('p1', run.name)['state'] == 'UNSUPPORTED'


@pytest.mark.parametrize('identifier', ['../auth', 'a/b', r'a\b', 'C:stream', 'eng-a:secret', 'CON', '%SystemDrive%'])
def test_evidence_only_accepts_producer_run_ids(control_module, tmp_path, identifier):
    source = make_source(control_module, tmp_path)
    with pytest.raises(control_module('contracts').ControlError):
        source.evidence('p1', identifier)


def test_run_directory_symlink_is_rejected(control_module, tmp_path):
    source = make_source(control_module, tmp_path)
    parent = tmp_path / 'p1' / 'plugin-data' / 'implementation_router'
    parent.mkdir(parents=True)
    elsewhere = tmp_path / 'private'
    elsewhere.mkdir()
    try:
        (parent / ('eng-' + 'a'*32)).symlink_to(elsewhere, target_is_directory=True)
    except OSError:
        pytest.skip('Symlink privilege not available on this host')
    with pytest.raises(control_module('contracts').ControlError):
        source.run('p1', 'eng-' + 'a'*32)


def test_read_authorisation_precedes_observation(control_module, control_context, tmp_path):
    class Tripwire:
        def routes(self, *a):
            raise AssertionError('Unauthorised source access')
    service = control_module('service').HostControlService(source=Tripwire(), clock=lambda: 100)
    with pytest.raises(control_module('contracts').ControlError) as caught:
        service.read(control_context(), 'hermes_get_routes', {'profile_id': 'p2'})
    assert caught.value.code == 'resource_denied'


def test_capabilities_do_not_advertise_unwired_writes(control_module, control_context, tmp_path):
    service = control_module('service').HostControlService(source=make_source(control_module, tmp_path), clock=lambda:100)
    result = service.read(control_context(), 'hermes_get_capabilities', {'profile_id': 'p1'})
    assert result['schema_version'] == 1
    assert result['capabilities']['read'] is True
    assert result['capabilities']['write'] is False
    assert result['capabilities']['resume'] is False
    assert result['producer_epoch']


@pytest.mark.parametrize('extra', [{'approved':True}, {'path':'/etc/passwd'}, {'client_name':'human'}, {'profile':'p2'}])
def test_read_schema_rejects_authority_arguments(control_module, control_context, tmp_path, extra):
    service = control_module('service').HostControlService(source=make_source(control_module, tmp_path), clock=lambda:100)
    with pytest.raises(control_module('contracts').ControlError) as caught:
        service.read(control_context(), 'hermes_get_runtime_status', {'profile_id':'p1', **extra})
    assert caught.value.code == 'invalid_request'


def test_run_read_requires_workspace_grant(control_module, control_context, tmp_path):
    service = control_module('service').HostControlService(source=make_source(control_module,tmp_path), clock=lambda:100)
    with pytest.raises(control_module('contracts').ControlError) as caught:
        service.read(control_context(), 'hermes_get_run', {'profile_id':'p1', 'workspace_id':'w2','run_id':'eng-'+'a'*32})
    assert caught.value.code == 'resource_denied'


def test_event_gap_is_explicit_without_owner_feed(control_module, control_context, tmp_path):
    service = control_module('service').HostControlService(source=make_source(control_module,tmp_path), clock=lambda:100)
    result = service.read(control_context(),'hermes_poll_events',{'profile_id':'p1','after_cursor':99,'producer_epoch':'old'})
    assert result['state'] == 'UNSUPPORTED'
    assert result['gap'] is True
    assert result['events'] == []
