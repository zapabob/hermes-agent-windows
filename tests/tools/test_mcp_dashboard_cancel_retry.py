"""Dashboard cancellation ends its connection task without disabling retry."""

import asyncio

import pytest

from tools.mcp_dashboard_oauth import DashboardOAuthFlow, dashboard_oauth_flow


def _flow(tmp_path, name: str) -> DashboardOAuthFlow:
    return DashboardOAuthFlow(
        flow_id=name,
        server_name="reports",
        profile="work",
        hermes_home=str(tmp_path),
        redirect_uri="http://127.0.0.1:49152/callback",
    )


@pytest.mark.no_isolate
@pytest.mark.parametrize("wrapped", [False, True], ids=["direct", "task-group"])
def test_cancelled_inherited_flow_stops_before_retry(monkeypatch, tmp_path, wrapped):
    from tools import mcp_tool

    # Cold SDK initialization is outside the scheduling barrier's deadline.
    mcp_tool._ensure_mcp_sdk()

    async def scenario():
        flow = _flow(tmp_path, "cancelled-owner")
        replacement = _flow(tmp_path, "replacement-owner")
        attempts = []
        sleeps = []
        parks = []
        entered = asyncio.Event()
        release = asyncio.Event()
        failure = None
        real_sleep = asyncio.sleep

        async def fast_sleep(delay):
            sleeps.append(delay)
            await real_sleep(0)

        class Task(mcp_tool.MCPServerTask):
            async def _run_http(self, config):
                nonlocal failure
                attempts.append(len(attempts) + 1)
                await flow.publish_authorization_url("https://issuer.invalid/authorize?state=owned")
                entered.set()
                await release.wait()
                try:
                    await flow.wait_for_callback()
                except RuntimeError as exc:
                    failure = ExceptionGroup("transport", [exc]) if wrapped else exc
                    raise failure

            async def _wait_for_reconnect_or_shutdown(self, timeout=None):
                parks.append(timeout)
                return "shutdown"

        monkeypatch.setattr(mcp_tool.asyncio, "sleep", fast_sleep)
        task = Task("reports")
        with dashboard_oauth_flow(flow):
            running = asyncio.create_task(task.run({"url": "http://127.0.0.1:49152/mcp", "auth": "oauth"}))
        try:
            await asyncio.wait_for(entered.wait(), 2)
            # The task inherited A. Its caller can bind B without transferring A's authority.
            with dashboard_oauth_flow(replacement):
                assert flow.cancel_pending() is True
                release.set()
                await asyncio.wait_for(running, 2)
            assert attempts == [1], "Cancelled flow re-entered the transport"
            assert sleeps == [] and parks == [], "Cancelled flow entered retry/park"
            assert task._error is failure and task._ready.is_set()
            assert replacement.cancelled is False
        finally:
            release.set()
            if not running.done():
                running.cancel()
            await asyncio.gather(running, return_exceptions=True)

    asyncio.run(scenario())


@pytest.mark.no_isolate
def test_cancel_during_backoff_prevents_next_transport(monkeypatch, tmp_path):
    from tools import mcp_tool

    mcp_tool._ensure_mcp_sdk()

    async def scenario():
        flow = _flow(tmp_path, "backoff-owner")
        attempts = []
        sleeps = []
        parks = []
        failure = RuntimeError("transient transport failure")
        real_sleep = asyncio.sleep

        async def cancel_in_backoff(delay):
            sleeps.append(delay)
            assert flow.cancel_pending() is True
            await real_sleep(0)

        class Task(mcp_tool.MCPServerTask):
            async def _run_http(self, config):
                attempts.append(len(attempts) + 1)
                raise failure

            async def _wait_for_reconnect_or_shutdown(self, timeout=None):
                parks.append(timeout)
                return "shutdown"

        monkeypatch.setattr(mcp_tool.asyncio, "sleep", cancel_in_backoff)
        task = Task("reports")
        with dashboard_oauth_flow(flow):
            await task.run({"url": "http://127.0.0.1:49152/mcp", "auth": "oauth"})
        assert attempts == [1], "Backoff cancellation admitted another transport"
        assert len(sleeps) == 1 and parks == []
        assert task._error is failure and task._ready.is_set()

    asyncio.run(scenario())


@pytest.mark.no_isolate
@pytest.mark.parametrize("admitted", [False, True], ids=["ordinary-transient", "admitted-callback"])
def test_normal_retry_and_admitted_callback_remain_useful(monkeypatch, tmp_path, admitted):
    from tools import mcp_tool

    mcp_tool._ensure_mcp_sdk()

    async def scenario():
        flow = _flow(tmp_path, "useful-owner")
        attempts = []
        sleeps = []
        real_sleep = asyncio.sleep

        if admitted:
            await flow.publish_authorization_url("https://issuer.invalid/authorize?state=owned")
            flow.deliver_callback(code="owned-code", state="owned", error=None)
            assert flow.cancel_pending() is False
            assert await flow.wait_for_callback() == ("owned-code", "owned", None)

        async def fast_sleep(delay):
            sleeps.append(delay)
            await real_sleep(0)

        class Task(mcp_tool.MCPServerTask):
            async def _run_http(self, config):
                attempts.append(len(attempts) + 1)
                if len(attempts) == 1:
                    raise RuntimeError("transient transport failure")
                self.session = object()
                self._ever_connected = True
                self._ready.set()
                self._shutdown_event.set()

        monkeypatch.setattr(mcp_tool.asyncio, "sleep", fast_sleep)
        task = Task("reports")
        with dashboard_oauth_flow(flow):
            await task.run({"url": "http://127.0.0.1:49152/mcp", "auth": "oauth"})
        assert attempts == [1, 2] and len(sleeps) == 1
        assert task._ready.is_set() and task._error is None
        assert flow.cancelled is False

    asyncio.run(scenario())


@pytest.mark.no_isolate
def test_precancelled_flow_wakes_start_without_entering_transport(monkeypatch, tmp_path):
    from tools import mcp_tool

    mcp_tool._ensure_mcp_sdk()

    async def scenario():
        flow = _flow(tmp_path, "precancelled-owner")
        assert flow.cancel_pending() is True
        attempts = []
        real_sleep = asyncio.sleep

        async def fast_sleep(delay):
            await real_sleep(0)

        class Task(mcp_tool.MCPServerTask):
            async def _run_http(self, config):
                attempts.append(True)
                raise RuntimeError("Cancelled transport was admitted")

            async def _wait_for_reconnect_or_shutdown(self, timeout=None):
                return "shutdown"

        monkeypatch.setattr(mcp_tool.asyncio, "sleep", fast_sleep)
        task = Task("reports")
        with dashboard_oauth_flow(flow):
            with pytest.raises(RuntimeError):
                await asyncio.wait_for(task.start({"url": "http://127.0.0.1:49152/mcp", "auth": "oauth"}), 2)
        await task.shutdown()
        assert attempts == []
        assert task._ready.is_set() and isinstance(task._error, RuntimeError)
        assert task._task.done()

    asyncio.run(scenario())
