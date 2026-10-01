"""F08b real ordinary-agent fork acceptance; only provider transport is scripted."""
from __future__ import annotations

import copy
import http.client
import hashlib
import json
import os
import socket
import threading
import traceback
from types import SimpleNamespace
from pathlib import Path

import pytest
import yaml


@pytest.fixture
def delivery(tmp_path, monkeypatch, request):
    home = tmp_path / "所有 profile 日本語"
    home.mkdir()
    monkeypatch.setenv("HERMES_HOME", str(home))
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("USERPROFILE", str(home))
    monkeypatch.setenv("TERMINAL_CWD", str(home))
    monkeypatch.chdir(home)
    (home / "config.yaml").write_text(yaml.safe_dump({
        "model": {"default": "fixture-f08", "provider": "openai-compat",
                  "base_url": "http://127.0.0.1:9/v1", "context_length": request.param,
                  "ollama_num_ctx": request.param, "max_tokens": 256},
        "lsp": {"enabled": False},
        "compression": {"enabled": False},
        "terminal": {"backend": "local", "cwd": str(home)},
        "memory": {"memory_enabled": False, "user_profile_enabled": False},
        "skills": {"external_dirs": [], "guard_agent_created": True},
        "auxiliary": {"background_review": {"enabled": False}},
    }), encoding="utf-8")
    from hermes_constants import set_hermes_home_override, reset_hermes_home_override
    token = set_hermes_home_override(None)
    attempts, requests, threads, clients = [], [], [], []

    def deny(*args, **kwargs):
        attempts.append(repr(args[:1]) + "\n" + "".join(traceback.format_stack(limit=30)))
        print("F08_DENIED_NETWORK_STACK", attempts[-1])
        raise AssertionError("F08 provider fixture forbids network/DNS")

    monkeypatch.setattr(socket.socket, "connect", deny)
    monkeypatch.setattr(socket.socket, "connect_ex", deny)
    monkeypatch.setattr(socket, "getaddrinfo", deny)
    import openai
    import run_agent
    from openai.types.chat import ChatCompletion, ChatCompletionChunk
    from cli import HermesCLI
    from tools import skills_tool, skill_manager_tool, skill_usage
    from hermes_state import SessionDB
    skills = home / "skills"
    # Modules imported by collection use their import-time directory; this is
    # owned profile path binding, not tool-discovery, provenance or guard doubles.
    monkeypatch.setattr(skills_tool, "SKILLS_DIR", skills)
    monkeypatch.setattr(skill_manager_tool, "SKILLS_DIR", skills)
    old = "---\nname: review-owned\ndescription: Preserve tested procedures.\n---\n\n# 手順\n\n旧手順\n"
    for name in ("review-owned", "user-owned"):
        folder = skills / name
        folder.mkdir(parents=True)
        (folder / "SKILL.md").write_text(old.replace("review-owned", name), encoding="utf-8")
    skill_usage.mark_agent_created("review-owned")
    assert skill_usage.is_agent_created("review-owned")
    real_threading = run_agent.threading

    class ThreadingProxy:
        def __getattr__(self, name):
            return getattr(real_threading, name)

        def Thread(self, *args, **kwargs):
            instance = real_threading.Thread(*args, **kwargs)
            threads.append(instance)
            return instance

    monkeypatch.setattr(run_agent, "threading", ThreadingProxy())
    from agent import chat_completion_helpers, tool_executor, display, relay_runtime
    initial_scope_pool = relay_runtime._SCOPE_OP_EXECUTOR
    from tools import daemon_pool
    for module in (chat_completion_helpers, tool_executor, display, daemon_pool):
        monkeypatch.setattr(module, "threading", ThreadingProxy())
    # The real local-provider progress tracker has its own HTTP transport,
    # independent of OpenAI. Script only that owned /slots transport too.
    class OwnedProgressConnection:
        def __init__(self, host, port, **kwargs):
            assert host == "127.0.0.1" and port == 9

        def request(self, method, path, **kwargs):
            assert method == "GET" and path.startswith("/slots")

        def getresponse(self):
            return SimpleNamespace(read=lambda: b"[]")

        def close(self):
            pass

    monkeypatch.setattr(http.client, "HTTPConnection", OwnedProgressConnection)
    script = []
    observed = []

    def completion(**kwargs):
        requests.append(copy.deepcopy(kwargs))
        child = getattr(parent, "_background_review_agent", None)
        if child is not None:
            assert type(child) is run_agent.AIAgent
            assert child._persist_disabled and child._session_db is None
            assert child._memory_write_origin == "background_review"
        observed.extend(copy.deepcopy(m) for m in kwargs["messages"] if m["role"] == "tool")
        action = script.pop(0) if script else None
        message = {"role": "assistant", "content": "所有テスト完了"}
        finish = "stop"
        if action:
            batch = action if isinstance(action, list) else [action]
            message = {"role": "assistant", "content": None, "tool_calls": [
                {"id": f"owned-call-{len(requests)}-{index}", "type": "function",
                 "function": {"name": name, "arguments": json.dumps(arguments, ensure_ascii=False)}}
                for index, (name, arguments) in enumerate(batch)]}
            finish = "tool_calls"
        data = {"id": "owned-f08", "object": "chat.completion", "created": 0,
                "model": "fixture-f08", "choices": [{"index": 0, "message": message,
                "finish_reason": finish}], "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2}}
        if kwargs.get("stream"):
            delta = {"role": "assistant", "content": message["content"]}
            if action:
                delta = {"role": "assistant", "tool_calls": [{"index": index, **call} for index, call in enumerate(message["tool_calls"])]}
            return iter([ChatCompletionChunk.model_validate({"id": "owned-f08", "object": "chat.completion.chunk",
                "created": 0, "model": "fixture-f08", "choices": [{"index": 0, "delta": delta, "finish_reason": finish}]})])
        return ChatCompletion.model_validate(data)

    def make_client(**kwargs):
        client = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=completion)),
            base_url="http://127.0.0.1:9/v1", close=lambda: None)
        clients.append(client)
        return client

    monkeypatch.setattr(run_agent, "OpenAI", make_client)
    monkeypatch.setattr(openai, "OpenAI", make_client)
    parent = None
    db = None

    def join(*, include_scope_pool=False):
        for thread in threads:
            # The real Relay owner keeps a process-lifetime pool. It is owned
            # only if created here; dispose it after closing this test's parent.
            if thread.name.startswith("relay-scope-op") and not include_scope_pool:
                continue
            if thread.ident is not None:
                thread.join(timeout=30)
                assert not thread.is_alive(), ("owned thread still running", thread.name)

    try:
        parent = run_agent.AIAgent(model="fixture-f08", provider="openai-compat",
            api_mode="chat_completions", api_key="owned-placeholder", base_url="http://127.0.0.1:9/v1",
            quiet_mode=True, skip_memory=True, enabled_toolsets=["skills", "file", "terminal"],
            max_iterations=5, save_trajectories=False, platform="cli", session_id="owned-f08-provider")
        parent._memory_nudge_interval = parent._skill_nudge_interval = 0
        parent.run_conversation("親の通常ターン 日本語", conversation_history=[])
        assert requests, "FIXTURE provider request absent in parent seed"
        assert parent._cached_system_prompt, "FIXTURE parent cached prefix not captured"
        db = SessionDB(db_path=home / "owned-state.db")
        db.create_session(parent.session_id, "cli")
        db.append_message(parent.session_id, "user", "親の永続メッセージ")
        parent._session_db = db
        cli = HermesCLI.__new__(HermesCLI)
        cli.agent = parent
        cli.session_id = parent.session_id
        cli.conversation_history = [{"role": "user", "content": "親の会話 日本語"},
                                    {"role": "assistant", "content": "親の回答"}]

        def run(calls):
            script[:] = calls
            requests.clear()
            observed.clear()
            before = (parent._cached_system_prompt, copy.deepcopy(parent.tools),
                      copy.deepcopy(cli.conversation_history), db.get_messages(parent.session_id),
                      db.get_session(parent.session_id), copy.deepcopy(parent._session_messages))
            try:
                assert cli.process_command("/refine 指定された手順を安全に更新") is True
            finally:
                join()
            assert any(t.name == "bg-review" for t in threads), "FIXTURE no review thread"
            assert requests, "FIXTURE ordinary child never reached provider"
            assert not script, "FIXTURE scripted child actions not consumed"
            assert parent._active_children == [] and parent._background_review_agent is None
            assert parent._cached_system_prompt == before[0]
            assert parent.tools == before[1]
            assert cli.conversation_history == before[2]
            assert parent._session_messages == before[5]
            assert db.get_messages(parent.session_id) == before[3]
            # Usage attribution is an existing explicit parent-side effect; the
            # fork must preserve session lifecycle/identity, not zero usage.
            after = db.get_session(parent.session_id)
            for key in ("id", "source", "ended_at", "title", "parent_session_id"):
                assert after.get(key) == before[4].get(key), (key, after, before[4])
            assert requests[0]["tools"] == before[1]
            prefix = next(m["content"] for m in requests[0]["messages"] if m["role"] == "system")
            assert prefix == before[0]
            assert "指定された手順を安全に更新" in str(requests[0]["messages"])
            assert not attempts, attempts
            results = {}
            for msg in observed:
                try:
                    results[msg["tool_call_id"]] = json.loads(msg["content"])
                except json.JSONDecodeError:
                    results[msg["tool_call_id"]] = {"delivered_preview": msg["content"]}
            assert len(results) == sum(len(c) if isinstance(c, list) else 1 for c in calls), (results, calls)
            trace = {"case": tmp_path.name, "calls": calls, "results": list(results.values()),
                     "provider_requests": len(requests), "parent_prefix_schema_history_preserved": True,
                     "persisted_transcript_and_lifecycle_preserved": True,
                     "owned_threads": [{"name": t.name, "alive": t.is_alive()} for t in threads],
                     "network_attempts": attempts,
                     "relay_scope_pool_disposal_deferred_to_fixture_teardown": initial_scope_pool is None}
            evidence = Path(__file__).resolve().parents[3] / "evidence/F08b-delivery-tests-001"
            identity = hashlib.sha256(str(tmp_path).encode("utf-8")).hexdigest()[:16]
            trace_path = evidence / (tmp_path.name + "-" + identity + "-trace.json")
            assert not trace_path.exists()
            trace_path.write_text(json.dumps(trace, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            return list(results.values())

        yield SimpleNamespace(run=run, home=home, skills=skills, old=old, requests=requests, parent=parent)
    finally:
        join()
        if parent is not None:
            parent.close()
        if initial_scope_pool is None:
            with relay_runtime._SCOPE_OP_EXECUTOR_LOCK:
                owned_pool = relay_runtime._SCOPE_OP_EXECUTOR
                relay_runtime._SCOPE_OP_EXECUTOR = None
            if owned_pool is not None:
                owned_pool.shutdown(wait=True, cancel_futures=True)
        join(include_scope_pool=True)
        if db is not None:
            db.close()
        reset_hermes_home_override(token)
        assert not attempts, attempts


def patch_args(name="review-owned"):
    return {"action": "patch", "name": name, "old_string": "旧手順", "new_string": "新しい安全な手順"}



@pytest.mark.parametrize("delivery", [65536, 131072], indirect=True)
@pytest.mark.parametrize("reader", ["read_file", "skill_view"])
def test_omitted_skill_content_cannot_authorize_patch(delivery, reader):
    # Short lines avoid per-line clamps, and the target is far outside preview.
    count = 1 if delivery.parent.context_compressor.context_length == 65536 else 3
    names = ["review-owned"] + [f"rev-{i}" for i in range(1, count)]
    from tools import skill_usage
    for name in names:
        directory = delivery.skills / name
        directory.mkdir(exist_ok=True)
        content = delivery.old.replace("review-owned", name).replace("旧手順", ("手順確認 " + "a" * 84 + "\n") * 1000 + "旧手順")
        (directory / "SKILL.md").write_text(content, encoding="utf-8")
        skill_usage.mark_agent_created(name)
    reads = [(reader, {"path": str(delivery.skills / name / "SKILL.md"), "limit": 2000}
              if reader == "read_file" else {"name": name}) for name in names]
    before = (delivery.skills / "review-owned/SKILL.md").read_bytes()
    results = delivery.run([reads if count > 1 else reads[0], ("skill_manage", patch_args())])
    target_result = results[0]
    assert "delivered_preview" in target_result, ("FIXTURE aggregate omission absent", target_result)
    assert "旧手順" not in target_result["delivered_preview"], "FIXTURE omitted target remained visible"
    assert results[-1].get("_read_before_write_required") is True, results[-1]
    assert (delivery.skills / "review-owned/SKILL.md").read_bytes() == before


@pytest.mark.parametrize("delivery", [65536], indirect=True)
@pytest.mark.parametrize("reader", ["read_file", "skill_view"])
def test_complete_delivered_skill_remains_editable(delivery, reader):
    args = {"path": str(delivery.skills / "review-owned/SKILL.md")} if reader == "read_file" else {"name": "review-owned"}
    results = delivery.run([(reader, args), ("skill_manage", patch_args())])
    assert "delivered_preview" not in results[0]
    assert results[1].get("success") is True, results[1]
    assert "新しい安全な手順" in (delivery.skills / "review-owned/SKILL.md").read_text(encoding="utf-8")


@pytest.mark.parametrize("delivery", [65536], indirect=True)
@pytest.mark.parametrize("reader", ["read_file", "skill_view"])
def test_same_batch_read_has_not_yet_reached_model(delivery, reader):
    args = {"path": str(delivery.skills / "review-owned/SKILL.md")} if reader == "read_file" else {"name": "review-owned"}
    before = (delivery.skills / "review-owned/SKILL.md").read_bytes()
    results = delivery.run([[(reader, args), ("skill_manage", patch_args())]])
    assert results[1].get("_read_before_write_required") is True, results[1]
    assert (delivery.skills / "review-owned/SKILL.md").read_bytes() == before


@pytest.mark.parametrize("delivery", [65536], indirect=True)
@pytest.mark.parametrize("reader", ["read_file", "skill_view"])
def test_prior_complete_delivery_survives_repeat_read(delivery, reader):
    args = {"path": str(delivery.skills / "review-owned/SKILL.md")} if reader == "read_file" else {"name": "review-owned"}
    results = delivery.run([(reader, args), (reader, args), ("skill_manage", patch_args())])
    assert results[-1].get("success") is True, results[-1]
    assert "新しい安全な手順" in (delivery.skills / "review-owned/SKILL.md").read_text(encoding="utf-8")
