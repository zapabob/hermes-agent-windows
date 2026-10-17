"""FX-A02: cancellation belongs to the session SSE producer, not its worker.

Run only under the campaign's isolated runner. These tests use the real session
stream, stop handler, and executor-backed _run_agent. Only model construction,
process ownership/reaping, and the SSE transport are substituted; no listener,
model, native application, or external messaging service is started.
"""

import asyncio
import json
import threading
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager, nullcontext
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, Mock

import pytest


_TIMEOUT = 10.0
_GUIDANCE = "owned guidance settled before cancellation"
_AUTH_HEADERS = {"Authorization": "Bearer owned-session-stream-key"}


class _RecordingResponse:
    """Capture actual SSE frames without opening a socket."""

    def __init__(self, **_kwargs: Any) -> None:
        self.frames: list[bytes] = []
        self.block_event: str | None = None
        self.disconnect = False
        self.write_blocked = asyncio.Event()
        self.release_write = asyncio.Event()
        self.block_prepare = False
        self.prepare_blocked = asyncio.Event()
        self.release_prepare = asyncio.Event()
        self.prepare_interrupted = asyncio.Event()

    async def prepare(self, request: Any) -> None:
        del request
        if self.block_prepare:
            self.prepare_blocked.set()
            try:
                await self.release_prepare.wait()
            except asyncio.CancelledError:
                self.prepare_interrupted.set()
                raise
            self.prepare_interrupted.set()
            raise ConnectionResetError("owned prepare disconnected")

    async def write(self, payload: bytes) -> None:
        if self.block_event and payload.startswith(
            f"event: {self.block_event}\n".encode("utf-8")
        ):
            self.write_blocked.set()
            await self.release_write.wait()
            if self.disconnect:
                raise ConnectionResetError("owned transport disconnected")
        self.frames.append(payload)

    def events(self) -> list[tuple[str, dict[str, Any]]]:
        events = []
        for frame in self.frames:
            lines = frame.decode("utf-8").splitlines()
            names = [line[7:] for line in lines if line.startswith("event: ")]
            data = [line[6:] for line in lines if line.startswith("data: ")]
            if names and data:
                events.append((names[0], json.loads("\n".join(data))))
        return events


class _GatedAgent:
    """Return an already-settled result even after a hard stop was accepted."""

    session_prompt_tokens = 0
    session_completion_tokens = 0
    session_total_tokens = 0

    def __init__(self, session_id: str, pending_steer: str) -> None:
        self.session_id = session_id
        self.pending_steer = pending_steer
        self.worker_started = asyncio.Event()
        self.release_worker = threading.Event()
        self.hard_stopped = threading.Event()
        self.interrupt_seen = asyncio.Event()
        self.loop = asyncio.get_running_loop()
        self.conversation_calls = 0

    def hard_interrupt(self, message: str | None = None) -> None:
        del message
        self.hard_stopped.set()
        self.loop.call_soon_threadsafe(self.interrupt_seen.set)

    def interrupt(self, message: str | None = None) -> None:
        """Expose the old soft ABI so the regression fails on a real assertion."""
        del message
        self.loop.call_soon_threadsafe(self.interrupt_seen.set)

    def run_conversation(
        self, *, user_message: str, conversation_history: list, task_id: str
    ) -> dict[str, Any]:
        self.conversation_calls += 1
        assert user_message == "owned prompt"
        assert conversation_history == []
        assert task_id == self.session_id
        self.loop.call_soon_threadsafe(self.worker_started.set)
        assert self.release_worker.wait(_TIMEOUT), "worker release gate timed out"
        result = {
            "session_id": self.session_id,
            "final_response": "owned completion",
            "messages": [
                {"role": "user", "content": user_message},
                {"role": "assistant", "content": "owned completion"},
            ],
        }
        if self.pending_steer:
            result["pending_steer"] = self.pending_steer
        return result


