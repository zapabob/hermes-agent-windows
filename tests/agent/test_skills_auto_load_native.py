"""F12 native profile files -> ordinary agent prompt acceptance.

Only construction/tool discovery and the provider transport are doubled.
Config, skill_view, preprocessing, trust, scanner and prompt owners are real.
"""
from __future__ import annotations

import copy
import socket
import threading
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest
import yaml

MARKER = "F12_NATIVE_BODY_日本語_7b941"
OTHER = "F12_OTHER_BODY_別プロファイル"


@pytest.fixture
def native(tmp_path, monkeypatch):
    from hermes_constants import reset_hermes_home_override, set_hermes_home_override
    home = tmp_path / "日本語 home"
    workspace = tmp_path / "所有 workspace"
    home.mkdir()
    workspace.mkdir()
    monkeypatch.setenv("HERMES_HOME", str(home))
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("USERPROFILE", str(home))
    monkeypatch.setenv("TERMINAL_CWD", str(workspace))
    monkeypatch.setenv("HERMES_PLATFORM", "cli")
    monkeypatch.chdir(workspace)
    monkeypatch.delenv("HERMES_IGNORE_RULES", raising=False)
    token = set_hermes_home_override(None)

    def deny(*args, **kwargs):
        raise AssertionError("F12 test cannot use socket/DNS")

    monkeypatch.setattr(socket.socket, "connect", deny)
    monkeypatch.setattr(socket.socket, "connect_ex", deny)
    monkeypatch.setattr(socket, "getaddrinfo", deny)

    def config(value, at=None):
        target = at or home
        target.mkdir(parents=True, exist_ok=True)
        value = {"model": {"default": "fixture-f12", "context_length": 131072,
                            "max_tokens": 256}, "compression": {"enabled": False}, **value}
        (target / "config.yaml").write_text(yaml.safe_dump(value), encoding="utf-8")

    def skill(name="native-alpha", body=MARKER, at=None, platforms=None):
        directory = (at or home / "skills") / name
        directory.mkdir(parents=True, exist_ok=True)
        metadata = {"name": Path(name).name, "description": "Owned native fixture."}
        if platforms is not None:
            metadata["platforms"] = platforms
        file = directory / "SKILL.md"
        file.write_text("---\n" + yaml.safe_dump(metadata) + "---\n\n# Native fixture\n\n" + body + "\n", encoding="utf-8")
        return file

    config({"skills": {"auto_load": ["native-alpha"]}})
    skill()
    state = SimpleNamespace(home=home, workspace=workspace, config=config, skill=skill,
                            agents=[], databases=[], requests=[])

    def agent(skills=True, skip=False, db_home=None):
        import run_agent
        from hermes_state import SessionDB
        import openai
        from openai.types.chat import ChatCompletion, ChatCompletionChunk
        names = ["skills_list", "skill_view"] if skills else ["web_search"]
        definitions = [{"type": "function", "function": {"name": name,
                        "description": "Owned construction boundary",
                        "parameters": {"type": "object", "properties": {}}}} for name in names]

        def completion(**kwargs):
            state.requests.append(copy.deepcopy(kwargs))
            if kwargs.get("stream"):
                return iter([ChatCompletionChunk.model_validate({"id": "owned-f12", "object": "chat.completion.chunk",
                    "created": 0, "model": "fixture-f12", "choices": [{"index": 0,
                    "delta": {"role": "assistant", "content": "Owned completion."},
                    "finish_reason": "stop"}]})])
            return ChatCompletion.model_validate({"id": "owned-f12", "object": "chat.completion",
                "created": 0, "model": "fixture-f12", "choices": [{"index": 0,
                "message": {"role": "assistant", "content": "Owned completion."},
                "finish_reason": "stop"}], "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2}})

        client = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=completion)),
                                 base_url="http://127.0.0.1:9/v1", close=lambda: None)
        # Transport can be rebuilt after construction during a real turn.
        # Keep the provider double alive for the whole owned test lifecycle.
        monkeypatch.setattr(run_agent, "OpenAI", lambda **kwargs: client)
        monkeypatch.setattr(openai, "OpenAI", lambda **kwargs: client)
        with patch.object(run_agent, "get_tool_definitions", return_value=definitions), \
             patch.object(run_agent, "check_toolset_requirements", return_value={}), \
             patch("hermes_cli.plugins.discover_plugins", return_value=None):
            instance = run_agent.AIAgent(model="fixture-f12", provider="openai-compat",
                api_mode="chat_completions", api_key="owned-placeholder", base_url=client.base_url,
                quiet_mode=True, skip_context_files=skip, skip_memory=True, max_iterations=2,
                enabled_toolsets=["skills"] if skills else ["web"], save_trajectories=False,
                session_id="owned-f12-" + str(len(state.agents)), platform="cli")
        db = SessionDB(db_path=(db_home or home) / "state.db")
        instance._session_db = db
        state.databases.append(db)
        state.agents.append(instance)
        return instance

    state.agent = agent
    yield state
    for db in state.databases:
        db.close()
    reset_hermes_home_override(token)


