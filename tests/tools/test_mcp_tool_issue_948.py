import asyncio
import os
import sys
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


from tools.mcp_tool import (
    MCPServerTask,
    _format_connect_error,
    _prefer_windows_exe,
    _resolve_stdio_command,
    _MCP_AVAILABLE,
)

# Ensure the mcp module symbols exist for patching even when the SDK isn't installed
if not _MCP_AVAILABLE:
    import tools.mcp_tool as _mcp_mod
    if not hasattr(_mcp_mod, "StdioServerParameters"):
        _mcp_mod.StdioServerParameters = MagicMock
    if not hasattr(_mcp_mod, "stdio_client"):
        _mcp_mod.stdio_client = MagicMock
    if not hasattr(_mcp_mod, "ClientSession"):
        _mcp_mod.ClientSession = MagicMock


def test_resolve_stdio_command_falls_back_to_hermes_node_bin(tmp_path):
    node_bin = tmp_path / "node" / "bin"
    node_bin.mkdir(parents=True)
    npx_path = node_bin / "npx"
    npx_path.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    npx_path.chmod(0o755)

    with patch("tools.mcp_tool.shutil.which", return_value=None), \
         patch.dict("os.environ", {"HERMES_HOME": str(tmp_path)}, clear=False):
        command, env = _resolve_stdio_command("npx", {"PATH": "/usr/bin"})

    assert command == str(npx_path)
    assert env["PATH"].split(os.pathsep)[0] == str(node_bin)


def test_resolve_stdio_command_falls_back_to_usr_local_bin():
    """When ``npx`` isn't on the filtered PATH and isn't under ``$HERMES_HOME/node/bin``
    or ``~/.local/bin``, the resolver should still locate it at ``/usr/local/bin/npx``.

    This is the canonical install location for Node on Linux from-source builds,
    the upstream ``node:bookworm-slim`` image (which the Hermes Docker image
    copies ``node + npm + corepack`` from since #4977), and macOS Homebrew on
    Intel. Without this candidate, MCP servers run with an ``env.PATH`` that
    omits ``/usr/local/bin`` (common when users hand-author PATH for sandboxing)
    fail with ENOENT at ``execvp``.
    """
    target = os.path.join(os.sep, "usr", "local", "bin", "npx")

    # Pretend ONLY the /usr/local/bin/npx candidate exists and is executable —
    # the other candidates ($HERMES_HOME/node/bin/npx and ~/.local/bin/npx)
    # should fail isfile() and the resolver must fall through to /usr/local/bin.
    def _fake_isfile(path):
        return path == target

    def _fake_access(path, _mode):
        return path == target

    with patch("tools.mcp_tool.shutil.which", return_value=None), \
         patch("tools.mcp_tool.os.path.isfile", side_effect=_fake_isfile), \
         patch("tools.mcp_tool.os.access", side_effect=_fake_access):
        command, env = _resolve_stdio_command("npx", {"PATH": "/opt/data/bin:/usr/bin:/bin"})

    assert command == target
    # /usr/local/bin must be prepended so npx's shebang (`/usr/bin/env node`)
    # can find node in the same directory.
    assert env["PATH"].split(os.pathsep)[0] == os.path.dirname(target)


def test_prefer_windows_exe_swaps_cmd_shim_when_sibling_exists(tmp_path):
    """Pure helper: platform is data — prefer sibling .exe over .cmd/.bat."""
    cmd_shim = tmp_path / "uvx.cmd"
    exe = tmp_path / "uvx.exe"
    cmd_shim.write_text("@echo off\r\n", encoding="utf-8")
    exe.write_bytes(b"MZ")

    assert _prefer_windows_exe(str(cmd_shim), is_windows=True) == str(exe)
    assert _prefer_windows_exe(str(cmd_shim), is_windows=False) == str(cmd_shim)

    bat_only = tmp_path / "lonely.bat"
    bat_only.write_text("@echo off\r\n", encoding="utf-8")
    assert _prefer_windows_exe(str(bat_only), is_windows=True) == str(bat_only)
    assert _prefer_windows_exe(str(exe), is_windows=True) == str(exe)