class _StreamCase:
    def __init__(
        self, adapter: Any, agent: _GatedAgent, response: _RecordingResponse
    ) -> None:
        self.adapter = adapter
        self.agent = agent
        self.response = response
        self.worker_returned = asyncio.Event()
        self.release_producer = asyncio.Event()
        self.worker_cleanup_markers: list[bool] = []
        self.reaper = Mock()
        self.handler_task: asyncio.Task | None = None
        self.run_id = ""
        self.expect_cancelled_handler = False
        self.expect_prepare_error = False
        self.creation_started = asyncio.Event()
        self.release_creation = threading.Event()
        self.worker_exited = asyncio.Event()
        self.drain_entered = asyncio.Event()
        self.producer_task: asyncio.Task | None = None

    async def stop(self) -> None:
        request = SimpleNamespace(match_info={"run_id": self.run_id}, headers=_AUTH_HEADERS)
        response = await self.adapter._handle_stop_run(request)
        assert response.status == 200
        assert json.loads(response.body)["status"] == "stopping"
        assert self.agent.hard_stopped.is_set()
        self.reaper.assert_called_once_with(
            self.agent, source="api_server_run_stop"
        )
        assert self.adapter._run_statuses[self.run_id]["status"] == "stopping"
        assert self.run_id in self.adapter._stopping_run_ids

    async def finish_worker(self) -> None:
        self.agent.release_worker.set()
        await asyncio.wait_for(self.worker_returned.wait(), _TIMEOUT)

    async def finish_producer(self) -> None:
        self.release_producer.set()
        assert self.handler_task is not None
        await asyncio.wait_for(asyncio.shield(self.handler_task), _TIMEOUT)