def prompt(agent, system=None):
    """Real provider-ready ordinary AIAgent prompt assembly, never mocked."""
    return agent._build_system_prompt(system)


def test_auto_load_public_api_absence_is_separate(native):
    from agent import skill_commands
    assert callable(getattr(skill_commands, "resolve_auto_load_skills", None)), "MISSING_API resolve_auto_load_skills"
    assert callable(getattr(skill_commands, "build_auto_load_prompt", None)), "MISSING_API build_auto_load_prompt"


@pytest.mark.parametrize("entries", [["native-alpha"], [" native-alpha ", "native-alpha", ""],
                                  [None, 7, {}, "native-alpha"], ["missing", "native-alpha"]])
def test_config_selection_reaches_body_once(native, entries):
    native.config({"skills": {"auto_load": entries}})
    assert prompt(native.agent()).count(MARKER) == 1


@pytest.mark.parametrize("config", [{}, {"skills": None}, {"skills": "bad"},
    {"skills": {"auto_load": "native-alpha"}}, {"skills": {"auto_load": None}},
    {"skills": {"auto_load": {"native-alpha": True}}}, {"skills": {"auto_load": []}}])
def test_malformed_selection_is_not_loaded(native, config):
    native.config(config)
    assert MARKER not in prompt(native.agent())


@pytest.mark.parametrize("gate", ["disabled", "platform-disabled", "platform-frontmatter", "missing", "deleted", "ignore", "skip-context", "no-skill-tool"])
def test_existing_opt_outs_block_body(native, monkeypatch, gate):
    config = {"skills": {"auto_load": ["native-alpha"]}}
    if gate == "disabled":
        config["skills"]["disabled"] = ["native-alpha"]
    elif gate == "platform-disabled":
        config["skills"]["platform_disabled"] = {"cli": ["native-alpha"]}
    elif gate == "platform-frontmatter":
        native.skill(platforms=["macos"])
    elif gate in ("missing", "deleted"):
        if gate == "missing":
            config["skills"]["auto_load"] = ["unknown-native"]
        else:
            (native.home / "skills/native-alpha/SKILL.md").unlink()
    elif gate == "ignore":
        monkeypatch.setenv("HERMES_IGNORE_RULES", "1")
    native.config(config)
    assert MARKER not in prompt(native.agent(skills=gate != "no-skill-tool", skip=gate == "skip-context"))


def test_real_provider_request_contains_body_once(native):
    agent = native.agent()
    agent.run_conversation("Owned Unicode request 日本語", conversation_history=[], task_id="owned-f12-turn")
    assert native.requests, "No provider-ready request was produced"
    content = "\n".join(str(message.get("content", "")) for message in native.requests[0]["messages"] if message["role"] == "system")
    assert content.count(MARKER) == 1


