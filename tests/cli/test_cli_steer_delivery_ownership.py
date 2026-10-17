"""Late guidance retains the source turn's cancellation/session authority."""
from queue import Queue
import threading
from types import SimpleNamespace

import pytest


def surface():
    agent = SimpleNamespace(_pending_steer_lock=threading.Lock(), _hard_interrupt_requested=threading.Event(),
                            _steer_cancel_generation=0, session_id="owned-session")
    return SimpleNamespace(agent=agent, _pending_input=Queue(), _agent_running=False,
                           _expand_paste_references=lambda value: value)


def result():
    return {"pending_steer": "owned guidance", "pending_steer_generation": 0, "session_id": "owned-session"}


@pytest.mark.parametrize("change", ["stop", "new-session", "other-profile"])
def test_queued_leftover_cannot_outlive_its_source_turn(change):
    from hermes_cli.cli_queue import enqueue_pending_steer, pending_steer_is_current
    owner = surface()
    assert enqueue_pending_steer(owner, result()) is True
    assert owner._pending_input.qsize() == 1
    item = owner._pending_input.get_nowait()
    assert str(item) == "owned guidance"
    assert pending_steer_is_current(owner, item) is True

    if change == "stop":
        owner.agent._steer_cancel_generation += 1
        # Generation must survive clear_interrupt() resetting this Event.
        owner.agent._hard_interrupt_requested.clear()
    elif change == "new-session":
        owner.agent.session_id = "new-owned-session"
    else:
        owner.agent = surface().agent

    assert pending_steer_is_current(owner, item) is False
    assert pending_steer_is_current(owner, "owned guidance") is True


def test_stop_between_core_return_and_cli_handoff_rejects_only_leftover():
    from hermes_cli.cli_queue import enqueue_pending_steer
    owner = surface()
    owner._pending_input.put("ordinary queued request")
    saved_result = result()
    owner.agent._steer_cancel_generation += 1

    assert enqueue_pending_steer(owner, saved_result) is False
    assert owner._pending_input.get_nowait() == "ordinary queued request"
    assert owner._pending_input.empty()


def test_other_profile_with_the_same_session_id_cannot_adopt_the_returned_text():
    from hermes_cli.cli_queue import enqueue_pending_steer
    owner = surface()
    source_agent = owner.agent
    owner.agent = surface().agent

    assert enqueue_pending_steer(owner, result(), source_agent=source_agent) is False
    assert owner._pending_input.empty()


def test_real_hard_stop_keeps_guidance_revoked_after_the_event_is_cleared():
    from tests.run_agent.test_steer import _bare_agent
    from hermes_cli.cli_queue import enqueue_pending_steer, pending_steer_is_current
    owner = surface()
    owner.agent = _bare_agent()
    owner.agent.session_id = "owned-session"
    owner.agent._hard_interrupt_requested = threading.Event()
    owner.agent._steer_cancel_generation = 0
    saved_result = result()
    assert enqueue_pending_steer(owner, saved_result)
    item = owner._pending_input.get_nowait()

    owner.agent.hard_interrupt()
    owner.agent.clear_interrupt()
    owner.agent._open_steer_turn()

    assert pending_steer_is_current(owner, item) is False
    assert enqueue_pending_steer(owner, saved_result) is False


def test_public_late_steer_at_finalizer_cleanup_is_delivered_once(monkeypatch):
    from cli import HermesCLI
    from run_agent import AIAgent
    from tests.run_agent.test_steer import _bare_agent
    from tests.agent.test_turn_finalizer_interrupt_alternation import _StubAgent, _finalize

    class FinishingAgent(_StubAgent, AIAgent):
        pass

    agent = FinishingAgent()
    agent.__dict__.update(_bare_agent().__dict__)
    agent._hard_interrupt_requested = threading.Event()
    agent._drain_pending_steer = AIAgent._drain_pending_steer.__get__(agent)
    owner = object.__new__(HermesCLI)
    owner.agent, owner._agent_running, owner._pending_input = agent, True, Queue()
    owner._pending_input.put("earlier queued request")
    assert agent.steer("before final drain")

    def clear_after_late_command():
        # Public inline dispatch lands after the last finalizer drain but
        # before the real interrupt cleanup, without timing or source hooks.
        assert owner.process_command("/s during final cleanup")
        AIAgent.clear_interrupt(agent)

    monkeypatch.setattr(agent, "clear_interrupt", clear_after_late_command)
    outcome = _finalize(agent, [{"role": "user", "content": "owned question"},
                                {"role": "assistant", "content": "owned answer"}],
                        interrupted=False, final_response="owned answer")

    assert outcome["pending_steer"] == "before final drain"
    from hermes_cli.cli_queue import enqueue_pending_steer
    enqueue_pending_steer(owner, outcome, source_agent=agent)
    owner._pending_resume_sessions = None
    owner._voice_lock = threading.Lock()
    owner._voice_mode = owner._voice_continuous = False
    delivered = []
    monkeypatch.setattr(owner, "chat", lambda text, **_kwargs: delivered.append(str(text)))
    monkeypatch.setattr(owner, "_print_user_message_preview", lambda _item: None)
    monkeypatch.setattr(owner, "_tui_after_turn", lambda: None)
    while not owner._pending_input.empty():
        owner._tui_process_one_input(owner._pending_input.get_nowait())
    assert delivered == ["earlier queued request", "before final drain", "during final cleanup"]
    assert owner._pending_input.empty()
    assert agent._drain_pending_steer() is None


def test_explicit_queue_edit_adopts_guidance_as_the_users_new_request():
    from hermes_cli.cli_queue import enqueue_pending_steer, pending_steer_is_current, process_queue_command
    owner = surface()
    assert enqueue_pending_steer(owner, result())
    process_queue_command(owner, "/queue edit 1 edited guidance", lambda _message: None)
    owner.agent._steer_cancel_generation += 1

    item = owner._pending_input.get_nowait()
    assert item == "edited guidance"
    assert pending_steer_is_current(owner, item) is True


@pytest.mark.parametrize("change", ["stop", "new-session", "other-profile"])
def test_real_input_consumer_drops_stale_guidance_and_keeps_plain_user_input(monkeypatch, change):
    from cli import HermesCLI
    from hermes_cli.cli_queue import enqueue_pending_steer
    owner = object.__new__(HermesCLI)
    owner.agent = surface().agent
    owner._pending_input = Queue()
    owner._pending_resume_sessions = None
    owner._voice_lock = threading.Lock()
    owner._voice_mode = owner._voice_continuous = False
    delivered = []
    monkeypatch.setattr(owner, "chat", lambda text, **_kwargs: delivered.append(str(text)))
    monkeypatch.setattr(owner, "_print_user_message_preview", lambda _item: None)
    monkeypatch.setattr(owner, "_tui_after_turn", lambda: None)
    assert enqueue_pending_steer(owner, result())
    owner._tui_process_one_input(owner._pending_input.get_nowait())
    assert delivered == ["owned guidance"]
    delivered.clear()
    assert enqueue_pending_steer(owner, result())
    owner._pending_input.put("ordinary queued request")
    if change == "stop":
        owner.agent._steer_cancel_generation += 1
    elif change == "new-session":
        owner.agent.session_id = "new-owned-session"
    else:
        owner.agent = surface().agent

    while not owner._pending_input.empty():
        owner._tui_process_one_input(owner._pending_input.get_nowait())

    assert delivered == ["ordinary queued request"]
