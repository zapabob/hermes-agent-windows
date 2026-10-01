"""F11 owned Windows JSONL acceptance; transport/construction doubles only.

No reference-tree runtime imports. Emitter cases exercise the public sink;
subprocess cases use argparse -> cmd_chat -> cli.main -> ordinary AIAgent.
Formal runtime execution is coordinated by the parent after F12 is frozen.
"""
from __future__ import annotations

import importlib
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
from types import SimpleNamespace

import pytest


def _module():
    assert importlib.util.find_spec("hermes_cli.stream_json") is not None, "API_UNAVAILABLE stream_json"
    return importlib.import_module("hermes_cli.stream_json")


def _events(capsys):
    captured = capsys.readouterr()
    return [json.loads(line) for line in captured.out.splitlines()], captured.err


def test_public_stream_api_absence_is_separate():
    module = _module()
    assert callable(getattr(module, "StreamJsonEmitter", None)), "MISSING_API StreamJsonEmitter"
    assert callable(getattr(module, "stream_json_requested", None)), "MISSING_API stream_json_requested"


@pytest.mark.parametrize("delta", ["日本語🐈", " ", "\n", "\t", "a\n b"])
def test_exact_delta_json_line(delta, capsys):
    emitter = _module().StreamJsonEmitter(model="所有モデル", session_id="所有SID")
    emitter.on_text_delta(delta)
    events, error = _events(capsys)
    assert [(e["type"], e.get("text")) for e in events] == [("system", None), ("text", delta)]
    assert events[0]["subtype"] == "init"
    assert events[0]["model"] == "所有モデル"
    assert events[0]["session_id"] == "所有SID"
    assert all(isinstance(e["timestamp"], int) for e in events)
    assert not error


def test_empty_and_none_delta_are_sentinels(capsys):
    emitter = _module().StreamJsonEmitter()
    emitter.on_text_delta(None)
    emitter.on_text_delta("")
    events, _ = _events(capsys)
    assert [e["type"] for e in events] == ["system"]


@pytest.mark.parametrize("size", [4999, 5000, 5001])
def test_tool_output_cap_and_identity(size, capsys):
    emitter = _module().StreamJsonEmitter()
    arguments = {"path": "所有/日本語.txt", "content": "\n猫 "}
    emitter.on_tool_progress("tool.started", "write_file", args=arguments, tool_call_id="call-日本語")
    emitter.on_tool_progress("tool.completed", "write_file", result="猫" * size,
                             duration=0.125, is_error=True, tool_call_id="call-日本語")
    events, _ = _events(capsys)
    use, result = events[1:]
    assert use == {**use, "type": "tool_use", "name": "write_file", "input": arguments,
                   "tool_call_id": "call-日本語"}
    assert result["type"] == "tool_result" and result["tool_call_id"] == use["tool_call_id"]
    assert result["output"] == "猫" * min(size, 5000) + ("..." if size > 5000 else "")
    assert result["is_error"] is True
    assert result["duration_ms"] == 125


def test_parallel_same_name_timing_is_by_call_id(monkeypatch, capsys):
    module = _module()
    clock = [10.0]
    monkeypatch.setattr(module.time, "time", lambda: clock[0])
    emitter = module.StreamJsonEmitter()
    emitter.on_tool_progress("tool.started", "read_file", tool_call_id="A")
    clock[0] = 11.0
    emitter.on_tool_progress("tool.started", "read_file", tool_call_id="B")
    clock[0] = 13.0
    emitter.on_tool_progress("tool.completed", "read_file", tool_call_id="A", result="first")
    clock[0] = 15.0
    emitter.on_tool_progress("tool.completed", "read_file", tool_call_id="B", result="second")
    events, _ = _events(capsys)
    assert [(e["tool_call_id"], e["duration_ms"]) for e in events if e["type"] == "tool_result"] == [("A", 3000), ("B", 4000)]


@pytest.mark.parametrize("event", ["reasoning", "tool.output_risk", "tool.progress"])
def test_nonprotocol_progress_is_ignored(event, capsys):
    emitter = _module().StreamJsonEmitter()
    emitter.on_tool_progress(event, "read_file", result="must not appear")
    events, _ = _events(capsys)
    assert [e["type"] for e in events] == ["system"]


