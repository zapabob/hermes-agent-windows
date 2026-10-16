"""Fresh owned native process checks persisted OAuth through real registry."""
from __future__ import annotations

import hashlib
import importlib
import json
import os
from pathlib import Path
import sys
import tempfile
import time

import psutil

ROOT = Path(__file__).resolve().parents[3]
assert Path(__file__).resolve() == ROOT / "apps/desktop/e2e/mcp-oauth-worker-cold.py"
OWNED_TEMP = ROOT / "tmp/probes/v0216-20261010/temp"
assert Path(tempfile.gettempdir()).resolve() == OWNED_TEMP.resolve()
home, nonce, permission, receipt = sys.argv[1:5]
HOME, RECEIPT = Path(home).resolve(), Path(receipt).resolve()
assert HOME.is_relative_to(OWNED_TEMP.resolve()) and RECEIPT.is_relative_to(HOME)
assert permission in {"allowed", "denied"} and nonce.startswith("native-worker-cold-")
assert not RECEIPT.exists()
for candidate in (HOME, RECEIPT.parent):
    for part in (candidate, *candidate.parents):
        assert not part.is_symlink() and not part.is_junction()
        if part == OWNED_TEMP:
            break
os.environ["HERMES_HOME"] = str(HOME)
sys.path.insert(0, str(ROOT))
me = psutil.Process()
birth = {"pid": me.pid, "created": me.create_time(), "executable": me.exe(), "argv": me.cmdline()}
with RECEIPT.with_suffix(".birth.json").open("x", encoding="utf-8") as stream:
    json.dump(birth, stream)
    stream.flush()
    os.fsync(stream.fileno())
observed = RECEIPT.with_suffix(".observed")
deadline = time.monotonic() + 10
while not observed.exists() and time.monotonic() < deadline:
    time.sleep(0.025)
assert observed.read_text(encoding="utf-8") == "observed"

from tools import mcp_tool as core
from tools.registry import registry

imports = {}
for name, relative in {"tools.mcp_tool": "tools/mcp_tool.py", "tools.registry": "tools/registry.py",
                       "hermes_constants": "hermes_constants.py", "tools.mcp_oauth": "tools/mcp_oauth.py",
                       "mcp.client.auth.oauth2": ".venv/Lib/site-packages/mcp/client/auth/oauth2.py"}.items():
    module = importlib.import_module(name)
    actual = Path(module.__file__).resolve()
    assert actual == (ROOT / relative).resolve()
    imports[name] = {"path": str(actual), "sha256": hashlib.sha256(actual.read_bytes()).hexdigest()}
assert imports["mcp.client.auth.oauth2"]["sha256"] == "912f43f60a023b66b05d102a5f2312affbccb6a626644f195aa6739d52c8717c"
import threading
threading_hash = hashlib.sha256(Path(threading.__file__).read_bytes()).hexdigest()
assert threading_hash == "846f450ae794e4aab823a163f8c71d27751148af33e91dd3de886686a4e8ebfb"
loops = []
original_ensure = core._ensure_mcp_loop

def capture_loop(*args, **kwargs):
    try:
        return original_ensure(*args, **kwargs)
    finally:
        loop, worker = core._mcp_loop, core._mcp_thread
        if loop is not None and not any(row[0] is loop for row in loops):
            loops.append((loop, worker))

core._ensure_mcp_loop = capture_loop
primary_failure = None
cleanup_failures = []
result = None
try:
    tools = core.discover_mcp_tools()
    tool = "mcp__reports__write_sentinel"
    if permission == "allowed":
        assert tool in tools, core._server_connect_errors
        result = json.loads(registry.dispatch(tool, {"nonce": nonce}))
        assert "error" not in result, result
    else:
        assert tool not in tools, tools
        assert any("non-interactive" in str(error) and "no cached tokens" in str(error)
                   for error in core._server_connect_errors.values()), core._server_connect_errors
        result = {"denied": True, "errors": list(core._server_connect_errors.values())}
except BaseException as error:
    primary_failure = error
finally:
    try:
        core.shutdown_mcp_servers()
    except BaseException as error:
        cleanup_failures.append("SDK shutdown: " + repr(error))
    for loop, worker in loops:
        try:
            assert loop.is_closed() and not loop.is_running()
        except BaseException as error:
            cleanup_failures.append("Exact loop closure: " + repr(error))
        try:
            assert worker is not None and worker._started.wait(timeout=5)
            worker.join(timeout=8)
            assert not worker.is_alive()
        except BaseException as error:
            cleanup_failures.append("Exact loop thread join: " + repr(error))
    try:
        core._ensure_mcp_loop = original_ensure
    except BaseException as error:
        cleanup_failures.append("Loop creator restoration: " + repr(error))
    try:
        with RECEIPT.open("x", encoding="utf-8") as stream:
            json.dump({"birth": birth, "home": str(HOME), "permission": permission, "nonce": nonce,
                       "result": result, "imports": imports, "hook_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
                       "python": sys.version, "threading_sha256": threading_hash, "loops": len(loops), "cleanup_completed": not cleanup_failures, "cleanup_failures": cleanup_failures,
                       "primary_failure": None if primary_failure is None else repr(primary_failure)}, stream, indent=2)
            stream.flush()
            os.fsync(stream.fileno())
    except BaseException as error:
        cleanup_failures.append("Exclusive receipt recording: " + repr(error))
if primary_failure is not None:
    if cleanup_failures:
        primary_failure.add_note("Owned cold cleanup failures: " + repr(cleanup_failures))
    raise primary_failure
assert not cleanup_failures, cleanup_failures
