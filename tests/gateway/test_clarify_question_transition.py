"""Typing authority belongs to the pending question, including one run's peers."""
import asyncio
from concurrent.futures import ThreadPoolExecutor
import json
import threading

import pytest

from gateway.platforms.base import MessageEvent
from tests.gateway.test_clarify_run_lifecycle import BodyBarrier, DeliveryAdapter, finish, owned_registry, trace, until
from tests.gateway.test_clarify_routing_retirement import inbound
from tests.gateway.test_queued_followup_processing_hooks import SESSION_KEY, _install_fake_agent, _make_runner, _source
from tools import clarify_gateway as cm
from tools.clarify_tool import clarify_tool


@pytest.mark.asyncio
@pytest.mark.parametrize("next_kind", ["clarify", "approval"])
async def test_old_inbound_cannot_unpause_next_actual_question(monkeypatch, tmp_path, trace, next_kind):
    from tools import approval
    second_paused, first_waiting = threading.Event(), threading.Event()

    class Adapter(DeliveryAdapter):
        pauses = 0

        def pause_typing_for_chat(self, chat_id):
            super().pause_typing_for_chat(chat_id)
            self.pauses += 1
            if self.pauses == 2:
                second_paused.set()

    adapter = Adapter()
    runner = inbound(monkeypatch, adapter)
    answers = []

    class Agent:
        def __init__(self, **kwargs):
            self.tools = []

        def run_conversation(self, message, **kwargs):
            for label in ("old", "new"):
                if label == "new" and next_kind == "approval":
                    callback = approval._gateway_notify_cbs[SESSION_KEY]
                    decision = approval._await_gateway_decision(SESSION_KEY, callback,
                        {"command": "owned harmless approval", "description": "no command executes",
                         "pattern_key": "owned harmless approval", "pattern_keys": ["owned harmless approval"]})
                    answers.append(decision["choice"])
                else:
                    answers.append(json.loads(clarify_tool(question="owned-" + label,
                        choices=["alpha", "beta"], callback=self.clarify_callback))["user_response"])
            return {"final_response": "owned reply", "messages": [], "api_calls": 1}

    _install_fake_agent(monkeypatch, tmp_path, Agent)
    actual_wait = cm.wait_for_response

    def wait(clarify_id, timeout, **kwargs):
        if kwargs.get("entry") is not None and kwargs["entry"].question == "owned-old":
            first_waiting.set()
        return actual_wait(clarify_id, timeout, **kwargs)

    monkeypatch.setattr(cm, "wait_for_response", wait)
    generation = runner._begin_session_run_generation(SESSION_KEY)
    task = asyncio.create_task(runner._run_agent(message="old", context_prompt="", history=[], source=_source(),
        session_id="same-run-sequential", session_key=SESSION_KEY, run_generation=generation))
    try:
        await until(first_waiting.is_set)
        first = cm.get_pending_for_session(SESSION_KEY, include_choice_prompts=True)
        actual_resolve = cm.resolve_gateway_clarify

        def resolve(clarify_id, response, **kwargs):
            result = actual_resolve(clarify_id, response, **kwargs)
            if result and clarify_id == first.clarify_id:
                assert second_paused.wait(6), "actual worker did not enter its second question's pause"
            return result

        monkeypatch.setattr(cm, "resolve_gateway_clarify", resolve)
        assert await runner._handle_message(MessageEvent(text="1", source=_source(), message_id="answer-a")) == ""
        second = cm.get_pending_for_session(SESSION_KEY, include_choice_prompts=True)
        if next_kind == "clarify":
            assert second is not None and second.owner is first.owner
        else:
            assert approval.has_blocking_approval(SESSION_KEY)
            assert approval._gateway_queues[SESSION_KEY][0].owner is approval._gateway_notify_cbs[SESSION_KEY]
        assert runner._session_state(SESSION_KEY).persistent.run_generation == generation
        trace.update(paused=list(adapter._typing_paused), next_kind=next_kind,
                     first_answer=first.response, pending=second.clarify_id if second else "actual approval")
        assert _source().chat_id in adapter._typing_paused, "A inbound unpaused actual B in the same run"
        if next_kind == "clarify":
            await until(lambda: "new" in adapter.sent)
            assert await runner._handle_message(MessageEvent(text="2", source=_source(), message_id="answer-b")) == ""
        else:
            assert approval.resolve_gateway_approval(SESSION_KEY, "once") == 1
        await asyncio.wait_for(task, 6)
        assert answers == ["alpha", "beta" if next_kind == "clarify" else "once"]
    finally:
        approval.resolve_gateway_approval(SESSION_KEY, "deny", resolve_all=True)
        await finish([task], adapter)