@pytest.mark.parametrize("data,exit_code", [
    ({"final_response": "猫\n ", "input_tokens": 7, "output_tokens": 3, "total_tokens": 10,
      "cache_read_tokens": 2, "cache_write_tokens": 1}, 0),
    ({"failed": True, "error": "所有 provider failure"}, 1),
    ("日本語 final", 0),
])
def test_terminal_result_fields(data, exit_code, capsys):
    emitter = _module().StreamJsonEmitter(session_id="parent")
    assert emitter.emit_result(data, session_id="continuation") == exit_code
    events, error = _events(capsys)
    result = events[-1]
    assert result["type"] == "result"
    assert result["session_id"] == "continuation" and result["exit_code"] == exit_code
    assert isinstance(result["duration_ms"], int) and result["duration_ms"] >= 0
    assert result["tokens"] == ({"input": 7, "output": 3, "total": 10, "cache_read": 2, "cache_write": 1}
                               if isinstance(data, dict) and "input_tokens" in data else
                               {"input": 0, "output": 0, "total": 0, "cache_read": 0, "cache_write": 0})
    assert result["text"] == (data.get("final_response", "") if isinstance(data, dict) else data)
    if isinstance(data, dict) and data.get("error"):
        assert result["error"] == data["error"]
    assert "session_id: continuation" in error


def test_terminal_result_emitted_once(capsys):
    emitter = _module().StreamJsonEmitter(session_id="owned")
    emitter.emit_result({"final_response": "first"})
    emitter.emit_result({"final_response": "second"})
    events, _ = _events(capsys)
    assert [e["text"] for e in events if e["type"] == "result"] == ["first"]


def test_attach_callbacks_use_actual_sink(capsys):
    agent = SimpleNamespace(stream_delta_callback=None, tool_progress_callback=None)
    emitter = _module().StreamJsonEmitter()
    assert emitter.attach(agent) is emitter
    agent.stream_delta_callback("猫")
    agent.tool_progress_callback("tool.started", "read_file", args={"path": "owned"}, tool_call_id="X")
    events, _ = _events(capsys)
    assert [e["type"] for e in events] == ["system", "text", "tool_use"]


@pytest.mark.parametrize("argv", [
    ["chat", "--format", "stream-json"],
    ["chat", "-q", "猫", "--format", "stream-json", "--tui"],
    ["chat", "-q", "猫", "--format", "invalid"],
])
def test_invalid_public_invocations_exit_two(argv, capsys):
    from hermes_cli._parser import build_top_level_parser
    built = build_top_level_parser()
    parser = built[0] if isinstance(built, tuple) else built
    with pytest.raises(SystemExit) as exc:
        args = parser.parse_args(argv)
        _module().stream_json_requested(args)
    assert exc.value.code == 2
    assert capsys.readouterr().out == ""