@pytest.fixture
def stream_case(monkeypatch: pytest.MonkeyPatch, tmp_path: Any) -> Callable:
    """Delay product imports until the isolated runner has installed its fences."""

    @asynccontextmanager
    async def create(
        pending_steer: str = _GUIDANCE,
        *,
        transport: str = "normal",
        gate_creation: bool = False,
    ) -> AsyncIterator[_StreamCase]:
        from gateway.config import PlatformConfig
        from gateway.platforms import api_server as api
        from hermes_state import SessionDB

        db = SessionDB(tmp_path / "owned-session-stream.db")
        store = api.ResponseStore(db_path=":memory:")
        try:
            with monkeypatch.context() as patcher:
                # Constructor leaves otherwise read config/secrets or open the
                # profile's response_store.db. All storage here is owned/memory.
                patcher.setattr(api, "_get_scoped_secret", lambda *_a, **_k: "")
                patcher.setattr(api, "ResponseStore", lambda: store)
                patcher.setattr(api, "get_browser_control_broker", lambda: object())
                patcher.setattr(
                    api.APIServerAdapter,
                    "_resolve_max_concurrent_runs",
                    staticmethod(lambda: 0),
                )
                patcher.setattr(
                    api.APIServerAdapter,
                    "_profile_scope",
                    staticmethod(lambda _profile: nullcontext()),
                )
                adapter = api.APIServerAdapter(
                    PlatformConfig(
                        enabled=True,
                        extra={
                            "key": "owned-session-stream-key",
                            "model_name": "owned-model",
                            "host": "127.0.0.1",
                            "port": 8642,
                            "cors_origins": "",
                        },
                    )
                )
                adapter._session_db = db
                session_id = db.create_session("owned-stream-session", "api_server")
                agent = _GatedAgent(session_id, pending_steer)
                response = _RecordingResponse()
                if transport in {"disconnect", "handler-cancel"}:
                    response.block_event = "run.started"
                    response.disconnect = transport == "disconnect"
                elif transport == "terminal-write":
                    response.block_event = "assistant.completed"
                elif transport in {"prepare-reset", "prepare-cancel"}:
                    response.block_prepare = True
                case = _StreamCase(adapter, agent, response)

                def create_owned_agent(**_kwargs: Any) -> _GatedAgent:
                    if gate_creation:
                        agent.loop.call_soon_threadsafe(case.creation_started.set)
                        assert case.release_creation.wait(_TIMEOUT), (
                            "agent construction release gate timed out"
                        )
                    return agent

                patcher.setattr(adapter, "_create_agent", create_owned_agent)
                patcher.setattr(api, "_publish_turn_process_ownership", Mock())
                patcher.setattr(
                    api, "_reap_disconnected_agent_processes", case.reaper
                )

                def clear_owned_process_marker(_agent: Any) -> None:
                    case.worker_cleanup_markers.append(
                        case.run_id in adapter._stopping_run_ids
                    )
                    agent.loop.call_soon_threadsafe(case.worker_exited.set)

                patcher.setattr(
                    api, "_clear_turn_process_ownership", clear_owned_process_marker
                )
                patcher.setattr(api.web, "StreamResponse", lambda **_kwargs: response)

                # Preserve the real executor owner, including its finally. The
                # gate separates worker cleanup from producer publication so a
                # premature marker discard cannot hide behind scheduling luck.
                real_run_agent = adapter._run_agent

                async def hold_completed_worker(**kwargs: Any) -> tuple:
                    case.producer_task = asyncio.current_task()
                    result = await real_run_agent(**kwargs)
                    case.worker_returned.set()
                    await case.release_producer.wait()
                    return result

                patcher.setattr(adapter, "_run_agent", hold_completed_worker)
                real_drain = adapter._drain_session_stream_task_on_disconnect

                async def observe_drain(*args: Any, **kwargs: Any) -> None:
                    case.drain_entered.set()
                    await real_drain(*args, **kwargs)

                patcher.setattr(
                    adapter, "_drain_session_stream_task_on_disconnect", observe_drain
                )
                request = SimpleNamespace(
                    match_info={"session_id": session_id},
                    headers=_AUTH_HEADERS,
                    json=AsyncMock(return_value={"message": "owned prompt"}),
                )
                case.handler_task = asyncio.create_task(
                    adapter._handle_session_chat_stream(request)
                )
                try:
                    started = (
                        case.creation_started if gate_creation else agent.worker_started
                    )
                    await asyncio.wait_for(started.wait(), _TIMEOUT)
                    assert len(adapter._run_statuses) == 1
                    case.run_id = next(iter(adapter._run_statuses))
                    if gate_creation:
                        assert case.run_id not in adapter._active_run_agents
                    else:
                        assert adapter._active_run_agents[case.run_id] is agent
                    assert case.run_id not in adapter._active_run_tasks
                    yield case
                finally:
                    # Release both gates before awaiting anything, including
                    # when the assertion under review fails on the RED source.
                    case.release_creation.set()
                    agent.release_worker.set()
                    case.release_producer.set()
                    response.release_write.set()
                    response.release_prepare.set()
                    try:
                        await asyncio.wait_for(
                            asyncio.shield(case.handler_task), _TIMEOUT
                        )
                    except asyncio.CancelledError:
                        if not (
                            case.expect_cancelled_handler
                            and case.handler_task.cancelled()
                        ):
                            raise
                    except ConnectionResetError:
                        if not case.expect_prepare_error:
                            raise
                    # A buggy producer cancellation can settle its asyncio
                    # wrapper before the constructor/executor actually exits.
                    # Keep DBs and spies alive until that real worker unwinds.
                    await asyncio.wait_for(case.worker_exited.wait(), _TIMEOUT)
                    results = await asyncio.gather(
                        *tuple(adapter._background_tasks), return_exceptions=True
                    )
                    for result in results:
                        if isinstance(result, BaseException) and not isinstance(
                            result, asyncio.CancelledError
                        ):
                            raise result
        finally:
            store.close()
            db.close()

    return create


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "pending_steer", ["", _GUIDANCE], ids=["no-leftover", "settled-leftover"]
)
async def test_stop_suppresses_session_stream_completion_and_leftover(
    stream_case: Callable, pending_steer: str
) -> None:
    async with stream_case(pending_steer) as case:
        await case.stop()
        await case.finish_worker()
        await case.finish_producer()

        status = case.adapter._run_statuses[case.run_id]
        events = case.response.events()
        assert status["status"] == "cancelled"
        assert status["last_event"] == "run.cancelled"
        assert "run.cancelled" in [name for name, _payload in events]
        assert not {"assistant.completed", "run.completed"}.intersection(
            name for name, _payload in events
        )
        assert "pending_steer" not in status
        assert all("pending_steer" not in payload for _name, payload in events)
        assert case.run_id not in case.adapter._active_run_agents


