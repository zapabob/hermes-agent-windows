"""MCP stdio resolution must use the child environment as its authority."""

import asyncio
import os
import shutil
import sys
from unittest.mock import patch

import pytest

from tools.mcp_tool import MCPServerTask, _resolve_stdio_command


@pytest.fixture
def parent_only_launcher(tmp_path, monkeypatch):
    parent_bin = tmp_path / "parent-bin"
    parent_bin.mkdir()
    launcher = parent_bin / "n30_parent_only.exe"
    launcher.write_bytes(b"MZ")
    monkeypatch.setenv("PATH", str(parent_bin))
    assert os.path.normcase(shutil.which("n30_parent_only") or "") == os.path.normcase(str(launcher))
    return launcher


@pytest.mark.skipif(sys.platform != "win32", reason="Windows stdio child PATH contract")
def test_stdio_absent_child_path_does_not_import_parent_executable(parent_only_launcher):
    child_env = {"SYSTEMROOT": r"C:\Windows"}

    command, resolved_env = _resolve_stdio_command("n30_parent_only", child_env)

    assert command == "n30_parent_only"
    assert resolved_env == child_env


@pytest.mark.skipif(sys.platform != "win32", reason="Windows stdio child PATH contract")
def test_stdio_explicit_empty_child_path_stays_distinct_from_parent(parent_only_launcher):
    command, resolved_env = _resolve_stdio_command("n30_parent_only", {"PATH": ""})

    assert command == "n30_parent_only"
    assert resolved_env == {"PATH": ""}


@pytest.mark.skipif(sys.platform != "win32", reason="Windows stdio child PATH contract")
def test_stdio_absent_child_path_with_pathext_does_not_retry_parent_path(parent_only_launcher, monkeypatch):
    monkeypatch.setenv("PATHEXT", ".CMD")
    child_env = {"SYSTEMROOT": r"C:\Windows", "Pathext": ".EXE"}

    command, resolved_env = _resolve_stdio_command("n30_parent_only", child_env)

    assert command == "n30_parent_only"
    assert resolved_env == child_env
    assert os.environ["PATHEXT"] == ".CMD"


@pytest.mark.skipif(sys.platform != "win32", reason="Windows stdio child PATH contract")
@pytest.mark.parametrize("child_pathext", [None, ".EXE"])
def test_stdio_caller_does_not_forward_parent_only_command(parent_only_launcher, monkeypatch, child_pathext):
    class CapturedParameters(Exception):
        pass

    captured = {}

    def capture_parameters(**kwargs):
        captured.update(kwargs)
        raise CapturedParameters

    child_env = {"SYSTEMROOT": r"C:\Windows"}
    if child_pathext is not None:
        monkeypatch.setenv("PATHEXT", ".CMD")
        child_env["PATHEXT"] = child_pathext
    with patch("tools.mcp_tool._ensure_mcp_sdk", return_value=True), \
         patch("tools.mcp_tool._build_safe_env", return_value=child_env), \
         patch("tools.osv_check.check_package_for_malware", return_value=None), \
         patch("tools.mcp_tool.StdioServerParameters", side_effect=capture_parameters, create=True):
        with pytest.raises(CapturedParameters):
            asyncio.run(MCPServerTask("n30-server")._run_stdio({"command": "n30_parent_only"}))

    assert captured["command"] == "n30_parent_only"
    assert captured["env"] == child_env
