"""Native ConPTY ownership smoke: reap without relying on a drain EOF."""

import asyncio
import os
import sys
import time

import pytest

from hermes_cli.pty_session import PtySession, PtySessionRegistry


@pytest.mark.skipif(sys.platform != "win32", reason="Native ConPTY contract")
@pytest.mark.asyncio
async def test_owned_conpty_child_exit_releases_registry_slot(tmp_path):
    from hermes_cli.win_pty_bridge import WinPtyBridge

    assert WinPtyBridge.is_available(), "Mandatory native smoke requires installed pywinpty"
    script = tmp_path / "owned_child.py"
    marker = tmp_path / "effect.txt"
    script.write_text(
        "from pathlib import Path\n"
        "import time\n"
        "Path('effect.txt').write_text('owned-native-child', encoding='utf-8')\n"
        "time.sleep(0.1)\n",
        encoding="utf-8",
    )
    bridge = WinPtyBridge.spawn([sys.executable, "-I", str(script)], cwd=str(tmp_path), env=dict(os.environ))
    reg = PtySessionRegistry(ttl=30, max_sessions=1, buffer_cap=128, read_timeout=0.01)
    session = PtySession("owned", bridge, buffer_cap=128, read_timeout=0.01)
    reg._sessions["owned"] = session
    session.attached = True
    try:
        deadline = time.monotonic() + 8
        while bridge.is_alive() and time.monotonic() < deadline:
            await asyncio.sleep(0.02)
        assert not bridge.is_alive(), "Test-owned child did not exit within its budget"
        assert marker.read_text(encoding="utf-8") == "owned-native-child"
        assert session.alive  # No drain has consumed EOF.
        await reg.reap_idle()
        assert reg._sessions == {}
        assert not session.alive
    finally:
        await reg.close_all()
        await asyncio.to_thread(bridge.close)