@pytest.mark.asyncio
async def test_stop_marker_survives_worker_cleanup_until_producer_finishes(
    stream_case: Callable,
) -> None:
    async with stream_case() as case:
        await case.stop()
        await case.finish_worker()

        assert case.worker_cleanup_markers == [True]
        assert case.run_id not in case.adapter._active_run_agents
        assert case.run_id in case.adapter._stopping_run_ids
        assert case.adapter._run_statuses[case.run_id]["status"] == "stopping"
        assert not case.handler_task.done()

        await case.finish_producer()
        assert case.run_id not in case.adapter._stopping_run_ids


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "pending_steer", ["", _GUIDANCE], ids=["no-leftover", "settled-leftover"]
)
async def test_unstopped_session_stream_preserves_completion_and_leftover(
    stream_case: Callable, pending_steer: str
) -> None:
    async with stream_case(pending_steer) as case:
        await case.finish_worker()
        await case.finish_producer()

        status = case.adapter._run_statuses[case.run_id]
        events = case.response.events()
        names = [name for name, _payload in events]
        assert status["status"] == "completed"
        assert names.count("assistant.completed") == names.count("run.completed") == 1
        assert "run.cancelled" not in names
        completed = next(payload for name, payload in events if name == "run.completed")
        assistant = next(
            payload for name, payload in events if name == "assistant.completed"
        )
        assert assistant["content"] == "owned completion"
        assert completed.get("pending_steer") == (pending_steer or None)
        assert status.get("pending_steer") == (pending_steer or None)
        assert not case.adapter._stopping_run_ids


@pytest.mark.asyncio
@pytest.mark.parametrize("transport", ["disconnect", "handler-cancel"])
async def test_session_stream_transport_cancel_hard_stops_worker_and_retires_leftover(
    stream_case: Callable, transport: str
) -> None:
    async with stream_case(transport=transport) as case:
        await asyncio.wait_for(case.response.write_blocked.wait(), _TIMEOUT)
        if transport == "handler-cancel":
            case.expect_cancelled_handler = True
            case.handler_task.cancel()
        else:
            case.response.release_write.set()
        await asyncio.wait_for(case.agent.interrupt_seen.wait(), _TIMEOUT)
        assert case.agent.hard_stopped.is_set()
        case.reaper.assert_called_once_with(
            case.agent, source="api_server_session_stream_disconnect"
        )
        assert case.run_id in case.adapter._stopping_run_ids
        assert case.adapter._active_run_agents[case.run_id] is case.agent
        assert not case.handler_task.done()

        await case.finish_worker()
        assert case.worker_cleanup_markers == [True]
        assert case.run_id in case.adapter._stopping_run_ids
        if transport == "handler-cancel":
            with pytest.raises(asyncio.CancelledError):
                await case.finish_producer()
        else:
            await case.finish_producer()

        status = case.adapter._run_statuses[case.run_id]
        assert status["status"] == "cancelled"
        assert "pending_steer" not in status
        assert case.run_id not in case.adapter._stopping_run_ids
        assert case.run_id not in case.adapter._active_run_agents
        assert not {"assistant.completed", "run.completed"}.intersection(
            name for name, _payload in case.response.events()
        )


