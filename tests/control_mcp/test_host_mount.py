"""The existing serve parent starts and stops the mounted SDK manager."""
import asyncio
from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi import FastAPI


@pytest.mark.asyncio
async def test_existing_parent_lifespan_enters_control_manager(monkeypatch):
    from gateway import code_skew
    from hermes_cli import web_server

    events = []

    class Host:
        @asynccontextmanager
        async def lifespan(self):
            events.append("started")
            try:
                yield
            finally:
                events.append("stopped")

    application = FastAPI()
    application.state.control_mcp_host = Host()
    for name in (
        "_eager_reconcile_own_session_db",
        "_resume_security_watch_on_startup",
        "_auto_update_security_definitions_on_startup",
        "_warm_gateway_module",
    ):
        monkeypatch.setattr(web_server, name, lambda: None)
    monkeypatch.setattr(code_skew, "record_boot_fingerprint", lambda: None)
    monkeypatch.delenv("HERMES_DESKTOP", raising=False)
    monkeypatch.delenv("HERMES_WATCHDOG_MANAGED", raising=False)

    async def idle(*_args):
        await asyncio.Event().wait()

    monkeypatch.setattr(web_server, "run_reaper", idle)
    monkeypatch.setattr(web_server, "_dashboard_selftest_loop", idle)
    monkeypatch.setattr(web_server, "_auto_archive_ticker_loop", idle)
    monkeypatch.setattr(web_server, "PTY_REGISTRY", SimpleNamespace(close_all=AsyncMock()))
    async with web_server._lifespan(application):
        assert events == ["started"]
    assert events == ["started", "stopped"]
