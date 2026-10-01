"""Real registered picker RPC, profile binding and config; catalogue transport is a double."""
from pathlib import Path
import socket
import pytest


@pytest.fixture
def picker(tmp_path, monkeypatch):
    root = tmp_path / '一覧所有プロフィール'
    root.mkdir()
    for name in ['work', 'other']:
        home = root / 'profiles' / name
        home.mkdir(parents=True)
        (home / 'config.yaml').write_text(f'model:\n  provider: openai-compat\n  default: {name}-model\n', encoding='utf-8')
    (root / 'config.yaml').write_text('model:\n  provider: openai-compat\n  default: launch-model\n', encoding='utf-8')
    monkeypatch.setenv('HERMES_HOME', str(root))
    monkeypatch.setenv('HOME', str(root))
    monkeypatch.setenv('USERPROFILE', str(root))
    from hermes_constants import get_hermes_home, get_hermes_home_override
    from hermes_cli import inventory
    import tui_gateway.server as server
    assert get_hermes_home_override() is None
    attempts = []
    def deny(*args, **kwargs):
        attempts.append(str(args[:1]))
        raise AssertionError('test forbids provider and upstream runtime access')
    monkeypatch.setattr(socket.socket, 'connect', deny)
    monkeypatch.setattr(socket, 'getaddrinfo', deny)
    seen = []
    def catalogue(ctx, **kwargs):
        seen.append((get_hermes_home(), ctx.current_model, kwargs))
        return {'model': ctx.current_model, 'provider': ctx.current_provider,
                'providers': [{'slug': ctx.current_provider, 'models': [ctx.current_model]}]}
    monkeypatch.setattr(inventory, 'build_model_options_payload', catalogue)
    monkeypatch.setattr(server, '_sessions', {})
    before = {p: p.read_bytes() for p in root.rglob('config.yaml')}
    yield root, server, seen
    assert get_hermes_home_override() is None
    assert not attempts, attempts
    assert all(p.read_bytes() == data for p, data in before.items())


@pytest.mark.parametrize('profile', ['work', 'other'])
@pytest.mark.parametrize('refresh', [False, True])
def test_registered_picker_uses_requested_profile_and_restores_launch(picker, profile, refresh):
    root, server, seen = picker
    result = server._methods['model.options'](1, {'profile': profile, 'refresh': refresh, 'explicit_only': True})
    assert 'error' not in result, result
    assert result['result']['model'] == profile + '-model'
    assert seen[-1][0] == root / 'profiles' / profile
    assert seen[-1][2]['refresh'] is refresh
    from hermes_constants import get_hermes_home
    assert get_hermes_home() == root
    launch = server._methods['model.options'](2, {'explicit_only': True})
    assert launch['result']['model'] == 'launch-model'


def test_unknown_profile_does_not_fall_back_to_launch(picker):
    root, server, seen = picker
    with pytest.raises((FileNotFoundError, ValueError)):
        server._methods['model.options'](1, {'profile': 'missing'})
    assert not seen


def test_catalogue_failure_restores_profile_context(picker, monkeypatch):
    root, server, seen = picker
    from hermes_cli import inventory
    from hermes_constants import get_hermes_home
    def broken(ctx, **kwargs):
        assert get_hermes_home() == root / 'profiles/work'
        raise RuntimeError('owned catalogue unavailable')
    monkeypatch.setattr(inventory, 'build_model_options_payload', broken)
    reply = server._methods['model.options'](1, {'profile': 'work'})
    assert reply['error']['code'] == 5033, reply
    assert get_hermes_home() == root
