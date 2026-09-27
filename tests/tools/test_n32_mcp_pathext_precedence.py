"""An explicit MCP child PATHEXT selects its own stdio launcher."""

import asyncio
import os
import sys
from unittest.mock import patch

import pytest

from tools.mcp_tool import MCPServerTask, _build_safe_env, _resolve_stdio_command


@pytest.fixture
def sibling_launchers(tmp_path):
    child_bin = tmp_path / "child-bin"
    child_bin.mkdir()
    exe = child_bin / "n32_server.exe"
    cmd = child_bin / "n32_server.cmd"
    exe.write_bytes(b"MZ")
    cmd.write_text("@echo off\r\n", encoding="utf-8")
    return child_bin, exe, cmd


@pytest.mark.skipif(sys.platform != "win32", reason="Windows PATHEXT contract")
def test_explicit_child_pathext_wins_over_parent_exe(sibling_launchers, monkeypatch):
    child_bin, exe, cmd = sibling_launchers
    monkeypatch.setenv("PATHEXT", ".EXE")

    command, child_env = _resolve_stdio_command(
        "n32_server", {"PATH": str(child_bin), "PATHEXT": ".CMD"}
    )

    assert os.path.normcase(command) == os.path.normcase(str(cmd))
    assert os.path.normcase(command) != os.path.normcase(str(exe))
    assert child_env["PATHEXT"] == ".CMD"
    assert os.environ["PATHEXT"] == ".EXE"


@pytest.mark.skipif(sys.platform != "win32", reason="Windows PATHEXT contract")
def test_default_child_pathext_keeps_existing_exe_preference(sibling_launchers, monkeypatch):
    child_bin, exe, _ = sibling_launchers
    monkeypatch.setenv("PATHEXT", ".CMD;.EXE")

    command, _ = _resolve_stdio_command("n32_server", {"PATH": str(child_bin)})

    assert os.path.normcase(command) == os.path.normcase(str(exe))


@pytest.mark.skipif(sys.platform != "win32", reason="Windows PATHEXT contract")
def test_stdio_caller_forwards_child_selected_command(sibling_launchers, monkeypatch):
    child_bin, exe, cmd = sibling_launchers
    monkeypatch.setenv("PATHEXT", ".CMD")
    child_env = {"PATH": str(child_bin), "PATHEXT": ".CMD"}

    class CapturedParameters(Exception):
        pass

    captured = {}

    def capture_parameters(**kwargs):
        captured.update(kwargs)
        raise CapturedParameters

    with patch("tools.mcp_tool._ensure_mcp_sdk", return_value=True), \
         patch("tools.mcp_tool._build_safe_env", return_value=child_env), \
         patch("tools.osv_check.check_package_for_malware", return_value=None), \
         patch("tools.mcp_tool.StdioServerParameters", side_effect=capture_parameters, create=True):
        with pytest.raises(CapturedParameters):
            asyncio.run(MCPServerTask("n32-server")._run_stdio({
                "command": "n32_server",
                "env": {"PATH": str(child_bin), "PATHEXT": ".CMD"},
            }))

    assert os.path.normcase(captured["command"]) == os.path.normcase(str(cmd))
    assert os.path.normcase(captured["command"]) != os.path.normcase(str(exe))
    assert captured["env"]["PATHEXT"] == ".CMD"


@pytest.mark.skipif(sys.platform != "win32", reason="Windows PATHEXT contract")
def test_stdio_caller_without_explicit_pathext_keeps_exe_preference(sibling_launchers, monkeypatch):
    child_bin, exe, _ = sibling_launchers
    monkeypatch.setenv("PATHEXT", ".CMD;.EXE")
    child_env = {"PATH": str(child_bin), "PATHEXT": ".CMD;.EXE"}

    class CapturedParameters(Exception):
        pass

    captured = {}

    def capture_parameters(**kwargs):
        captured.update(kwargs)
        raise CapturedParameters

    with patch("tools.mcp_tool._ensure_mcp_sdk", return_value=True), \
         patch("tools.mcp_tool._build_safe_env", return_value=child_env), \
         patch("tools.osv_check.check_package_for_malware", return_value=None), \
         patch("tools.mcp_tool.StdioServerParameters", side_effect=capture_parameters, create=True):
        with pytest.raises(CapturedParameters):
            asyncio.run(MCPServerTask("n32-server")._run_stdio({"command": "n32_server"}))

    assert os.path.normcase(captured["command"]) == os.path.normcase(str(exe))


@pytest.mark.skipif(sys.platform != "win32", reason="Windows environment key contract")
@pytest.mark.parametrize("path_key, pathext_key", [
    ("PATH", "Pathext"),
    ("Path", "pathext"),
])
def test_stdio_caller_merges_mixed_case_child_environment(
    sibling_launchers, monkeypatch, path_key, pathext_key,
):
    child_bin, exe, cmd = sibling_launchers
    monkeypatch.setenv("PATHEXT", ".EXE")

    class CapturedParameters(Exception):
        pass

    captured = {}

    def capture_parameters(**kwargs):
        captured.update(kwargs)
        raise CapturedParameters

    with patch("tools.mcp_tool._ensure_mcp_sdk", return_value=True), \
         patch("tools.osv_check.check_package_for_malware", return_value=None), \
         patch("tools.mcp_tool.StdioServerParameters", side_effect=capture_parameters, create=True):
        with pytest.raises(CapturedParameters):
            asyncio.run(MCPServerTask("n32-server")._run_stdio({
                "command": "n32_server",
                "env": {path_key: str(child_bin), pathext_key: ".CMD"},
            }))

    assert os.path.normcase(captured["command"]) == os.path.normcase(str(cmd))
    assert os.path.normcase(captured["command"]) != os.path.normcase(str(exe))
    child_env = captured["env"]
    assert [key for key in child_env if key.upper() == "PATH"] == ["PATH"]
    assert [key for key in child_env if key.upper() == "PATHEXT"] == ["PATHEXT"]
    assert child_env["PATHEXT"] == ".CMD"


@pytest.mark.skipif(sys.platform != "win32", reason="Windows environment key contract")
def test_user_environment_overrides_inherited_safe_key_case_insensitively(monkeypatch):
    monkeypatch.setenv("APPDATA", r"C:\parent")

    child_env = _build_safe_env({"AppData": r"C:\child"})

    assert [key for key in child_env if key.upper() == "APPDATA"] == ["AppData"]
    assert child_env["AppData"] == r"C:\child"
