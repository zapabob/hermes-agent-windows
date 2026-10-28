"""W02: occupied webapp.port → unavailable; occupant process is never killed."""
from __future__ import annotations

import os
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from gateway.webapp_listener import WebappMount


@pytest.mark.asyncio
async def test_start_gateway_runtime_api_port_busy_sets_unavailable_without_kill(
    tmp_path, monkeypatch
) -> None:
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    (tmp_path / "config.yaml").write_text(
        "webapp:\n  enabled: true\n  host: 127.0.0.1\n  port: 9120\n",
        encoding="utf-8",
    )
    occupant_pid = os.getpid()

    runner = SimpleNamespace(
        session_api=None,
        webapp_status=None,
        session_runtime_descriptor={},
        session_authorities=None,
        session_authority=None,
    )
    private_handle = SimpleNamespace(api_origin="http://127.0.0.1:0")
    calls: list[tuple] = []

    async def _fake_start_gateway_api(runner_arg, *, host="127.0.0.1", port=0, webapp=None):
        calls.append((host, port, webapp is not None))
        if webapp is not None:
            raise OSError(10048, "Only one usage of each socket address is normally permitted")
        return private_handle

    with (
        patch("gateway.run_api.start_gateway_api", new=AsyncMock(side_effect=_fake_start_gateway_api)),
        patch("gateway.webapp_listener.register_control_verbs", lambda *_a, **_k: None),
        patch(
            "gateway.webapp_listener.listener_plan",
            lambda _home: (
                "127.0.0.1",
                9120,
                WebappMount(dist=tmp_path / "dist-webapp", home=tmp_path, public_url=""),
                None,
            ),
        ),
        patch("gateway.webapp_listener.browser_session_token", lambda *_a, **_k: "x" * 43),
        patch("os.kill") as kill_mock,
        patch("os.killpg", create=True) as killpg_mock,
    ):
        from gateway.webapp_runtime import start_gateway_runtime_api

        await start_gateway_runtime_api(runner)

    assert runner.webapp_status is not None
    assert runner.webapp_status["state"] == "unavailable"
    assert runner.webapp_status["url"] is None
    assert "9120" in str(runner.webapp_status.get("reason") or "") or "listen" in str(
        runner.webapp_status.get("reason") or ""
    ).lower()
    assert runner.session_api is private_handle
    # First attempt used the Webapp fixed port; fallback used private listener.
    assert any(port == 9120 and used_webapp for _host, port, used_webapp in calls)
    assert any(not used_webapp for _host, _port, used_webapp in calls)
    kill_mock.assert_not_called()
    if hasattr(killpg_mock, "assert_not_called"):
        killpg_mock.assert_not_called()
    assert os.getpid() == occupant_pid

