"""Public /plan dispatch to the existing input queue, without agent startup."""
from __future__ import annotations

import copy
import os
from pathlib import Path
from queue import Queue
import subprocess
import sys
from unittest.mock import Mock

import pytest

from agent.plan_prompt import build_plan_prompt


@pytest.fixture
def plan_cli(monkeypatch):
    import cli as cli_module
    from hermes_cli import plugins

    instance = cli_module.HermesCLI.__new__(cli_module.HermesCLI)
    instance.config = {"model": {"default": "fixture-model"}, "approval": {"mode": "ask"}}
    instance.model = "fixture-model"
    instance.agent = None
    instance.session_id = "test-owned-plan"
    instance._pending_input = Queue()
    instance._pending_resume_sessions = ["obsolete"]
    instance._agent_running = False
    observer = Mock()
    monkeypatch.setattr(plugins, "fire_pre_command_hook", observer)
    monkeypatch.setattr(cli_module, "_ensure_skill_commands", lambda: {})
    monkeypatch.setattr(cli_module, "get_skill_bundles", lambda: {})
    monkeypatch.setattr(cli_module, "_get_plugin_cmd_handler_names", lambda: set())
    return instance, observer


@pytest.mark.parametrize("command, task", [
    ("/plan Preserve 日本語 Case", "Preserve 日本語 Case"),
    ("/PLAN Keep Case", "Keep Case"),
    ("/plan", ""),
    ("  /plan   \t  ", ""),
    ("/plan   Line One\n日本語 Two  ", "Line One\n日本語 Two"),
])
def test_public_plan_queues_shared_prompt_once(plan_cli, capsys, command, task):
    instance, observer = plan_cli
    before_config = copy.deepcopy(instance.config)
    assert instance.process_command(command) is True
    assert instance._pending_input.get_nowait() == build_plan_prompt(task)
    assert instance._pending_input.empty()
    assert "Unknown command" not in capsys.readouterr().out
    assert instance.config == before_config
    assert instance.model == "fixture-model"
    assert instance.agent is None
    assert instance._pending_resume_sessions is None
    observer.assert_called_once_with(surface="cli", command="plan", alias_used="plan",
                                     args_raw=task, session_key="test-owned-plan", platform="cli")


def test_no_active_queue_reports_existing_handler_message(plan_cli, capsys):
    instance, _ = plan_cli
    del instance._pending_input
    assert instance.process_command("/plan 日本語") is True
    output = capsys.readouterr().out
    assert "/plan needs an active chat session" in output
    assert "Unknown command" not in output


def test_neighbor_review_keeps_its_existing_owner(plan_cli):
    instance, observer = plan_cli
    instance._handle_review_command = Mock()
    assert instance.process_command("/review Keep 日本語") is True
    instance._handle_review_command.assert_called_once_with("/review Keep 日本語")
    assert instance._pending_input.empty()
    assert observer.call_args.kwargs["command"] == "review"


def test_unknown_plan_suffix_cannot_invoke_plan(plan_cli, capsys):
    instance, observer = plan_cli
    assert instance.process_command("/plan-not-registered keep") is True
    assert instance._pending_input.empty()
    assert "Unknown command" in capsys.readouterr().out
    observer.assert_not_called()


def test_existing_quick_plan_alias_retains_its_effect(plan_cli):
    instance, _ = plan_cli
    instance.config["quick_commands"] = {"plan": {"type": "alias", "target": "review"}}
    instance._handle_review_command = Mock()
    assert instance.process_command("/plan Preserve 日本語 Case") is True
    instance._handle_review_command.assert_called_once_with("/review Preserve 日本語 Case")
    assert instance._pending_input.empty()


def test_existing_plugin_plan_retains_its_effect(plan_cli, monkeypatch, capsys):
    import cli as cli_module
    from hermes_cli import plugins
    instance, _ = plan_cli
    handler = Mock(return_value="CUSTOM_PLAN_EFFECT")
    monkeypatch.setattr(cli_module, "_get_plugin_cmd_handler_names", lambda: {"plan"})
    monkeypatch.setattr(plugins, "get_plugin_command_handler", lambda name: handler if name == "plan" else None)
    assert instance.process_command("/plan Preserve 日本語 Case") is True
    handler.assert_called_once_with("Preserve 日本語 Case")
    assert instance._pending_input.empty()
    assert "CUSTOM_PLAN_EFFECT" in capsys.readouterr().out


def test_public_plan_native_subprocess_uses_only_owned_home(tmp_path):
    root = Path(__file__).resolve().parents[2]
    assert not (root / ".env").exists()
    home = tmp_path / "日本語 plan profile"
    home.mkdir()
    script = '''
from queue import Queue
from unittest.mock import patch
import cli
from agent.plan_prompt import build_plan_prompt
instance = cli.HermesCLI.__new__(cli.HermesCLI)
instance.config = {}
instance.agent = None
instance.model = 'fixture-model'
instance.session_id = 'native-plan'
instance._pending_input = Queue()
with patch('hermes_cli.plugins.fire_pre_command_hook'), patch.object(cli, '_ensure_skill_commands', return_value={}), patch.object(cli, 'get_skill_bundles', return_value={}), patch.object(cli, '_get_plugin_cmd_handler_names', return_value=set()):
    assert instance.process_command('/plan Preserve 日本語 Case') is True
assert instance._pending_input.get_nowait() == build_plan_prompt('Preserve 日本語 Case')
assert instance._pending_input.empty()
assert instance.model == 'fixture-model' and instance.agent is None
print('NATIVE_PLAN_QUEUE_OK')
'''
    env = {key: value for key, value in os.environ.items() if key.upper() in
           {"SYSTEMROOT", "WINDIR", "COMSPEC", "PATH", "PATHEXT", "TEMP", "TMP"}}
    env.update(HERMES_HOME=str(home), HOME=str(home), USERPROFILE=str(home),
               PYTHONUTF8="1", PYTHONIOENCODING="utf-8")
    result = subprocess.run([sys.executable, "-c", script], cwd=root, env=env,
                            encoding="utf-8", capture_output=True, timeout=60)
    assert result.returncode == 0, result.stdout + result.stderr
    assert "NATIVE_PLAN_QUEUE_OK" in result.stdout
    assert "Unknown command" not in result.stdout