@pytest.mark.parametrize("change", ["file", "config", "delete", "disable"])
def test_same_agent_pins_block_new_agent_resolves_changes(native, change):
    agent = native.agent()
    initial = prompt(agent)
    assert initial.count(MARKER) == 1
    if change == "file":
        native.skill(body=OTHER)
    elif change == "config":
        native.skill("native-other", body=OTHER)
        native.config({"skills": {"auto_load": ["native-other"]}})
    elif change == "delete":
        (native.home / "skills/native-alpha/SKILL.md").unlink()
    else:
        native.config({"skills": {"auto_load": ["native-alpha"], "disabled": ["native-alpha"]}})
    rebuilt = prompt(agent)
    assert rebuilt.count(MARKER) == 1
    assert OTHER not in rebuilt
    fresh = prompt(native.agent())
    assert MARKER not in fresh
    assert fresh.count(OTHER) == (1 if change in ("file", "config") else 0)


@pytest.mark.parametrize("model_changed", [False, True])
def test_static_prefix_restoration_keeps_captured_skill_bytes(native, model_changed):
    from agent.system_prompt import reconstruct_static_prefix
    agent = native.agent()
    initial = prompt(agent)
    assert initial.count(MARKER) == 1
    pinned = agent._auto_load_skills_result[0]
    assert pinned.count(MARKER) == 1
    agent._cached_system_prompt = initial
    agent._cached_system_prompt_static = None
    agent._use_prompt_caching = True
    native.skill(body=OTHER)
    if model_changed:
        agent.model = "fixture-f12-other-model"
    reconstruct_static_prefix(agent)
    assert agent._auto_load_skills_result[0].encode("utf-8") == pinned.encode("utf-8")
    assert pinned in prompt(agent)
    assert OTHER not in prompt(agent)


@pytest.mark.parametrize("bound", [False, True])
def test_profile_db_home_and_context_override_are_real(native, bound):
    from hermes_constants import reset_hermes_home_override, set_hermes_home_override
    profile = native.home / "profiles/別"
    native.config({"skills": {"auto_load": ["native-alpha"]}}, at=profile)
    native.skill(body=OTHER, at=profile / "skills")
    agent = native.agent(db_home=profile)
    token = set_hermes_home_override(str(profile)) if bound else None
    try:
        result = prompt(agent)
    finally:
        if token is not None:
            reset_hermes_home_override(token)
    assert result.count(OTHER) == 1
    assert MARKER not in result


def test_context_lost_thread_uses_session_db_profile(native):
    profile = native.home / "profiles/thread 日本語"
    native.config({"skills": {"auto_load": ["native-alpha"]}}, at=profile)
    native.skill(body=OTHER, at=profile / "skills")
    agent = native.agent(db_home=profile)
    results = []
    errors = []
    def build():
        try:
            results.append(prompt(agent))
        except BaseException as error:
            errors.append(error)
    thread = threading.Thread(target=build)
    thread.start()
    thread.join(timeout=20)
    assert not thread.is_alive()
    assert not errors, errors
    assert results[0].count(OTHER) == 1
    assert MARKER not in results[0]


@pytest.mark.parametrize("identifier", ["../outside", "absolute"])
def test_outside_identifier_preserves_existing_refusal(native, identifier):
    outside = native.skill("outside", body=OTHER, at=native.workspace)
    requested = str(outside.parent) if identifier == "absolute" else identifier
    native.config({"skills": {"auto_load": [requested, "native-alpha"]}})
    result = prompt(native.agent())
    assert OTHER not in result
    assert result.count(MARKER) == 1


@pytest.mark.parametrize("trusted", [False, True])
def test_project_skill_requires_actual_trust_and_scanner(native, trusted):
    from agent.skill_utils import is_quarantined_project_skill
    (native.workspace / ".git").mkdir()
    project = native.skill("project-native", body=OTHER, at=native.workspace / ".hermes/skills")
    config = {"skills": {"auto_load": ["project-native", "native-alpha"]}}
    if trusted:
        config["skills"]["trusted_project_dirs"] = [str(native.workspace)]
    native.config(config)
    if trusted:
        assert not is_quarantined_project_skill(project), "BLOCKED_NATIVE_SCANNER: real scanner refused benign owned project"
    result = prompt(native.agent())
    assert result.count(MARKER) == 1
    assert result.count(OTHER) == (1 if trusted else 0)


