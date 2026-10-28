"""``PluginContext.ask_choice`` / ``hermes_cli.plugin_choices``: behaviour contracts.

The asker is the dispatching surface's clarify prompt; these tests drive the seam with fake askers and
assert what a plugin handler observes: the picked *value* (never a label), ``None`` whenever nothing
can be answered, no cross-talk between concurrent commands, and a ContextVar that is always restored.
"""
from __future__ import annotations

import asyncio
import contextvars
import threading

import pytest

from hermes_cli import plugin_choices
from hermes_cli.plugin_choices import ask_choice, asker_bound, bind_asker, clarify_asker
from hermes_cli.plugins import PluginContext, PluginManager, PluginManifest

CHOICES = [
    {"value": "default", "label": "Default", "description": "delegation.model / parent model"},
    {"value": "model_map", "label": "Model routes"},
    "profile_routes",
]
SHOWN = ["Default — delegation.model / parent model", "Model routes", "profile_routes"]


def _pick(answer):
    """An asker that records the prompt it was shown and replies with *answer*."""
    seen = []

    def asker(question, labels):
        seen.append((question, list(labels)))
        return answer

    asker.seen = seen
    return asker


def test_asker_sees_shown_labels_and_the_value_comes_back():
    asker = _pick(SHOWN[1])
    with bind_asker(asker):
        assert ask_choice("Mode", CHOICES) == "model_map"
    assert asker.seen == [("Mode", SHOWN)]


@pytest.mark.parametrize("reply", [SHOWN[0], "Default", "default", "DEFAULT", "  default  "])
def test_label_value_and_shown_text_each_pick_the_same_choice(reply):
    with bind_asker(_pick(reply)):
        assert ask_choice("Mode", CHOICES) == "default"


def test_label_and_value_differ_and_value_is_returned():
    with bind_asker(_pick("Model routes")):
        assert ask_choice("Mode", CHOICES) != "Model routes"
    with bind_asker(_pick("Model routes")):
        assert ask_choice("Mode", CHOICES) == "model_map"


@pytest.mark.parametrize("reply", [None, "", "   ", "something else", "3", "[user did not respond within 2m]", 7, ["default"]])
def test_cancel_timeout_and_unknown_replies_are_none(reply):
    with bind_asker(_pick(reply)):
        assert ask_choice("Mode", CHOICES) is None


def test_unknown_reply_never_falls_back_to_the_first_choice():
    with bind_asker(_pick("not a choice")):
        assert ask_choice("Mode", ["first", "second"]) is None


def test_an_ambiguous_reply_is_none_rather_than_a_guess():
    twins = [{"value": "a", "label": "Same"}, {"value": "b", "label": "Same"}]
    with bind_asker(_pick("Same")):
        assert ask_choice("Mode", twins) is None


def test_a_distinguishing_value_still_picks_between_twin_labels():
    twins = [{"value": "a", "label": "Same"}, {"value": "b", "label": "Same"}]
    with bind_asker(_pick("b")):
        assert ask_choice("Mode", twins) == "b"


def test_unbound_asker_is_none_and_never_prompts():
    assert not asker_bound()
    assert ask_choice("Mode", CHOICES) is None


@pytest.mark.parametrize("choices", [[], None, [{"label": "no value"}], [42], [""], ["   "]])
def test_no_usable_choices_never_reaches_the_asker(choices):
    asker = _pick("x")
    with bind_asker(asker):
        assert ask_choice("Mode", choices) is None
    assert asker.seen == []


def test_malformed_entries_are_dropped_but_valid_ones_still_work():
    asker = _pick("ok")
    with bind_asker(asker):
        assert ask_choice("Mode", [{"label": "no value"}, "ok", 3]) == "ok"
    assert asker.seen[0][1] == ["ok"]


def test_a_non_interactive_hook_context_has_no_asker():
    """A hook or cron job runs outside any slash-command dispatch: the binding is simply absent."""
    results = []
    thread = threading.Thread(target=lambda: results.append(ask_choice("Mode", CHOICES)))
    thread.start()
    thread.join()
    assert results == [None]


def test_call_on_a_running_event_loop_is_none_and_does_not_block():
    asker = _pick("Default")

    async def handler():
        return ask_choice("Mode", CHOICES)

    with bind_asker(asker):
        assert asyncio.run(handler()) is None
    assert asker.seen == [], "an async handler must not reach a blocking asker"


