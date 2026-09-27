"""A server's PATHEXT must not become the gateway process's PATHEXT."""

import asyncio
import os
import shutil
import sys
import threading
from unittest.mock import patch

import pytest

from tools.mcp_tool import MCPServerTask, _resolve_stdio_command


@pytest.mark.skipif(sys.platform != "win32", reason="Windows PATHEXT contract")
def test_stdio_configured_pathext_is_not_visible_to_another_thread(tmp_path, monkeypatch):
    child_bin = tmp_path / "child-bin"
    child_bin.mkdir()
    launcher = child_bin / "n31_server.cmd"
    launcher.write_text("@echo off\r\n", encoding="utf-8")
    monkeypatch.setenv("PATHEXT", ".EXE")
    child_env = {"PATH": str(child_bin), "Pathext": ".CMD"}
    entered_retry = threading.Event()
    release_retry = threading.Event()
    finished = threading.Event()
    outcome = {}
    original_which = shutil.which
    calls = 0

    def guarded_which(command, path=None):
        nonlocal calls
        calls += 1
        if calls == 1:
            return None  # Parent PATHEXT cannot locate this .cmd launcher.
        entered_retry.set()
        if not release_retry.wait(timeout=5):
            raise TimeoutError("PATHEXT lookup was not released")
        return original_which(command, path=path)

    def resolve():
        try:
            outcome["resolved"] = _resolve_stdio_command("n31_server", child_env)
        except BaseException as exc:
            outcome["error"] = exc
        finally:
            finished.set()

    with patch("tools.mcp_tool.shutil.which", side_effect=guarded_which):
        worker = threading.Thread(target=resolve, daemon=True)
        worker.start()
        try:
            for _ in range(100):
                if entered_retry.wait(timeout=0.01) or finished.is_set():
                    break
            assert entered_retry.is_set() or finished.is_set(), "resolver did not reach a result"
            assert os.environ["PATHEXT"] == ".EXE"
        finally:
            release_retry.set()
            worker.join(timeout=5)

    assert not worker.is_alive()
    assert "error" not in outcome, outcome.get("error")
    command, resolved_env = outcome["resolved"]
    assert os.path.normcase(command) == os.path.normcase(str(launcher))
    assert resolved_env == child_env
    assert os.environ["PATHEXT"] == ".EXE"


@pytest.mark.skipif(sys.platform != "win32", reason="Windows PATHEXT contract")
@pytest.mark.parametrize("pathext, expected_suffix", [(".BAT;.CMD", ".bat"), (".CMD;.BAT", ".cmd")])
def test_stdio_configured_pathext_preserves_child_extension_order(tmp_path, monkeypatch, pathext, expected_suffix):
    child_bin = tmp_path / "child-bin"
    child_bin.mkdir()
    for suffix in (".bat", ".cmd"):
        (child_bin / f"n31_server{suffix}").write_text("@echo off\r\n", encoding="utf-8")
    monkeypatch.setenv("PATHEXT", ".EXE")
    child_env = {"PATH": str(child_bin), "PATHEXT": pathext}

    command, resolved_env = _resolve_stdio_command("n31_server", child_env)

    assert os.path.normcase(command) == os.path.normcase(str(child_bin / f"n31_server{expected_suffix}"))
    assert resolved_env == child_env
    assert os.environ["PATHEXT"] == ".EXE"


@pytest.mark.skipif(sys.platform != "win32", reason="Windows PATHEXT contract")
def test_stdio_explicit_empty_child_path_does_not_search_cwd(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "n31_local.cmd").write_text("@echo off\r\n", encoding="utf-8")
    monkeypatch.setenv("PATHEXT", ".EXE")
    child_env = {"PATH": "", "PATHEXT": ".CMD"}
    assert shutil.which("n31_local", path="") is None

    command, resolved_env = _resolve_stdio_command("n31_local", child_env)

    assert command == "n31_local"
    assert resolved_env == child_env


@pytest.mark.skipif(sys.platform != "win32", reason="Windows PATHEXT contract")
def test_stdio_respects_windows_no_default_current_directory_policy(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "n31_local.cmd").write_text("@echo off\r\n", encoding="utf-8")
    child_bin = tmp_path / "child-bin"
    child_bin.mkdir()
    monkeypatch.setenv("NoDefaultCurrentDirectoryInExePath", "1")
    monkeypatch.setenv("PATHEXT", ".EXE")
    child_env = {"PATH": str(child_bin), "PATHEXT": ".CMD"}
    assert shutil.which("n31_local", path=str(child_bin)) is None

    command, resolved_env = _resolve_stdio_command("n31_local", child_env)

    assert command == "n31_local"
    assert resolved_env == child_env


@pytest.mark.skipif(sys.platform != "win32", reason="Windows PATHEXT contract")
def test_stdio_caller_passes_configured_pathext_result_without_parent_change(tmp_path, monkeypatch):
    child_bin = tmp_path / "child-bin"
    child_bin.mkdir()
    launcher = child_bin / "n31_server.cmd"
    launcher.write_text("@echo off\r\n", encoding="utf-8")
    monkeypatch.setenv("PATHEXT", ".EXE")
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
            asyncio.run(MCPServerTask("n31-server")._run_stdio({"command": "n31_server"}))

    assert os.path.normcase(captured["command"]) == os.path.normcase(str(launcher))
    assert captured["env"] == child_env
    assert os.environ["PATHEXT"] == ".EXE"