_PUBLIC_SCRIPT = r'''
import copy, json, os, socket, sys, threading
from contextlib import ExitStack
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
network_attempts = []
def deny(*args, **kwargs):
    network_attempts.append(repr(args))
    raise AssertionError('F11 owned test cannot use socket/DNS')
socket.socket.connect = deny
socket.socket.connect_ex = deny
socket.getaddrinfo = deny
import cli, run_agent, openai
from hermes_cli import main as entry
from hermes_cli._parser import build_top_level_parser
from openai.types.chat import ChatCompletion, ChatCompletionChunk
from hermes_state import SessionDB
import tools.file_tools
from tools.registry import registry
definitions = [{'type':'function','function':registry.get_schema('write_file')}]
assert definitions[0]['function'] is not None
case = sys.argv[1]
home = Path(os.environ['HERMES_HOME'])
config = home/'config.yaml'
original_config = config.read_bytes()
target = config if case == 'deny' else Path.cwd()/'所有 output.txt'
body = '猫の本文\nsecond line\n'
final = '日本語\n 完了 '
calls = []
observed_final_text = []
def completion(**kwargs):
    calls.append(copy.deepcopy(kwargs))
    if case == 'provider-error':
        raise RuntimeError('owned scripted provider failure')
    tool_turn = len(calls) == 1 and case in ('write', 'deny')
    message = {'role':'assistant', 'content':None, 'tool_calls':[{'id':'owned-file-call',
        'type':'function', 'function':{'name':'write_file', 'arguments':json.dumps(
        {'path':str(target), 'content':body}, ensure_ascii=False)}}]} if tool_turn else {'role':'assistant','content':final}
    finish = 'tool_calls' if tool_turn else 'stop'
    if len(calls) > 1 and case in ('write','deny'):
        results = [m for m in kwargs['messages'] if m.get('role') == 'tool']
        assert results and results[-1]['tool_call_id'] == 'owned-file-call'
        payload = json.loads(results[-1]['content'])
        assert ('security-sensitive configuration' in str(payload.get('error'))) if case == 'deny' else not payload.get('error'), payload
    if kwargs.get('stream'):
        chunks = []
        if tool_turn:
            delta = {'role':'assistant','tool_calls':[{'index':0, **message['tool_calls'][0]}]}
            chunks.append({'index':0,'delta':delta,'finish_reason':None})
        else:
            for text in ('日本語', '\n', ' ', '完了', ' '):
                chunks.append({'index':0,'delta':{'content':text},'finish_reason':None})
        chunks.append({'index':0,'delta':{},'finish_reason':finish})
        response = [ChatCompletionChunk.model_validate({'id':'owned-f11','object':'chat.completion.chunk',
            'created':0,'model':'fixture-f11','choices':[chunk]}) for chunk in chunks]
        response.append(ChatCompletionChunk.model_validate({'id':'owned-f11','object':'chat.completion.chunk',
            'created':0,'model':'fixture-f11','choices':[], 'usage':{'prompt_tokens':7,'completion_tokens':3,'total_tokens':10}}))
        return iter(response)
    return ChatCompletion.model_validate({'id':'owned-f11','object':'chat.completion','created':0,
        'model':'fixture-f11','choices':[{'index':0,'message':message,'finish_reason':finish}],
        'usage':{'prompt_tokens':7,'completion_tokens':3,'total_tokens':10}})
client = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=completion)),
    base_url='http://127.0.0.1:9/v1',close=lambda:None)
db = SessionDB(db_path=home/'state.db')
class OwnedCLI:
    def __init__(self, **kwargs):
        self.model='fixture-f11'; self.provider='openai-compat'; self.requested_provider='openai-compat'
        self.session_id='owned-f11-session'; self.conversation_history=[]; self.agent=None
        self._active_agent_route_signature='owned-route'; self.ignore_rules=True
        self._session_db=db; self.system_prompt=''; self.config={}
    def _claim_active_session(self, surface, *, stderr=False): return True
    def _release_active_session(self): pass
    def _ensure_runtime_credentials(self):
        if case != 'plain':
            observed = [json.loads(line) for line in out.getvalue().splitlines()]
            assert observed and observed[0]['type']=='system' and observed[0]['subtype']=='init', 'init must precede credential boundary'
        if case == 'interrupt':
            assert threading.current_thread() is threading.main_thread()
            raise KeyboardInterrupt()
        return case != 'credentials-fail'
    def _resolve_turn_agent_config(self, query):
        return {'signature':'owned-route','model':None,'runtime':None,'request_overrides':None}
    def _init_agent(self, **kwargs):
        if case=='init-fail': return False
        with patch.object(run_agent,'get_tool_definitions',return_value=definitions), patch.object(run_agent,'check_toolset_requirements',return_value={}), patch('hermes_cli.plugins.discover_plugins',return_value=None):
            self.agent=run_agent.AIAgent(model=self.model,provider=self.provider,api_mode='chat_completions',
                api_key='test-owned-placeholder',base_url=client.base_url,enabled_toolsets=['file'],
                max_iterations=3,quiet_mode=True,skip_memory=True,skip_context_files=True,
                save_trajectories=False,platform='cli',session_id=self.session_id)
        self.agent._session_db=db
        original_bound_run = self.agent.run_conversation
        def observe_original_run(*args, **kwargs):
            assert not observed_final_text, 'CLI must invoke the ordinary agent once'
            result = original_bound_run(*args, **kwargs)
            observed_final_text.append(result.get('final_response') if isinstance(result, dict) else str(result))
            return result
        self.agent.run_conversation = observe_original_run
        return True
import io
out, err = io.StringIO(), io.StringIO()
query='write owned 日本語'
argv=['chat','-q',query,'--quiet','--ignore-rules']
if case!='plain': argv += ['--format','stream-json']
if case=='query-file':
    qfile=Path.cwd()/'日本語 query.txt'
    query='日本語 "quotes" $(not-executed) `literal`\nsecond line'
    qfile.write_text(query,encoding='utf-8')
    argv=['chat','--query-file',str(qfile),'--quiet','--ignore-rules','--format','stream-json']
exit_code=0
with ExitStack() as stack:
    stack.enter_context(patch.object(run_agent,'OpenAI',lambda **kwargs:client))
    stack.enter_context(patch.object(openai,'OpenAI',lambda **kwargs:client))
    stack.enter_context(patch.object(cli,'HermesCLI',OwnedCLI))
    stack.enter_context(patch.object(cli.atexit,'register',lambda *args,**kwargs:None))
    # Construction teardown boundary only: never terminate host runtimes.
    stack.enter_context(patch.object(cli,'_run_cleanup',lambda **kwargs:None))
    stack.enter_context(patch.object(sys,'stdout',out))
    stack.enter_context(patch.object(sys,'stderr',err))
    built=build_top_level_parser(); parser=built[0] if isinstance(built,tuple) else built
    args=parser.parse_args(argv)
    try: entry.cmd_chat(args)
    except SystemExit as exc: exit_code=exc.code
if case not in ('credentials-fail','init-fail','interrupt','provider-error'):
    assert calls and any(query in str(m.get('content','')) for m in calls[0]['messages'] if m.get('role')=='user')
assert config.read_bytes()==original_config
if case=='write': assert target.read_text(encoding='utf-8')==body
elif case!='deny': assert not target.exists()
assert not (Path.cwd()/'not-executed').exists()
if case=='interrupt':
    assert not calls and not observed_final_text, 'Startup main-thread interrupt must precede provider/agent execution'
db.close()
sys.stdout.write(json.dumps({'stdout':out.getvalue(),'stderr':err.getvalue(),'exit_code':exit_code,
    'calls':len(calls),'network_attempts':len(network_attempts),
    'observed_final_response':observed_final_text[0] if observed_final_text else None,
    'observed_agent_calls':len(observed_final_text)},ensure_ascii=False)+'\n')
'''