@pytest.mark.skipif(sys.platform != "win32", reason="Windows GUI PATH contract")
@pytest.mark.parametrize("launcher", ["uv", "uvx"])
def test_windows_stdio_uv_launcher_uses_profile_bin_before_user_bin(tmp_path, monkeypatch, launcher):
    managed_home = tmp_path / "profile"
    managed_bin = managed_home / "bin"
    managed_bin.mkdir(parents=True)
    user_home = tmp_path / "user"
    user_bin = user_home / ".local" / "bin"
    user_bin.mkdir(parents=True)
    managed_exe = managed_bin / f"{launcher}.exe"
    user_exe = user_bin / f"{launcher}.exe"
    managed_exe.write_bytes(b"MZ")
    user_exe.write_bytes(b"MZ")
    monkeypatch.setenv("HERMES_HOME", str(managed_home))
    monkeypatch.setenv("USERPROFILE", str(user_home))
    child_path = r"C:\Windows\System32"

    with patch("tools.mcp_tool.shutil.which", return_value=None):
        command, env = _resolve_stdio_command(launcher, {"PATH": child_path})
        assert command == str(managed_exe)
        assert env["PATH"].split(os.pathsep) == [str(managed_bin), child_path]

        managed_exe.unlink()
        command, env = _resolve_stdio_command(launcher, {"PATH": child_path})
        assert command == str(user_exe)
        assert env["PATH"].split(os.pathsep) == [str(user_bin), child_path]

        user_exe.unlink()
        user_shim = user_bin / f"{launcher}.cmd"
        user_shim.write_text("@echo off\r\n", encoding="utf-8")
        command, env = _resolve_stdio_command(launcher, {"PATH": child_path})
        assert command == str(user_shim)
        assert env["PATH"].split(os.pathsep) == [str(user_bin), child_path]


@pytest.mark.skipif(sys.platform != "win32", reason="Windows GUI PATH contract")
def test_windows_stdio_uvx_uses_active_profile_override(tmp_path, monkeypatch):
    from hermes_constants import reset_hermes_home_override, set_hermes_home_override

    process_home = tmp_path / "process-home"
    active_home = tmp_path / "active-profile"
    for home in (process_home, active_home):
        bin_dir = home / "bin"
        bin_dir.mkdir(parents=True)
        (bin_dir / "uvx.exe").write_bytes(b"MZ")
    monkeypatch.setenv("HERMES_HOME", str(process_home))
    token = set_hermes_home_override(active_home)
    try:
        with patch("tools.mcp_tool.shutil.which", return_value=None):
            command, env = _resolve_stdio_command("uvx", {"PATH": r"C:\Windows\System32"})
    finally:
        reset_hermes_home_override(token)

    assert command == str(active_home / "bin" / "uvx.exe")
    assert env["PATH"].split(os.pathsep)[0] == str(active_home / "bin")


@pytest.mark.skipif(sys.platform != "win32", reason="Windows GUI PATH contract")
def test_windows_stdio_uv_launcher_preserves_child_path_hit_and_unknown_command(tmp_path, monkeypatch):
    managed_home = tmp_path / "profile"
    managed_bin = managed_home / "bin"
    managed_bin.mkdir(parents=True)
    (managed_bin / "uvx.exe").write_bytes(b"MZ")
    monkeypatch.setenv("HERMES_HOME", str(managed_home))
    child_path = r"C:\Selected\bin"
    selected = child_path + r"\uvx.exe"

    with patch("tools.mcp_tool.shutil.which", return_value=selected):
        assert _resolve_stdio_command("uvx", {"PATH": child_path}) == (
            selected, {"PATH": child_path}
        )
    with patch("tools.mcp_tool.shutil.which", return_value=None):
        assert _resolve_stdio_command("other-launcher", {"PATH": child_path}) == (
            "other-launcher", {"PATH": child_path}
        )


# ---------------------------------------------------------------------------
# #29184: OSV malware preflight must not block the asyncio event loop, and a
# stalled check must time out fail-open rather than freezing MCP startup.
# ---------------------------------------------------------------------------


def _stdio_mocks():
    mock_session = MagicMock()
    mock_session.initialize = AsyncMock()
    mock_session.list_tools = AsyncMock(return_value=SimpleNamespace(tools=[]))
    mock_stdio_cm = MagicMock()
    mock_stdio_cm.__aenter__ = AsyncMock(return_value=(object(), object()))
    mock_stdio_cm.__aexit__ = AsyncMock(return_value=False)
    mock_session_cm = MagicMock()
    mock_session_cm.__aenter__ = AsyncMock(return_value=mock_session)
    mock_session_cm.__aexit__ = AsyncMock(return_value=False)
    return mock_stdio_cm, mock_session_cm


