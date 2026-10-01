"""F08b dispatch/effect acceptance; child constructor/conversation are doubles.

Real HermesCLI.process_command -> /refine -> original spawn -> owned thread -> original
worker/cache-parity builder -> model_tools registry -> real skill/file owners.
The scripted child replaces AIAgent construction and its model conversation,
not the worker, whitelist, provenance, trust, scanner, or write guards.
This is bounded Windows dispatch/effect proof, not a provider-transport E2E.
"""
from __future__ import annotations

import copy
import json
import socket
import threading
from types import MethodType, SimpleNamespace

import pytest


@pytest.fixture
def harness(tmp_path, monkeypatch):
    home = tmp_path / "所有するプロフィール" / "home"
    skills = home / "skills"
    skills.mkdir(parents=True)
    monkeypatch.setenv("HERMES_HOME", str(home))
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("USERPROFILE", str(home))
    monkeypatch.chdir(home)
    (home / "config.yaml").write_text(
        "terminal:\n  backend: local\n"
        "skills:\n  external_dirs: []\n  guard_agent_created: true\n",
        encoding="utf-8",
    )
    attempts = []

    def deny_network(*args, **kwargs):
        attempts.append(str(args[:1]))
        raise AssertionError("F08b owned test forbids network")

    monkeypatch.setattr(socket.socket, "connect", deny_network)
    monkeypatch.setattr(socket, "getaddrinfo", deny_network)
    from tools import skill_manager_tool as manager, skills_tool, skill_usage
    from tools.skill_provenance import (
        get_current_write_origin, set_current_write_origin, reset_current_write_origin,
    )
    from hermes_cli import plugins
    from model_tools import handle_function_call, get_tool_definitions
    import run_agent
    from cli import HermesCLI  # before replacing the child constructor

    owned_threads = []
    real_threading = run_agent.threading

    class ThreadingProxy:
        def __getattr__(self, name):
            return getattr(real_threading, name)

        def Thread(self, *args, **kwargs):
            thread = real_threading.Thread(*args, **kwargs)
            owned_threads.append(thread)
            return thread

    # Replace only run_agent's module reference, never threading.Thread globally.
    monkeypatch.setattr(run_agent, "threading", ThreadingProxy())

    def join_owned_threads():
        for thread in owned_threads:
            if thread.ident is not None:
                thread.join(timeout=15)
                assert not thread.is_alive(), "owned review thread did not exit"

    # Explicit path-binding doubles for constants imported before this fixture.
    # Discovery, ownership, trust, scanner, provenance and guards stay real.
    monkeypatch.setattr(manager, "SKILLS_DIR", skills)
    monkeypatch.setattr(skills_tool, "SKILLS_DIR", skills)
    name = "review-owned"
    content = "---\nname: review-owned\ndescription: Preserve tested procedures.\n---\n\n# 手順\n\n旧手順\n"
    folder = skills / name
    folder.mkdir()
    (folder / "SKILL.md").write_text(content, encoding="utf-8")
    skill_usage.mark_agent_created(name)
    assert skill_usage.is_agent_created(name)
    user_folder = skills / "user-owned"
    user_folder.mkdir()
    (user_folder / "SKILL.md").write_text(content.replace(name, "user-owned"), encoding="utf-8")

    original_spawn = run_agent.AIAgent._spawn_background_review
    defs = get_tool_definitions(enabled_toolsets=["skills", "file"], quiet_mode=True)
    assert {"skill_view", "skill_manage", "read_file", "search_files"} <= {
        t["function"]["name"] for t in defs
    }
    parent = SimpleNamespace(
        model="test-owned-script", provider="openai", platform="cli",
        session_id="f08-owned-session", session_start="test-owned-start",
        client=SimpleNamespace(SUPPORTS_HERMES_TOOL_CALLS=True),
        enabled_toolsets=["skills", "file"], disabled_toolsets=None,
        valid_tool_names={t["function"]["name"] for t in defs},
        tools=copy.deepcopy(defs), _cached_system_prompt="固定プロンプト\n",
        reasoning_config=None, request_overrides={},
        _memory_store=None, _memory_enabled=False, _user_profile_enabled=False,
        _current_main_runtime=lambda: {"api_mode": "chat_completions"},
        _safe_print=lambda *a, **k: None, background_review_callback=None,
        memory_notifications="off", _active_children=[],
        _background_review_agent=None, _background_review_lock=threading.Lock(),
        _active_children_lock=threading.Lock(),
    )
    parent._spawn_background_review = MethodType(original_spawn, parent)
    before = (parent._cached_system_prompt, copy.deepcopy(parent.tools))
    history = [{"role": "user", "content": "保存した手順を確認する"}]

    def run(calls, *, explode=False):
        results, failures, children = [], [], []
        closed = threading.Event()
        parent._emit_auxiliary_failure = lambda label, exc: failures.append(str(exc))

        class ScriptedChild:
            def __init__(self, **kwargs):
                self.kwargs = kwargs
                self._session_messages = []
                self.tools = copy.deepcopy(defs)
                children.append(self)

            def run_conversation(self, **kwargs):
                assert "指定された手順" in kwargs["user_message"]
                assert self._memory_write_origin == "background_review"
                assert self._persist_disabled and self._session_db is None
                assert self._cached_system_prompt == before[0]
                assert self.tools == before[1]
                token = set_current_write_origin(self._memory_write_origin)
                try:
                    for tool, args in calls:
                        raw = handle_function_call(tool, args, task_id="f08-owned-task")
                        result = json.loads(raw)
                        if tool == "delegate_task":
                            # Meta-tool is intercepted before registry dispatch.
                            # Independently inspect the real worker policy; this
                            # is not proof of the actual agent-loop delegation gate.
                            result["_observed_worker_block"] = plugins.get_pre_tool_call_block_message(tool, args)
                        results.append(result)
                    if explode:
                        raise RuntimeError("owned scripted conversation failure")
                finally:
                    reset_current_write_origin(token)

            def shutdown_memory_provider(self):
                pass  # no memory provider was constructed by this double

            def close(self):
                # Observe worker cleanup in its own thread, before signalling.
                self.after_whitelist = plugins._get_pre_tool_call_directive_details("terminal", {}).action
                self.after_origin = get_current_write_origin()
                closed.set()

        monkeypatch.setattr(run_agent, "AIAgent", ScriptedChild)
        cli = HermesCLI.__new__(HermesCLI)
        cli.agent = parent
        cli.conversation_history = copy.deepcopy(history)
        cli.session_id = parent.session_id
        try:
            assert cli.process_command("/refine 指定された手順を保存") is True
        finally:
            join_owned_threads()
        assert closed.wait(15), (failures, results, children)
        assert len(children) == 1 and len(results) == len(calls), failures
        child = children[0]
        assert child.after_whitelist is None
        assert child.after_origin == "foreground"
        assert parent._active_children == [] and parent._background_review_agent is None
        assert (parent._cached_system_prompt, parent.tools) == before
        assert cli.conversation_history == history
        assert get_current_write_origin() == "foreground"
        assert not attempts, attempts
        return results, failures

    try:
        yield SimpleNamespace(run=run, home=home, folder=folder, content=content, name=name)
    finally:
        join_owned_threads()


