"""Native public plan entry through a scripted provider to real file policies."""
from __future__ import annotations

import logging
import os
from pathlib import Path
import subprocess
import sys

import pytest


@pytest.mark.parametrize("case", ["saved-plan", "protected-config"])
def test_plan_normal_agent_turn_native(tmp_path, case):
    root = Path(__file__).resolve().parents[2]
    assert not (root / ".env").exists()
    workspace = tmp_path / "日本語 workspace"
    workspace.mkdir()
    home = tmp_path / "test-owned-home"
    home.mkdir()
    config = home / "config.yaml"
    config.write_text("model:\n  default: fixture-plan\n", encoding="utf-8")
    sentinel = workspace / "unrelated.txt"
    sentinel.write_text("Keep 日本語\n", encoding="utf-8")
    script = r'''
import copy
import json
import logging
import os
from pathlib import Path
from queue import Queue
import socket
import sys
from types import SimpleNamespace
from unittest.mock import patch

network_attempts = []
def deny_connection(sock, address):
    network_attempts.append(str(address))
    raise AssertionError('The native plan fixture cannot connect to a network')
socket.socket.connect = deny_connection
socket.socket.connect_ex = deny_connection
original_getaddrinfo = socket.getaddrinfo
def owned_resolution(host, port, *args, **kwargs):
    if host not in ('127.0.0.1', '::1', 'localhost'):
        network_attempts.append(str((host, port)))
        raise AssertionError('The native plan fixture cannot resolve external hosts')
    return original_getaddrinfo(host, port, *args, **kwargs)
socket.getaddrinfo = owned_resolution

import cli
from agent.plan_prompt import build_plan_prompt
from openai.types.chat import ChatCompletion
from run_agent import AIAgent

case = sys.argv[1]
workspace = Path.cwd()
home = Path(os.environ['HERMES_HOME'])
config = home/'config.yaml'
original_config = config.read_bytes()
sentinel = workspace/'unrelated.txt'
original_sentinel = sentinel.read_bytes()
target = workspace/'.hermes/plans/2026-10-01_000000-fixture.md' if case == 'saved-plan' else config
content = '# Fixture plan\n\n日本語の計画。実装しない。\n'

instance = cli.HermesCLI.__new__(cli.HermesCLI)
instance.config = {}
instance.agent = None
instance.model = 'fixture-plan'
instance.session_id = 'owned-plan-native'
instance._pending_input = Queue()
with patch('hermes_cli.plugins.fire_pre_command_hook'), patch.object(cli, '_ensure_skill_commands', return_value={}), patch.object(cli, 'get_skill_bundles', return_value={}), patch.object(cli, '_get_plugin_cmd_handler_names', return_value=set()):
    assert instance.process_command('/plan Preserve 日本語 Case') is True
prompt = instance._pending_input.get_nowait()
assert prompt == build_plan_prompt('Preserve 日本語 Case')
assert instance._pending_input.empty()

calls = []
tool_results = []
def completion(**kwargs):
    calls.append(copy.deepcopy(kwargs))
    if len(calls) == 1:
        user_content = [m.get('content') for m in kwargs['messages'] if m.get('role') == 'user']
        assert any(prompt.strip() in str(value) for value in user_content), {'user_content':user_content,'prompt_length':len(prompt)}
        message = {'role':'assistant','content':None,'tool_calls':[{'id':'owned-write','type':'function','function':{'name':'write_file','arguments':json.dumps({'path':str(target),'content':content},ensure_ascii=False)}}]}
        finish = 'tool_calls'
    else:
        assert len(calls) == 2, 'Unexpected extra scripted completion'
        tool_results.extend(m for m in kwargs['messages'] if m.get('role') == 'tool')
        assert tool_results, 'The real agent did not execute the tool request'
        result = json.loads(tool_results[-1]['content'])
        if case == 'saved-plan':
            assert not result.get('error'), result
        else:
            assert 'security-sensitive configuration' in str(result.get('error')), result
        message = {'role':'assistant','content':'Saved fixture plan.' if case == 'saved-plan' else 'Protected configuration write was denied.'}
        finish = 'stop'
    return ChatCompletion.model_validate({'id':'fixture-completion','object':'chat.completion','created':0,'model':'fixture-plan','choices':[{'index':0,'message':message,'finish_reason':finish}],'usage':{'prompt_tokens':1,'completion_tokens':1,'total_tokens':2}})
client = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=completion)),base_url='http://127.0.0.1:9/v1',close=lambda:None)
with patch('run_agent.OpenAI',lambda **kwargs:client):
    agent = AIAgent(model='fixture-plan',provider='openai-compat',api_mode='chat_completions',api_key='test-owned-placeholder',base_url='http://127.0.0.1:9/v1',enabled_toolsets=['file'],max_iterations=3,quiet_mode=True,skip_memory=True,skip_context_files=True,save_trajectories=False,platform='cli',session_id='owned-plan-native')
    selected_model = agent.model
    result = agent.run_conversation(prompt,conversation_history=[],task_id='owned-plan-native-turn')
    assert agent.model == selected_model
assert len(calls) == 2
assert config.read_bytes() == original_config
assert sentinel.read_bytes() == original_sentinel
assert not (workspace/'state.db').exists()
if case == 'saved-plan':
    assert target.read_text(encoding='utf-8') == content
    assert len(list((workspace/'.hermes/plans').iterdir())) == 1
else:
    assert not (workspace/'.hermes/plans').exists()
assert all(tc['function']['name']=='write_file' for request in calls for message in request['messages'] for tc in message.get('tool_calls',[]))
proof_logger = logging.getLogger('owned.plan.proof')
proof_logger.disabled = False
proof_logger.setLevel(logging.INFO)
proof_logger.propagate = False
proof_logger.addHandler(logging.StreamHandler(sys.stderr))
proof_logger.info('NATIVE_PLAN_EFFECT_OK %s denied_network_attempts=%s', case, len(network_attempts))
'''
    env = {key: value for key, value in os.environ.items() if key.upper() in
           {"SYSTEMROOT", "WINDIR", "COMSPEC", "PATH", "PATHEXT", "TEMP", "TMP"}}
    env.update(HERMES_HOME=str(home), HOME=str(home), USERPROFILE=str(home),
               PYTHONPATH=str(root), PYTHONUTF8="1", PYTHONIOENCODING="utf-8")
    result = subprocess.run([sys.executable, "-c", script, case], cwd=workspace, env=env,
                            encoding="utf-8", capture_output=True, timeout=90)
    assert result.returncode == 0, result.stdout + result.stderr
    assert "NATIVE_PLAN_EFFECT_OK " + case in result.stderr
    logging.getLogger(__name__).warning(
        "%s", next(line for line in result.stderr.splitlines() if "NATIVE_PLAN_EFFECT_OK " in line)
    )