@pytest.mark.skipif(sys.platform != "win32", reason="Windows GUI PATH contract")
def test_windows_stdio_caller_passes_resolved_uvx_and_path_to_sdk(tmp_path, monkeypatch):
    managed_home = tmp_path / "profile"
    managed_bin = managed_home / "bin"
    managed_bin.mkdir(parents=True)
    managed_exe = managed_bin / "uvx.exe"
    managed_exe.write_bytes(b"MZ")
    monkeypatch.setenv("HERMES_HOME", str(managed_home))
    mock_stdio_cm, mock_session_cm = _stdio_mocks()
    child_path = r"C:\Windows\System32"

    async def exercise():
        with patch("tools.mcp_tool.shutil.which", return_value=None), \
             patch("tools.osv_check.check_package_for_malware", return_value=None), \
             patch("tools.mcp_tool.StdioServerParameters") as params, \
             patch("tools.mcp_tool.stdio_client", return_value=mock_stdio_cm), \
             patch("tools.mcp_tool.ClientSession", return_value=mock_session_cm):
            server = MCPServerTask("uvx-server")
            await server.start({"command": "uvx", "args": ["example"], "env": {"PATH": child_path}})
            try:
                kwargs = params.call_args.kwargs
                assert kwargs["command"] == str(managed_exe)
                assert kwargs["env"]["PATH"].split(os.pathsep) == [str(managed_bin), child_path]
            finally:
                await server.shutdown()

    asyncio.run(exercise())


def test_run_stdio_malware_check_does_not_block_event_loop():
    """The blocking OSV check runs off the loop (asyncio.to_thread), so a
    concurrent coroutine keeps making progress while it runs."""
    import time
    mock_stdio_cm, mock_session_cm = _stdio_mocks()

    def slow_check(_command, _args):
        time.sleep(0.3)  # simulate a slow OSV HTTPS call
        return None

    ticks = {"n": 0}

    async def _ticker():
        # If the loop were blocked, these ticks would not advance during the
        # 0.3s check.
        for _ in range(20):
            await asyncio.sleep(0.01)
            ticks["n"] += 1

    async def _test():
        with patch("tools.osv_check.check_package_for_malware", side_effect=slow_check), \
             patch("tools.mcp_tool.StdioServerParameters"), \
             patch("tools.mcp_tool.stdio_client", return_value=mock_stdio_cm), \
             patch("tools.mcp_tool.ClientSession", return_value=mock_session_cm):
            server = MCPServerTask("srv")
            ticker = asyncio.create_task(_ticker())
            await server.start({"command": "npx", "args": ["-y", "pkg"]})
            ticks_during = ticks["n"]
            await ticker
            await server.shutdown()
        # The loop kept ticking DURING the 0.3s blocking check -> not blocked.
        assert ticks_during >= 3, f"event loop appeared blocked (ticks={ticks_during})"

    asyncio.run(_test())


def test_run_stdio_malware_check_times_out_fail_open():
    """A check that hangs past the timeout must NOT freeze startup: it times
    out, logs, and proceeds (fail-open) so the server still starts."""
    import time
    mock_stdio_cm, mock_session_cm = _stdio_mocks()

    def hung_check(_command, _args):
        time.sleep(0.5)  # outlasts the 0.2s timeout 2.5x; short enough not to stall teardown
        return "MALWARE"  # would block startup if awaited to completion

    async def _test():
        with patch("tools.osv_check.check_package_for_malware", side_effect=hung_check), \
             patch("tools.mcp_tool._OSV_MALWARE_CHECK_TIMEOUT_S", 0.2), \
             patch("tools.mcp_tool.StdioServerParameters"), \
             patch("tools.mcp_tool.stdio_client", return_value=mock_stdio_cm), \
             patch("tools.mcp_tool.ClientSession", return_value=mock_session_cm):
            server = MCPServerTask("srv")
            start = time.monotonic()
            await server.start({"command": "npx", "args": ["-y", "pkg"]})
            elapsed = time.monotonic() - start
            await server.shutdown()
        # Returned shortly after the 0.2s timeout (fail-open), not the 0.5s hang.
        assert elapsed < 1.0, f"startup did not fail-open promptly ({elapsed:.1f}s)"

    asyncio.run(_test())