@pytest.mark.asyncio
@pytest.mark.parametrize("parallel", [False, True])
@pytest.mark.parametrize("effect", ["typing", "reopen"])
async def test_answered_callback_preserves_peer_pause_and_single_answer_utility(monkeypatch, tmp_path, trace, parallel, effect):
    from gateway.stream_consumer import GatewayStreamConsumer
    from hermes_constants import get_hermes_home

    # Existing public config enables actual consumer construction; only the
    # adapter's outbound leaves are inert. Spy methods delegate real owners.
    config = json.dumps({"display": {"streaming": True}, "agent": {"clarify_timeout": 0}})
    (get_hermes_home() / "config.yaml").write_text(config, encoding="utf-8")
    (tmp_path / "config.yaml").write_text(config, encoding="utf-8")
    reopens = []
    actual_reopen = GatewayStreamConsumer.request_reopen_seed

    def reopen(consumer):
        reopens.append([entry.clarify_id for entry in cm._entries.values() if not entry.event.is_set()])
        return actual_reopen(consumer)

    monkeypatch.setattr(GatewayStreamConsumer, "request_reopen_seed", reopen)
    adapter = DeliveryAdapter()
    runner = inbound(monkeypatch, adapter)
    body = BodyBarrier()
    answers = {}

    class Agent:
        def __init__(self, **kwargs):
            self.tools = []

        def run_conversation(self, message, **kwargs):
            def ask(label):
                result = clarify_tool(question="owned-current-" + label, choices=["alpha", "beta"],
                                      callback=self.clarify_callback)
                answers[label] = json.loads(result)["user_response"]

            with ThreadPoolExecutor(2) as pool:
                futures = [pool.submit(ask, "a")]
                if parallel:
                    futures.append(pool.submit(ask, "b"))
                for future in futures:
                    future.result(timeout=8)
            body.wait()
            return {"final_response": "owned reply", "messages": [], "api_calls": 1}

    _install_fake_agent(monkeypatch, tmp_path, Agent)
    generation = runner._begin_session_run_generation(SESSION_KEY)
    task = asyncio.create_task(runner._run_agent(message="current", context_prompt="", history=[], source=_source(),
        session_id="same-run-peers", session_key=SESSION_KEY, run_generation=generation))
    try:
        await until(lambda: len(adapter.sent) == (2 if parallel else 1))
        pending = [entry for entry in cm._entries.values() if not entry.event.is_set()]
        order = [entry.question.rsplit("-", 1)[-1] for entry in pending]
        if parallel:
            assert pending[0].owner is pending[1].owner
        first = pending[0]
        assert cm.resolve_gateway_clarify(first.clarify_id, "alpha", entry=first)
        await until(lambda: order[0] in answers)
        trace.update(parallel=parallel, effect=effect, paused=list(adapter._typing_paused), reopens=list(reopens), order=order)
        if parallel:
            if effect == "typing":
                assert _source().chat_id in adapter._typing_paused, "A worker callback unpaused its same-run peer B"
            else:
                assert not reopens, "A worker callback requested a stream reopen while its peer was pending"
            assert cm.is_pending(pending[1])
            assert cm.attempt_text_response_for_session(SESSION_KEY, "2") == cm.TEXT_RESOLVED
            await until(lambda: len(answers) == 2)
            assert answers[order[1]] == "beta"
        else:
            assert _source().chat_id not in adapter._typing_paused
            assert reopens, "single answered callback lost immediate actual request_reopen_seed"
        await asyncio.wait_for(body.entered.wait(), 6)
        assert _source().chat_id not in adapter._typing_paused
        body.release.set()
        await asyncio.wait_for(task, 6)
    finally:
        await finish([task], adapter, body)