def patch_args(name="review-owned", **kwargs):
    return dict(action="patch", name=name, old_string="旧手順", new_string="新しい安全な手順", **kwargs)


def test_requested_read_file_then_patch_has_real_utf8_effect(harness):
    results, failures = harness.run([
        ("read_file", {"path": str(harness.folder / "SKILL.md")}),
        ("skill_manage", patch_args()),
    ])
    assert not failures
    assert "error" not in results[0], results[0]
    assert results[1].get("success") is True, results[1]
    assert "新しい安全な手順" in (harness.folder / "SKILL.md").read_text(encoding="utf-8")


def test_requested_search_files_is_admitted_without_schema_change(harness):
    results, failures = harness.run([
        ("search_files", {"path": str(harness.folder), "pattern": "旧手順", "target": "content"}),
    ])
    assert not failures
    assert "error" not in results[0], results[0]
    assert "旧手順" in json.dumps(results[0], ensure_ascii=False)


def test_existing_skill_view_is_equivalent_read_save_control(harness):
    results, failures = harness.run([
        ("skill_view", {"name": harness.name}), ("skill_manage", patch_args()),
    ])
    assert not failures and all(r.get("success") is True for r in results), results
    assert "新しい安全な手順" in (harness.folder / "SKILL.md").read_text(encoding="utf-8")


def test_unread_owned_skill_is_refused(harness):
    results, _ = harness.run([("skill_manage", patch_args())])
    assert results[0].get("_read_before_write_required") is True, results
    assert (harness.folder / "SKILL.md").read_text(encoding="utf-8") == harness.content


@pytest.mark.parametrize("tool,args", [
    ("terminal", {"command": "echo must-not-run"}),
    ("write_file", {"path": "must-not-exist.txt", "content": "denied"}),
    ("send_message", {"message": "denied"}),
    ("delegate_task", {"task": "denied"}),
    ("patch", {"path": "must-not-exist.txt", "old_string": "a", "new_string": "b"}),
])
def test_unrelated_authority_stays_denied(harness, tool, args):
    results, _ = harness.run([(tool, args)])
    if tool == "delegate_task":
        assert results[0].get("error") == "delegate_task must be handled by the agent loop", results
        assert "non-whitelisted" in results[0].get("_observed_worker_block", ""), results
    else:
        assert "non-whitelisted" in results[0].get("error", ""), results
    assert not (harness.home / "must-not-exist.txt").exists()


def test_user_owned_skill_stays_refused_after_read(harness):
    results, _ = harness.run([
        ("skill_view", {"name": "user-owned"}),
        ("skill_manage", patch_args("user-owned")),
    ])
    assert results[1].get("success") is False, results
    assert "not curator-managed" in results[1].get("error", ""), results
    assert "旧手順" in (harness.home / "skills/user-owned/SKILL.md").read_text(encoding="utf-8")


def test_skill_patch_traversal_stays_refused(harness):
    results, _ = harness.run([
        ("skill_view", {"name": harness.name}),
        ("skill_manage", patch_args(file_path="references/../../config.yaml")),
    ])
    assert results[1].get("success") is False
    assert "traversal" in results[1].get("error", "").lower(), results
    assert "guard_agent_created: true" in (harness.home / "config.yaml").read_text(encoding="utf-8")


def test_exception_clears_worker_whitelist_and_provenance(harness):
    results, failures = harness.run([("skill_view", {"name": harness.name})], explode=True)
    assert results[0].get("success") is True, results
    assert failures == ["owned scripted conversation failure"]
