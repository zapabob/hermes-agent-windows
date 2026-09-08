import pytest
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock
from gateway.wake import admit_internal_event, WakeNotAccepted
from tools.async_delegation import (
    defer_completion_delivery,
    defer_event_delivery,
    claim_completion_delivery,
    _transaction,
)


@pytest.mark.parametrize("mode", ["empty", "occupied", "full", "missing"])
def test_busy_fifo_receipt_matches_actual_storage(mode):
    from gateway.run import GatewayRunner
    from gateway.platforms.base import MessageType
    runner = object.__new__(GatewayRunner)
    queued = []
    state = SimpleNamespace(conversation=SimpleNamespace(queued_events=queued))
    adapter = SimpleNamespace(_pending_messages={})
    old = SimpleNamespace(internal=False, message_type=MessageType.TEXT)
    if mode in {"occupied", "full"}:
        adapter._pending_messages["owner"] = old
    if mode == "full":
        queued.extend([old] * (runner._BUSY_QUEUE_MAX_PENDING - 1))
    runner._adapter_for_source = lambda source: None if mode == "missing" else adapter
    runner._peek_session_state = lambda key: state
    runner._session_state = lambda key: state
    event = SimpleNamespace(source=object(), internal=True, allow_gateway_control=False,
                            message_type=MessageType.TEXT, _gateway_accepted=False)
    runner._queue_or_replace_pending_event("owner", event)
    accepted = mode in {"empty", "occupied"}
    assert event._gateway_accepted is accepted
    assert (adapter._pending_messages.get("owner") is event or event in queued) is accepted
    if mode in {"occupied", "full"}:
        assert adapter._pending_messages["owner"] is old


@pytest.mark.asyncio
async def test_admit_internal_event_success():
    adapter = MagicMock()
    async def fake_handle(event):
        event._gateway_accepted = True
    adapter.handle_message = AsyncMock(side_effect=fake_handle)

    event = MagicMock()
    event._gateway_accepted = False

    await admit_internal_event(adapter, event)
    adapter.handle_message.assert_awaited_once_with(event)


@pytest.mark.asyncio
async def test_admit_internal_event_rejected():
    adapter = MagicMock()
    async def fake_handle(event):
        # Did not accept
        event._gateway_accepted = False
    adapter.handle_message = AsyncMock(side_effect=fake_handle)

    event = MagicMock()
    event._gateway_accepted = False

    with pytest.raises(WakeNotAccepted):
        await admit_internal_event(adapter, event)


def test_defer_event_delivery():
    evt_other = {"type": "completion", "delivery_claim": "claim-123"}
    defer_event_delivery(evt_other, "claim-123")


def test_defer_completion_delivery(tmp_path, monkeypatch):
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))

    with _transaction() as conn:
        conn.execute(
            """
            INSERT INTO async_delegations (
                delegation_id, origin_session, state, dispatched_at, updated_at,
                delivery_state, delivery_attempts
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            ("del-test-1", "sess-1", "completed", 1000.0, 1000.0, "pending", 1)
        )

    # Claim delivery
    claim_id = "worker-1"
    ok = claim_completion_delivery("del-test-1", claim_id)
    assert ok is True

    # Defer delivery
    res = defer_completion_delivery("del-test-1", claim_id)
    assert res is True

    with _transaction() as conn:
        row = conn.execute(
            "SELECT delivery_attempts, delivery_claim FROM async_delegations WHERE delegation_id = ?",
            ("del-test-1",)
        ).fetchone()
        assert row is not None
        attempts, claim_val = row
        assert attempts == 1  # 1 initial + 1 claim - 1 defer = 1
        assert claim_val is None