def test_auto_and_explicit_canonical_alias_render_once(native):
    from agent.skill_commands import build_preloaded_skills_prompt
    agent = native.agent()
    result = prompt(agent)
    assert result.count(MARKER) == 1
    text, loaded, missing = build_preloaded_skills_prompt(
        [str(native.home / "skills/native-alpha")], excluded_loaded_names=["native-alpha"])
    assert not text
    assert not missing
    assert (result + text).count(MARKER) == 1


@pytest.mark.parametrize("change", ["file", "config"])
def test_public_cli_preload_handoff_pins_worker_body(native, monkeypatch, change):
    """Public main/preload/finalize/_init_agent -> real agent provider request.

    Terminal interaction and AIAgent construction are the only replaced
    CLI boundaries. The worker and handoff run in production methods.
    """
    import cli
    from hermes_constants import reset_hermes_home_override, set_hermes_home_override
    calls = []
    native.skill("explicit-other", body="F12_EXPLICIT_BODY")
    chosen_home = native.home
    expected_body = MARKER
    token = None
    if change == "config":
        chosen_home = native.home / "profiles/CLI 日本語"
        native.config({"skills": {"auto_load": ["native-alpha"]}}, at=chosen_home)
        native.skill(body=OTHER, at=chosen_home / "skills")
        native.skill("explicit-other", body="F12_EXPLICIT_BODY", at=chosen_home / "skills")
        expected_body = OTHER
        token = set_hermes_home_override(str(chosen_home))

    def construct(**kwargs):
        instance = native.agent()
        instance.ephemeral_system_prompt = kwargs.get("ephemeral_system_prompt")
        return instance

    def terminal_turn(instance, query, images=None):
        instance.finalize_preloaded_skills()
        # Capture is deliberately before agent construction: changing inputs
        # here exposes a reread instead of reuse of worker-rendered bytes.
        if change == "file":
            native.skill(body=OTHER)
        else:
            native.config({"skills": {"auto_load": []}}, at=chosen_home)
        assert instance._init_agent(), "CLI real _init_agent failed"
        instance.agent.run_conversation(query, conversation_history=[], task_id="owned-cli-f12")
        calls.extend(native.requests)

    monkeypatch.setattr(cli, "AIAgent", construct)
    monkeypatch.setattr(cli.HermesCLI, "chat", terminal_turn)
    try:
        cli.main(query="Owned CLI request", skills="explicit-other", toolsets="skills",
                 model="fixture-f12", provider="custom", api_key="owned-placeholder",
                 base_url="http://127.0.0.1:9/v1", max_turns=2)
    finally:
        if token is not None:
            reset_hermes_home_override(token)
    assert calls
    system = "\n".join(str(m.get("content", "")) for m in calls[0]["messages"] if m["role"] == "system")
    assert system.count(expected_body) == 1, "Worker automatic body must survive handoff"
    assert (OTHER if expected_body == MARKER else MARKER) not in system
    assert system.count("F12_EXPLICIT_BODY") == 1


def test_owned_skill_body_is_really_loadable_without_auto_feature(native):
    from agent.skill_commands import build_preloaded_skills_prompt
    text, loaded, missing = build_preloaded_skills_prompt(["native-alpha"])
    assert text.count(MARKER) == 1
    assert loaded == ["native-alpha"]
    assert missing == []


def test_bad_auto_render_config_does_not_block_provider_turn(native):
    native.config({"skills": {"auto_load": ["native-alpha"], "inline_shell": True,
                              "inline_shell_timeout": "invalid-owned-value"}})
    agent = native.agent()
    agent.run_conversation("Owned bad-render request", conversation_history=[], task_id="owned-bad-render")
    assert native.requests
    assert MARKER not in "\n".join(str(m.get("content", "")) for m in native.requests[0]["messages"])


def test_same_bad_render_config_retains_explicit_preload_error(native):
    from agent.skill_commands import build_preloaded_skills_prompt
    native.config({"skills": {"auto_load": ["native-alpha"], "inline_shell": True,
                              "inline_shell_timeout": "invalid-owned-value"}})
    with pytest.raises(ValueError, match="invalid-owned-value"):
        build_preloaded_skills_prompt(["native-alpha"])