@pytest.mark.asyncio
async def test_stop_during_terminal_transport_write_cannot_reopen_completed_run(
    stream_case: Callable,
) -> None:
    async with stream_case(transport="terminal-write") as case:
        await case.finish_worker()
        case.release_producer.set()
        await asyncio.wait_for(case.response.write_blocked.wait(), _TIMEOUT)

        # Transport backpressure is after the producer's completion decision.
        # A rejected late stop must not add a marker or rewrite terminal status.
        request = SimpleNamespace(
            match_info={"run_id": case.run_id}, headers=_AUTH_HEADERS
        )
        response = await case.adapter._handle_stop_run(request)
        assert response.status == 404
        assert case.adapter._run_statuses[case.run_id]["status"] == "completed"
        assert case.run_id not in case.adapter._stopping_run_ids
        assert not case.agent.hard_stopped.is_set()

        case.response.release_write.set()
        await case.finish_producer()
        assert case.adapter._run_statuses[case.run_id]["status"] == "completed"
        names = [name for name, _payload in case.response.events()]
        assert names.count("assistant.completed") == names.count("run.completed") == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("transport", ["disconnect", "handler-cancel"])
async def test_transport_cancel_during_agent_construction_keeps_executor_owned(
    stream_case: Callable, transport: str
) -> None:
    async with stream_case(transport=transport, gate_creation=True) as case:
        await asyncio.wait_for(case.response.write_blocked.wait(), _TIMEOUT)
        if transport == "handler-cancel":
            case.expect_cancelled_handler = True
            case.handler_task.cancel()
        else:
            case.response.release_write.set()
        await asyncio.wait_for(case.drain_entered.wait(), _TIMEOUT)

        assert case.run_id in case.adapter._stopping_run_ids
        assert case.producer_task is not None
        assert case.producer_task.cancelling() == 0
        assert not case.producer_task.done()
        assert case.adapter._inflight_agent_runs == 1
        assert not case.handler_task.done()
        assert not case.worker_exited.is_set()

        case.release_creation.set()
        await case.finish_worker()
        assert case.agent.hard_stopped.is_set()
        assert case.agent.conversation_calls == 0
        assert case.worker_exited.is_set()
        assert case.run_id in case.adapter._stopping_run_ids
        assert case.run_id not in case.adapter._active_run_agents
        assert case.adapter._inflight_agent_runs == 0
        if transport == "handler-cancel":
            with pytest.raises(asyncio.CancelledError):
                await case.finish_producer()
        else:
            await case.finish_producer()
        assert case.adapter._run_statuses[case.run_id]["status"] == "cancelled"
        assert case.run_id not in case.adapter._stopping_run_ids
        assert "pending_steer" not in case.adapter._run_statuses[case.run_id]
        assert not {"assistant.completed", "run.completed"}.intersection(
            name for name, _payload in case.response.events()
        )


@pytest.mark.asyncio
@pytest.mark.parametrize("transport", ["prepare-reset", "prepare-cancel"])
async def test_prepare_failure_hard_stops_and_drains_actual_session_producer(
    stream_case: Callable, transport: str
) -> None:
    async with stream_case(transport=transport) as case:
        await asyncio.wait_for(case.response.prepare_blocked.wait(), _TIMEOUT)
        if transport == "prepare-cancel":
            case.expect_cancelled_handler = True
            case.handler_task.cancel()
        else:
            case.expect_prepare_error = True
            case.response.release_prepare.set()
        await asyncio.wait_for(case.response.prepare_interrupted.wait(), _TIMEOUT)

        # prepare() reports its failure synchronously before propagating it;
        # the real handler must enter its drain before yielding back here.
        assert case.drain_entered.is_set()
        assert case.agent.hard_stopped.is_set()
        case.reaper.assert_called_once_with(
            case.agent, source="api_server_session_stream_disconnect"
        )
        assert case.run_id in case.adapter._stopping_run_ids
        assert case.adapter._active_run_agents[case.run_id] is case.agent
        assert not case.handler_task.done()

        await case.finish_worker()
        assert case.worker_cleanup_markers == [True]
        assert case.run_id in case.adapter._stopping_run_ids
        if transport == "prepare-cancel":
            with pytest.raises(asyncio.CancelledError):
                await case.finish_producer()
        else:
            await case.finish_producer()
        assert case.adapter._run_statuses[case.run_id]["status"] == "cancelled"
        assert case.run_id not in case.adapter._stopping_run_ids
        assert case.run_id not in case.adapter._active_run_agents
        assert not case.response.frames
