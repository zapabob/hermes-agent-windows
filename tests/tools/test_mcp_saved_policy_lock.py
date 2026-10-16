"""Supplemental M02 oracle with real asyncio.Lock waiting and threads.

The session remains a fake effect counter. Only acquire instrumentation is
added to the actual asyncio.Lock; the blocked waiter is observed before the
real config write. The public sync handler runs in a worker, and its coroutine
runs on the same main event loop as the lock, as in the production bridge.
"""

import asyncio
import json

import pytest

from tests.tools.test_mcp_saved_policy import OPERATIONS, handler_for, owner  # noqa: F401


@pytest.mark.parametrize("operation,factory,args", OPERATIONS)
def test_actual_waiter_rechecks_saved_policy_after_lock_release(owner, monkeypatch, operation, factory, args):
    async def scenario():
        waiting = asyncio.Event()
        loop = asyncio.get_running_loop()

        class ObservedLock(asyncio.Lock):
            async def acquire(self):
                if self.locked():
                    waiting.set()
                return await super().acquire()

        lock = ObservedLock()
        owner.server._rpc_lock = lock
        monkeypatch.setattr(owner.core, "_run_on_mcp_loop", lambda make, timeout=30:
                            asyncio.run_coroutine_threadsafe(make(), loop).result(timeout))
        handler = handler_for(owner, factory)
        await lock.acquire()
        call = asyncio.create_task(asyncio.to_thread(handler, args))
        try:
            await asyncio.wait_for(waiting.wait(), timeout=2)
            assert lock.locked() and not call.done()
            assert owner.calls == []
            owner.save(False)
        finally:
            lock.release()
        denied = json.loads(await asyncio.wait_for(call, timeout=3))
        assert owner.calls == [], "Actual blocked waiter was admitted after saved disable"
        assert "error" in denied and "disabled" in denied["error"].lower()
        assert owner.core._server_error_counts.get(owner.name, 0) == 0
        owner.save(True)
        restored = json.loads(await asyncio.to_thread(handler, args))
        assert "error" not in restored
        assert len(owner.calls) == 1 and owner.calls[0][0] == operation

    asyncio.run(scenario())
