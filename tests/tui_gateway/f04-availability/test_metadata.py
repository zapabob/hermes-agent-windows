"""F04b public dispatch effects; all resources belong to the test."""
import importlib
import queue
from dataclasses import fields, replace
from unittest.mock import MagicMock, patch

import pytest

from hermes_cli.commands import CommandDef, COMMAND_REGISTRY, infer_argument_mode


@pytest.fixture
def server(monkeypatch):
    with patch.dict('sys.modules', {'hermes_cli.env_loader': MagicMock(), 'hermes_cli.banner': MagicMock()}):
        mod = importlib.import_module('tui_gateway.server')
    monkeypatch.setattr(mod, '_load_cfg', lambda: {})
    monkeypatch.setattr(mod, '_skill_usage_lookup', lambda: (lambda name: 0, lambda name: 'local'))
    monkeypatch.setattr('agent.skill_commands.scan_skill_commands', lambda: {})
    monkeypatch.setattr('hermes_cli.plugins.get_plugin_commands', lambda: {})
    return mod


def rpc(server, method, params=None):
    responses = queue.Queue()

    class Transport:
        def write(self, response):
            responses.put(response)

    response = server.dispatch({'jsonrpc': '2.0', 'id': 7404, 'method': method,
                                'params': params or {}}, Transport())
    return response if response is not None else responses.get(timeout=10)


def test_append_only_api_and_offered_metadata():
    assert fields(CommandDef)[-1].name == 'desktop'
    from hermes_cli.commands import command_desktop_meta
    assert command_desktop_meta(CommandDef('fixture', 'Fixture', 'Session')) == {
        'argument_mode': None, 'desktop': None}


@pytest.mark.parametrize('disposition', ['hidden', 'terminal', 'messaging', 'advanced', 'settings', 'composer-voice'])
@pytest.mark.parametrize('mode', ['options', 'text', 'mixed'])
def test_wire_preserves_explicit_metadata_and_aliases(server, monkeypatch, disposition, mode):
    # A missing declaration produces a behavioral assertion, not constructor setup failure.
    cmd = CommandDef('f04-test', 'Fixture', 'Session', aliases=('f04-alias',), argument_mode=mode)
    if 'desktop' in {f.name for f in fields(CommandDef)}:
        cmd = replace(cmd, desktop=disposition)
    monkeypatch.setattr('hermes_cli.commands.COMMAND_REGISTRY', [cmd])
    catalog = rpc(server, 'commands.catalog')['result']
    expected = {'argument_mode': mode, 'desktop': disposition}
    assert catalog['commands']['/f04-test'] == expected
    assert catalog['commands']['/f04-alias'] == expected
    assert catalog['canon']['/f04-alias'] == '/f04-test'
    assert ['/f04-test', 'Fixture'] in catalog['pairs']


@pytest.mark.parametrize('name, disposition', [('model', 'hidden'), ('clear', 'terminal'),
    ('approve', 'messaging'), ('deny', 'messaging'), ('fast', 'advanced'), ('voice', 'composer-voice'),
    ('skills', 'settings'), ('snapshot', 'terminal'), ('reload-mcp', 'advanced')])
def test_actual_registry_frozen_upstream_dispositions(server, name, disposition):
    payload = rpc(server, 'commands.catalog')['result']
    assert payload['commands']['/'+name].get('desktop') == disposition
    definition = next(c for c in COMMAND_REGISTRY if c.name == name)
    if definition.gateway_only:
        assert not any(p[0] == '/'+name for p in payload['pairs'])


@pytest.mark.parametrize('name, mode', [('handoff', 'options'), ('goal', 'mixed'),
    ('loop', 'mixed'), ('resume', 'mixed'), ('personality', 'options'), ('skin', 'options'), ('tools', 'options')])
def test_actual_explicit_argument_modes(name, mode):
    assert infer_argument_mode(next(c for c in COMMAND_REGISTRY if c.name == name)) == mode


def test_metadata_does_not_change_cli_gateway_registry_surfaces(monkeypatch):
    import hermes_cli.commands as commands
    original = commands.COMMAND_REGISTRY
    before_cli = dict(commands.COMMANDS)
    before_gateway = commands.gateway_help_lines()
    changed = [replace(c, desktop='hidden') for c in original] if 'desktop' in {f.name for f in fields(CommandDef)} else original
    monkeypatch.setattr(commands, 'COMMAND_REGISTRY', changed)
    assert commands.COMMANDS == before_cli
    for c in commands.COMMAND_REGISTRY:
        assert (('/'+c.name) in commands.COMMANDS) == (not c.gateway_only)
    assert commands.gateway_help_lines() == before_gateway


def test_hidden_metadata_never_grants_session_authority(server, monkeypatch, tmp_path):
    command = CommandDef('f04-hidden', 'Hidden effect', 'Session')
    if 'desktop' in {f.name for f in fields(CommandDef)}:
        command = replace(command, desktop='hidden')
    monkeypatch.setattr('hermes_cli.commands.COMMAND_REGISTRY', [command])
    output = tmp_path / '隠れた操作.txt'

    def effect(arg):
        output.write_text(arg, encoding='utf-8')
        return 'saved'

    monkeypatch.setattr('hermes_cli.plugins.get_plugin_command_handler', lambda name: effect if name == 'f04-hidden' else None)
    assert rpc(server, 'commands.catalog')['result']['commands']['/f04-hidden'].get('desktop') == 'hidden'
    denied = rpc(server, 'slash.exec', {'command': '/f04-hidden denied', 'session_id': 'f04-missing'})
    assert 'error' in denied
    assert not output.exists()
    admitted = rpc(server, 'command.dispatch', {'name': 'f04-hidden', 'arg': '日本語の記録'})
    assert admitted['result'] == {'type': 'plugin', 'output': 'saved'}
    assert output.read_text(encoding='utf-8') == '日本語の記録'
