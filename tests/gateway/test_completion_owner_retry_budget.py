"""Actual fixed-head delivery and SQLite; synthetic unavailable owner only."""
import asyncio
import threading
import time
from collections import OrderedDict
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from gateway.run import GatewayRunner
from tools import async_delegation as delegation


@pytest.mark.parametrize("batch_size", [1, 2])
def test_temporary_owner_unavailability_does_not_spend_attempts(tmp_path, monkeypatch, batch_size):
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    events = []
    for index in range(batch_size):
        event = dict(type="async_delegation", delegation_id=f"owner-budget-{index}",
                     session_key="agent:main:telegram:dm:fixture", parent_session_id="fixture-parent",
                     goal="fixture", summary="fixture complete", status="completed",
                     dispatched_at=time.time(), completed_at=time.time())
        delegation._persist_dispatch(event)
        delegation._persist_completion(event, {"status": "completed", "summary": "fixture complete"})
        events.append(event)
    observations = []
    for iteration in range(10):
        runner = object.__new__(GatewayRunner)
        runner.adapters = {}
        runner.session_store = SimpleNamespace(_ensure_loaded=lambda: None, _entries={})
        runner._session_source_cache = {}
        runner._completion_delivery_lock = threading.Lock()
        runner._completion_deliveries_inflight = set()
        runner._completion_deliveries_delivered = OrderedDict()
        runner._completion_delivery_retention = 2048
        runner._background_tasks = set()
        runner._classify_completion_target = AsyncMock(return_value="retry")
        result = asyncio.run(runner._deliver_async_delegation_group(events))
        observations.append(dict(iteration=iteration, result=result, rows=[
            {key: delegation.get_durable_delegation(event["delegation_id"])[key]
             for key in ("delivery_state", "delivery_attempts")} for event in events]))
    assert all(row == {"delivery_state": "pending", "delivery_attempts": 0}
               for observation in observations for row in observation["rows"]), observations
