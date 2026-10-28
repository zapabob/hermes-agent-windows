"""``ask_choice`` from a plugin slash command in the classic CLI: it rides the CLI's clarify picker."""
from queue import Queue
from unittest.mock import Mock

import pytest

from hermes_cli import plugins
from hermes_cli.plugin_choices import ask_choice, asker_bound

CHOICES = [{"value": "default", "label": "Default", "description": "parent model"}, "profile_routes"]
LABELS = ["Default — parent model", "profile_routes"]


@pytest.fixture
def cli_with_plugin(monkeypatch):
    import cli as cli_module

    instance = cli_module.HermesCLI.__new__(cli_module.HermesCLI)
    instance.config = {"model": {"default": "fixture-model"}, "approval": {"mode": "ask"}}
    instance.model = "fixture-model"
    instance.agent = None
    instance.session_id = "test-plugin-choice"
    instance._pending_input = Queue()
    instance._agent_running = False
    monkeypatch.setattr(plugins, "fire_pre_command_hook", Mock())
    monkeypatch.setattr(cli_module, "_ensure_skill_commands", lambda: {})
    monkeypatch.setattr(cli_module, "get_skill_bundles", lambda: {})
    monkeypatch.setattr(cli_module, "_get_plugin_cmd_handler_names", lambda: {"delegation"})

    def install(handler):
        monkeypatch.setattr(plugins, "get_plugin_command_handler",
                            lambda name: handler if name == "delegation" else None)

    return instance, install


def test_the_clarify_picker_answers_the_choice_when_the_app_is_up(cli_with_plugin, capsys):
    instance, install = cli_with_plugin
    instance._app = object()  # the prompt_toolkit app is running: it can paint and answer a panel
    asked = []
    instance._clarify_callback = lambda question, choices, **kw: asked.append((question, list(choices))) or "profile_routes"
    install(lambda arg: f"MODE={ask_choice('Delegation mode', CHOICES)}")

    assert instance.process_command("/delegation") is True

    assert asked == [("Delegation mode", LABELS)]
    assert "MODE=profile_routes" in capsys.readouterr().out
    assert not asker_bound()


@pytest.mark.parametrize("answer", ["", "The user did not provide a response within the time limit.", "other"])
def test_a_timeout_or_unknown_picker_answer_is_none(cli_with_plugin, capsys, answer):
    instance, install = cli_with_plugin
    instance._app = object()
    instance._clarify_callback = lambda question, choices, **kw: answer
    install(lambda arg: f"MODE={ask_choice('Delegation mode', CHOICES)}")
    instance.process_command("/delegation")
    assert "MODE=None" in capsys.readouterr().out


def test_without_a_running_app_nothing_is_asked(cli_with_plugin, capsys):
    """Headless: the picker could never be painted or answered, so the handler gets None at once."""
    instance, install = cli_with_plugin
    instance._app = None
    instance._clarify_callback = Mock(side_effect=AssertionError("must not prompt without an app"))
    install(lambda arg: f"MODE={ask_choice('Delegation mode', CHOICES)}")
    instance.process_command("/delegation")
    assert "MODE=None" in capsys.readouterr().out
    instance._clarify_callback.assert_not_called()


def test_a_failing_handler_leaves_no_asker_bound(cli_with_plugin, capsys):
    instance, install = cli_with_plugin
    instance._app = object()
    instance._clarify_callback = lambda question, choices, **kw: "profile_routes"

    def handler(arg):
        assert asker_bound()
        raise RuntimeError("handler failed")

    install(handler)
    instance.process_command("/delegation")
    assert "handler failed" in capsys.readouterr().out
    assert not asker_bound()
    assert ask_choice("q?", ["x"]) is None
