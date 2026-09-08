"""Run actual helper call sites with an owned Windows console probe.

Extract functions to avoid starting the web application. Only the external
command is replaced; subprocess options flow unchanged into a real child.
"""
import ast
from pathlib import Path
import subprocess
import sys
from types import SimpleNamespace
from typing import Any, Dict, List

import pytest
from hermes_cli._subprocess_compat import windows_hide_flags


@pytest.mark.skipif(sys.platform != "win32", reason="Native Windows console contract")
@pytest.mark.parametrize("name", [
    "_probe_docker_backend", "_recent_upstream_commits", "_run_setup_command",
])
def test_background_helper_has_no_native_console(name, tmp_path):
    root = Path(__file__).resolve().parents[2]
    source = root / "hermes_cli" / "web_server.py"
    tree = ast.parse(source.read_text(encoding="utf-8"))
    function = next(node for node in tree.body
                    if isinstance(node, ast.FunctionDef) and node.name == name)
    outputs = []

    def run_owned_probe(command, **options):
        assert options.get("creationflags", 0) & subprocess.CREATE_NO_WINDOW
        assert not options.get("shell", False)
        # No Docker, git history, provider installation or network access.
        result = subprocess.run([
            sys.executable, "-I", "-c",
            "import ctypes; print(ctypes.windll.kernel32.GetConsoleWindow())",
        ], **options)
        outputs.append(result)
        return result

    namespace = {
        "subprocess": SimpleNamespace(run=run_owned_probe,
            CompletedProcess=subprocess.CompletedProcess,
            TimeoutExpired=subprocess.TimeoutExpired),
        "shutil": SimpleNamespace(which=lambda name: name),
        "windows_hide_flags": windows_hide_flags,
        "PROJECT_ROOT": tmp_path,
        "_memory_provider_setup_env": lambda: dict(),
        "Any": Any, "Dict": Dict, "List": List,
    }
    exec(compile(ast.Module(body=[function], type_ignores=[]), str(source), "exec"), namespace)
    if name == "_run_setup_command":
        namespace[name](["synthetic-setup"], display="Synthetic setup")
    else:
        namespace[name]()
    assert len(outputs) == 1
    assert outputs[0].returncode == 0
    assert outputs[0].stdout.strip() == "0"
    assert outputs[0].stderr == ""