@pytest.mark.parametrize("case", ["write", "deny", "query-file", "credentials-fail", "init-fail", "interrupt", "provider-error", "plain"])
def test_public_cli_jsonl_to_owned_native_effect(tmp_path, case):
    root = Path(__file__).resolve().parents[2]
    assert not (root / ".env").exists(), "Integration must not contain real credentials"
    home, workspace = tmp_path / "所有 日本語 home", tmp_path / "所有 workspace"
    home.mkdir()
    workspace.mkdir()
    (home / "config.yaml").write_text(
        "model:\n  default: fixture-f11\n  context_length: 131072\n  max_tokens: 256\ncompression:\n  enabled: false\napprovals:\n  single_query_mode: deny\n",
        encoding="utf-8",
    )
    env = {k: v for k, v in os.environ.items() if k.upper() in
           {"SYSTEMROOT", "WINDIR", "COMSPEC", "PATH", "PATHEXT"}}
    env.update(HERMES_HOME=str(home), HOME=str(home), USERPROFILE=str(home), TEMP=str(home), TMP=str(home),
               PYTHONPATH=str(root), PYTHONUTF8="1", PYTHONIOENCODING="utf-8", TERMINAL_CWD=str(workspace))
    completed = subprocess.run([sys.executable, "-c", _PUBLIC_SCRIPT, case], cwd=workspace, env=env,
                               encoding="utf-8", capture_output=True, timeout=90)
    assert completed.returncode == 0, completed.stdout + completed.stderr
    envelope = json.loads(completed.stdout)
    assert isinstance(envelope["network_attempts"], int)
    if case == "plain":
        assert envelope["stdout"] == "日本語\n 完了\n"
        assert envelope["exit_code"] == 0
        return
    events = [json.loads(line) for line in envelope["stdout"].splitlines()]
    assert events[0]["type"] == "system" and events[0]["subtype"] == "init"
    terminals = [e for e in events if e["type"] == "result"]
    assert len(terminals) == 1 and events[-1] is terminals[0]
    expected_exit = 130 if case == "interrupt" else 1 if case in ("credentials-fail", "init-fail", "provider-error") else 0
    assert terminals[0]["exit_code"] == envelope["exit_code"] == expected_exit
    assert "session_id:" in envelope["stderr"]
    if expected_exit == 0:
        if case == "deny":
            assert envelope["observed_agent_calls"] == 1
            assert terminals[0]["text"] == envelope["observed_final_response"]
            assert terminals[0]["text"].startswith("日本語\n 完了\n\n⚠️ File-mutation verifier:")
            assert str(home / "config.yaml") in terminals[0]["text"]
            assert "Refusing to write to Hermes config file" in terminals[0]["text"]
        else:
            assert terminals[0]["text"] == "日本語\n 完了"
        expected_stream = ("\n\n" if case in ("write", "deny") else "") + "日本語\n 完了 "
        assert "".join(e["text"] for e in events if e["type"] == "text") == expected_stream
        assert terminals[0]["tokens"]["total"] > 0
    if case in ("write", "deny"):
        use = [e for e in events if e["type"] == "tool_use"]
        results = [e for e in events if e["type"] == "tool_result"]
        assert len(use) == len(results) == 1
        assert use[0]["name"] == results[0]["name"] == "write_file"
        assert use[0]["tool_call_id"] == results[0]["tool_call_id"] == "owned-file-call"
        payload = json.loads(results[0]["output"])
        assert ("security-sensitive configuration" in str(payload.get("error"))) if case == "deny" else not payload.get("error"), payload
