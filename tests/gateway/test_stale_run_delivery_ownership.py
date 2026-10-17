"""Stale runs must not rebaseline a replacement or resume outbound delivery.

These regressions call the real GatewayRunner helpers with an in-memory DB
facade and adapter. Run only through the campaign's owned offline runner after
allowlisting this file. They do not read source, open a DB, or contact a peer.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable, Coroutine
from pathlib import Path
import threading
from types import SimpleNamespace
from typing import TYPE_CHECKING, Any
from unittest.mock import AsyncMock, call

import pytest

if TYPE_CHECKING:
    from gateway.run import GatewayRunner


SESSION_KEY = "agent:main:telegram:dm:owned-stale-run"
SESSION_ID = "owned-session"
BOUNDARY_TIMEOUT = 5


@pytest.fixture
def runner() -> GatewayRunner:
    from gateway.run import GatewayRunner

    instance = object.__new__(GatewayRunner)
    instance._agent_cache = {}
    instance._agent_cache_lock = threading.Lock()
    instance._session_db = None
    return instance


async def _change_during_await(
    operation: Coroutine[Any, Any, Any],
    entered: asyncio.Event,
    release: asyncio.Event,
    change: Callable[[], None],
) -> None:
    """Make the ownership change only after the real owner reaches its await."""
    task = asyncio.create_task(operation)
    boundary = asyncio.create_task(entered.wait())
    try:
        done, _ = await asyncio.wait(
            {task, boundary},
            timeout=BOUNDARY_TIMEOUT,
            return_when=asyncio.FIRST_COMPLETED,
        )
        if task in done:
            # Surface an owner/API error directly instead of masking it as a
            # timeout waiting for a boundary the owner never reached.
            await task
            pytest.fail("Owner returned before the held dependency await")
        assert boundary in done, "Owner did not reach the held dependency await"
        change()
        release.set()
        await asyncio.wait_for(task, timeout=BOUNDARY_TIMEOUT)
    finally:
        release.set()
        for pending in (task, boundary):
            if not pending.done():
                pending.cancel()
        await asyncio.gather(task, boundary, return_exceptions=True)


def _entry(agent: object, count: int, bound_session: bool) -> tuple:
    entry = (agent, "owned-config-signature", count)
    return (*entry, SESSION_ID) if bound_session else entry


@pytest.mark.asyncio
@pytest.mark.parametrize("bound_session", [False, True], ids=["legacy3", "bound4"])
async def test_cache_refresh_does_not_rebaseline_a_same_session_replacement(
    runner: GatewayRunner, bound_session: bool,
) -> None:
    entered, release = asyncio.Event(), asyncio.Event()

    async def get_session(session_id: str) -> dict:
        assert session_id == SESSION_ID
        entered.set()
        await release.wait()
        return {"message_count": 41}

    lookup = AsyncMock(side_effect=get_session)
    runner._session_db = SimpleNamespace(get_session=lookup)
    runner._agent_cache[SESSION_KEY] = _entry(object(), 3, bound_session)
    replacement = _entry(object(), 7, bound_session)

    def replace_agent() -> None:
        acquired = runner._agent_cache_lock.acquire(blocking=False)
        assert acquired, "Cache lock must not remain held across the DB await"
        try:
            runner._agent_cache[SESSION_KEY] = replacement
        finally:
            runner._agent_cache_lock.release()

    # Legacy callers must also preserve a replacement installed during the await.
    await _change_during_await(
        runner._refresh_agent_cache_message_count(SESSION_KEY, SESSION_ID),
        entered, release, replace_agent,
    )

    lookup.assert_awaited_once_with(SESSION_ID)
    assert runner._agent_cache == {SESSION_KEY: replacement}


@pytest.mark.asyncio
@pytest.mark.parametrize("bound_session", [False, True], ids=["legacy3", "bound4"])
async def test_cache_refresh_does_not_rebaseline_an_invalidated_generation(
    runner: GatewayRunner, bound_session: bool,
) -> None:
    entered, release = asyncio.Event(), asyncio.Event()

    async def get_session(session_id: str) -> dict:
        assert session_id == SESSION_ID
        entered.set()
        await release.wait()
        return {"message_count": 41}

    lookup = AsyncMock(side_effect=get_session)
    runner._session_db = SimpleNamespace(get_session=lookup)
    original = _entry(object(), 3, bound_session)
    runner._agent_cache[SESSION_KEY] = original
    generation = runner._begin_session_run_generation(SESSION_KEY)

    def invalidate() -> None:
        runner._invalidate_session_run_generation(SESSION_KEY)

    await _change_during_await(
        runner._refresh_agent_cache_message_count(
            SESSION_KEY, SESSION_ID, run_generation=generation,
        ),
        entered, release, invalidate,
    )

    lookup.assert_awaited_once_with(SESSION_ID)
    assert not runner._is_session_run_current(SESSION_KEY, generation)
    assert runner._agent_cache == {SESSION_KEY: original}


@pytest.mark.asyncio
@pytest.mark.parametrize("bound_session", [False, True], ids=["legacy3", "bound4"])
@pytest.mark.parametrize("guarded", [False, True], ids=["legacy-call", "current-run"])
async def test_current_cache_refresh_preserves_the_entry_shape(
    runner: GatewayRunner, bound_session: bool, guarded: bool,
) -> None:
    lookup = AsyncMock(return_value={"message_count": 41})
    runner._session_db = SimpleNamespace(get_session=lookup)
    agent = object()
    runner._agent_cache[SESSION_KEY] = _entry(agent, 3, bound_session)
    generation = runner._begin_session_run_generation(SESSION_KEY)
    kwargs = {"run_generation": generation} if guarded else {}

    await runner._refresh_agent_cache_message_count(SESSION_KEY, SESSION_ID, **kwargs)

    lookup.assert_awaited_once_with(SESSION_ID)
    assert runner._agent_cache == {SESSION_KEY: _entry(agent, 41, bound_session)}


def _adapter() -> SimpleNamespace:
    from gateway.platforms.base import BasePlatformAdapter

    return SimpleNamespace(
        name="owned-stale-delivery",
        extract_media=BasePlatformAdapter.extract_media,
        edit_message=AsyncMock(),
        send=AsyncMock(),
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("edit_outcome", ["success", "failure", "exception"])
async def test_invalidation_during_edit_blocks_fallback_send_and_media(
    runner: GatewayRunner, edit_outcome: str,
) -> None:
    from gateway.config import Platform
    from gateway.session import SessionSource

    entered, release = asyncio.Event(), asyncio.Event()
    adapter = _adapter()
    runner._deliver_media_from_response = AsyncMock()
    source = SessionSource(platform=Platform.TELEGRAM, chat_id="owned-chat")
    generation = runner._begin_session_run_generation(SESSION_KEY)

    async def edit_message(**_kwargs: Any) -> SimpleNamespace:
        entered.set()
        await release.wait()
        if edit_outcome == "exception":
            raise RuntimeError("owned edit failed")
        return SimpleNamespace(success=edit_outcome == "success")

    adapter.edit_message.side_effect = edit_message

    def invalidate() -> None:
        runner._invalidate_session_run_generation(SESSION_KEY)

    await _change_during_await(
        runner._deliver_queued_first_response(
            "owned final response", source, adapter,
            stream_consumer=SimpleNamespace(message_id="owned-message"),
            is_current=lambda: runner._is_session_run_current(SESSION_KEY, generation),
        ),
        entered, release, invalidate,
    )

    adapter.edit_message.assert_awaited_once_with(
        chat_id=source.chat_id, message_id="owned-message",
        content="owned final response", finalize=True,
    )
    adapter.send.assert_not_awaited()
    runner._deliver_media_from_response.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("edit_outcome", ["success", "failure", "exception"])
@pytest.mark.parametrize("guarded", [False, True], ids=["legacy-call", "current-run"])
async def test_current_delivery_preserves_edit_fallback_and_media(
    runner: GatewayRunner, edit_outcome: str, guarded: bool,
) -> None:
    from gateway.config import Platform
    from gateway.session import SessionSource

    adapter = _adapter()
    adapter.edit_message.return_value = SimpleNamespace(success=edit_outcome == "success")
    if edit_outcome == "exception":
        adapter.edit_message.side_effect = RuntimeError("owned edit failed")
    runner._deliver_media_from_response = AsyncMock()
    source = SessionSource(platform=Platform.TELEGRAM, chat_id="owned-chat")
    metadata = {"thread_id": "owned-thread"}
    generation = runner._begin_session_run_generation(SESSION_KEY)
    kwargs = {
        "is_current": lambda: runner._is_session_run_current(SESSION_KEY, generation),
    } if guarded else {}

    await runner._deliver_queued_first_response(
        "owned final response", source, adapter,
        metadata=metadata, event_message_id="owned-request",
        stream_consumer=SimpleNamespace(message_id="owned-message"), **kwargs,
    )

    adapter.edit_message.assert_awaited_once()
    if edit_outcome == "success":
        adapter.send.assert_not_awaited()
    else:
        adapter.send.assert_awaited_once_with(
            source.chat_id, "owned final response", metadata=metadata,
        )
    runner._deliver_media_from_response.assert_awaited_once()
    media_args, media_kwargs = runner._deliver_media_from_response.await_args
    assert media_args[0] == "owned final response"
    assert media_args[1].source is source
    assert media_args[1].message_id == "owned-request"
    assert media_args[2] is adapter
    assert media_kwargs == {"thread_metadata": metadata, **kwargs}


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", ["legacy-call", "current-run", "invalidated-run"])
async def test_document_delivery_rechecks_generation_after_each_send(
    runner: GatewayRunner,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    mode: str,
) -> None:
    from gateway.config import Platform
    from gateway.platforms.base import BasePlatformAdapter, MessageEvent
    from gateway.session import SessionSource

    # Keep real extraction and path validation within this test's owned files.
    media_root = (tmp_path / "media-cache").resolve()
    media_root.mkdir()
    first = media_root / "first.txt"
    second = media_root / "second.txt"
    first.write_text("owned first document", encoding="utf-8")
    second.write_text("owned second document", encoding="utf-8")
    monkeypatch.setattr(
        "gateway.platforms.base.MEDIA_DELIVERY_SAFE_ROOTS", (media_root,),
    )
    response = f'MEDIA:"{first.as_posix()}"\nMEDIA:"{second.as_posix()}"'
    source = SessionSource(platform=Platform.TELEGRAM, chat_id="owned-chat")
    event = MessageEvent(text="", source=source, message_id="owned-request")
    metadata = {"thread_id": "owned-thread"}
    generation = runner._begin_session_run_generation(SESSION_KEY)
    entered, release = asyncio.Event(), asyncio.Event()

    async def send_document(**send_kwargs: Any) -> SimpleNamespace:
        if send_kwargs["file_path"] == str(first):
            entered.set()
            await release.wait()
        return SimpleNamespace(success=True)

    adapter = _adapter()
    adapter.extract_images = BasePlatformAdapter.extract_images
    adapter.send_document = AsyncMock(side_effect=send_document)
    adapter.send_multiple_images = AsyncMock()
    adapter.send_voice = AsyncMock()
    adapter.send_video = AsyncMock()
    kwargs = {
        "is_current": lambda: runner._is_session_run_current(SESSION_KEY, generation),
    } if mode != "legacy-call" else {}

    def change_generation() -> None:
        if mode == "invalidated-run":
            runner._invalidate_session_run_generation(SESSION_KEY)

    await _change_during_await(
        runner._deliver_media_from_response(
            response, event, adapter, thread_metadata=metadata, **kwargs,
        ),
        entered, release, change_generation,
    )

    expected_sends = [
        call(chat_id=source.chat_id, file_path=str(first), metadata=metadata),
    ]
    if mode != "invalidated-run":
        expected_sends.append(
            call(chat_id=source.chat_id, file_path=str(second), metadata=metadata),
        )
    assert adapter.send_document.await_args_list == expected_sends
    adapter.send.assert_not_awaited()
    adapter.send_multiple_images.assert_not_awaited()
    adapter.send_voice.assert_not_awaited()
    adapter.send_video.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", ["legacy-call", "current-run", "invalidated-run"])
async def test_default_image_batch_rechecks_generation_after_each_send(
    runner: GatewayRunner,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    mode: str,
) -> None:
    from gateway.config import Platform
    from gateway.platforms.base import BasePlatformAdapter, MessageEvent
    from gateway.session import SessionSource

    media_root = (tmp_path / "image-cache").resolve()
    media_root.mkdir()
    first = media_root / "first.png"
    second = media_root / "second.png"
    # Only path validation runs; the fake transport never decodes these bytes.
    first.write_bytes(b"owned first image")
    second.write_bytes(b"owned second image")
    monkeypatch.setattr(
        "gateway.platforms.base.MEDIA_DELIVERY_SAFE_ROOTS", (media_root,),
    )
    response = f'MEDIA:"{first.as_posix()}"\nMEDIA:"{second.as_posix()}"'
    source = SessionSource(platform=Platform.TELEGRAM, chat_id="owned-chat")
    event = MessageEvent(text="", source=source, message_id="owned-request")
    metadata = {"thread_id": "owned-thread"}
    generation = runner._begin_session_run_generation(SESSION_KEY)
    entered, release = asyncio.Event(), asyncio.Event()

    async def send_image_file(**send_kwargs: Any) -> SimpleNamespace:
        if send_kwargs["image_path"] == str(first):
            entered.set()
            await release.wait()
        return SimpleNamespace(success=True)

    adapter = _adapter()
    adapter.extract_images = BasePlatformAdapter.extract_images
    adapter.send_multiple_images = BasePlatformAdapter.send_multiple_images.__get__(
        adapter, type(adapter),
    )
    adapter.send_image_file = AsyncMock(side_effect=send_image_file)
    adapter.send_document = AsyncMock()
    adapter.send_voice = AsyncMock()
    adapter.send_video = AsyncMock()
    kwargs = {
        "is_current": lambda: runner._is_session_run_current(SESSION_KEY, generation),
    } if mode != "legacy-call" else {}

    def change_generation() -> None:
        if mode == "invalidated-run":
            runner._invalidate_session_run_generation(SESSION_KEY)

    await _change_during_await(
        runner._deliver_media_from_response(
            response, event, adapter, thread_metadata=metadata, **kwargs,
        ),
        entered, release, change_generation,
    )

    expected_sends = [
        call(
            chat_id=source.chat_id, image_path=str(first),
            caption=None, metadata=metadata,
        ),
    ]
    if mode != "invalidated-run":
        expected_sends.append(
            call(
                chat_id=source.chat_id, image_path=str(second),
                caption=None, metadata=metadata,
            ),
        )
    assert adapter.send_image_file.await_args_list == expected_sends
    adapter.send.assert_not_awaited()
    adapter.send_document.assert_not_awaited()
    adapter.send_voice.assert_not_awaited()
    adapter.send_video.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", ["legacy-call", "current-run", "invalidated-run"])
@pytest.mark.parametrize("boundary", ["stt", "echo"])
async def test_pending_voice_rechecks_generation_before_echo_send(
    runner: GatewayRunner,
    tmp_path: Path,
    mode: str,
    boundary: str,
) -> None:
    from gateway.config import Platform
    from gateway.platforms.base import MessageEvent, MessageType
    from gateway.session import SessionSource

    source = SessionSource(platform=Platform.TELEGRAM, chat_id="owned-chat")
    event = MessageEvent(
        text="owned voice prompt",
        source=source,
        message_type=MessageType.VOICE,
        media_urls=[str(tmp_path / "owned-voice.ogg")],
        media_types=["audio/ogg"],
        message_id="owned-request",
    )
    transcripts = ["owned first transcript"]
    if boundary == "echo":
        transcripts.append("owned second transcript")
    metadata = {"thread_id": "owned-thread"}
    generation = runner._begin_session_run_generation(SESSION_KEY)
    entered, release = asyncio.Event(), asyncio.Event()

    async def transcribe(received_event: Any, text: str) -> tuple[str, list[str]]:
        assert received_event is event
        assert text == event.text
        if boundary == "stt":
            entered.set()
            await release.wait()
        return "owned enriched voice", list(transcripts)

    async def send_echo(_chat_id: str, content: str, **_kwargs: Any) -> None:
        if boundary == "echo" and content == f'🎙️ "{transcripts[0]}"':
            entered.set()
            await release.wait()

    # Keep the real wrapper and shared echo owner; replace only STT and I/O.
    runner._transcribe_pending_audio_event_once = AsyncMock(side_effect=transcribe)
    runner._should_echo_stt_transcripts = lambda: True
    adapter = _adapter()
    adapter.send.side_effect = send_echo
    kwargs = {
        "is_current": lambda: runner._is_session_run_current(SESSION_KEY, generation),
    } if mode != "legacy-call" else {}

    def change_generation() -> None:
        if mode == "invalidated-run":
            runner._invalidate_session_run_generation(SESSION_KEY)

    await _change_during_await(
        runner._transcribe_and_echo_pending_voice(
            event, adapter, source, event.text,
            metadata=metadata, log_context="Owned voice boundary", **kwargs,
        ),
        entered, release, change_generation,
    )

    runner._transcribe_pending_audio_event_once.assert_awaited_once_with(
        event, event.text,
    )
    expected_transcripts = transcripts
    if mode == "invalidated-run":
        expected_transcripts = [] if boundary == "stt" else transcripts[:1]
    assert adapter.send.await_args_list == [
        call(source.chat_id, f'🎙️ "{tx}"', metadata=metadata)
        for tx in expected_transcripts
    ]