def test_bound_asker_is_reset_after_the_with_block():
    with bind_asker(_pick("default")):
        assert asker_bound()
    assert not asker_bound()


def test_bound_asker_is_reset_when_the_handler_raises():
    with pytest.raises(RuntimeError):
        with bind_asker(_pick("default")):
            raise RuntimeError("handler blew up")
    assert not asker_bound()
    assert ask_choice("Mode", CHOICES) is None


def test_nested_binding_restores_the_outer_asker():
    with bind_asker(_pick("outer")):
        with bind_asker(_pick("inner")):
            assert ask_choice("Mode", ["inner", "outer"]) == "inner"
        assert ask_choice("Mode", ["inner", "outer"]) == "outer"


def test_an_asker_that_raises_is_none_and_leaves_nothing_bound():
    def broken(question, labels):
        raise ConnectionError("viewer gone")

    with bind_asker(broken):
        assert ask_choice("Mode", CHOICES) is None
    assert not asker_bound()


def test_concurrent_commands_never_cross_replies():
    """Two commands in flight (two sessions or profiles) each see only their own asker."""
    both_asked = threading.Barrier(2, timeout=10)
    answers = {}

    def command(name, reply):
        def asker(question, labels):
            assert question == f"question for {name}"
            both_asked.wait()  # both prompts are open at once before either replies
            return reply

        with bind_asker(asker):
            answers[name] = ask_choice(f"question for {name}", ["alpha", "beta"])

    threads = [
        threading.Thread(target=contextvars.copy_context().run, args=(command, "one", "alpha")),
        threading.Thread(target=contextvars.copy_context().run, args=(command, "two", "beta")),
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert answers == {"one": "alpha", "two": "beta"}


def test_context_copy_carries_the_asker_to_an_executor_thread():
    """A sync handler runs on an executor thread under a context copy taken while bound."""
    results = []
    with bind_asker(_pick("Default")):
        context = contextvars.copy_context()
        bare_thread = threading.Thread(target=lambda: results.append(("bare", ask_choice("Mode", CHOICES))))
        bare_thread.start()
        bare_thread.join()
    copied_thread = threading.Thread(
        target=lambda: results.append(("copied", context.run(ask_choice, "Mode", CHOICES)))
    )
    copied_thread.start()
    copied_thread.join()
    assert dict(results) == {"bare": None, "copied": "default"}
    assert ask_choice("Mode", CHOICES) is None, "the parent context stays unbound after the block"


class TestClarifyAsker:
    def test_returns_the_callback_answer(self):
        calls = []
        ask = clarify_asker(lambda q, labels: calls.append((q, labels)) or "Model routes")
        assert ask("Mode", SHOWN) == "Model routes"
        assert calls == [("Mode", SHOWN)]

    @pytest.mark.parametrize("answer", [None, {"answers": {}}, 0, ["a"]])
    def test_non_string_answers_are_no_answer(self, answer):
        assert clarify_asker(lambda q, labels: answer)("Mode", SHOWN) is None

    def test_a_timeout_sentence_never_selects_a_choice(self):
        sentence = (
            "The user did not provide a response within the time limit. "
            "Use your best judgement to make the choice and proceed."
        )
        with bind_asker(clarify_asker(lambda q, labels: sentence)):
            assert ask_choice("Mode", CHOICES) is None


class TestPluginContextAskChoice:
    def _ctx(self):
        return PluginContext(PluginManifest(name="test-plugin", source="user"), PluginManager())

    def test_delegates_to_the_bound_asker(self):
        with bind_asker(_pick("Model routes")):
            assert self._ctx().ask_choice("Mode", CHOICES) == "model_map"

    def test_is_none_without_an_asker(self):
        assert self._ctx().ask_choice("Mode", CHOICES) is None

    def test_plugin_context_delegates_to_the_module_function(self, monkeypatch):
        seen = []
        monkeypatch.setattr("hermes_cli.plugins._ask_choice", lambda q, c: seen.append((q, c)) or "sentinel")
        assert self._ctx().ask_choice("Mode", ["a"]) == "sentinel"
        assert seen == [("Mode", ["a"])]


def test_module_exposes_no_approval_surface():
    """ask_choice selects between options; it must not grow an approve/permission entry point."""
    public = {name for name in vars(plugin_choices) if not name.startswith("_")}
    assert not {name for name in public if "approv" in name.lower() or "permission" in name.lower()}
