"""One fresh owned process validates persisted OAuth and real registry effects."""

import json
import os
import sys
import time
from pathlib import Path

import psutil

repository = Path(__file__).resolve().parents[2]
owned_root = Path(sys.argv[5]).resolve()
home = Path(sys.argv[1]).resolve()
assert owned_root.is_dir() and home.is_relative_to(owned_root), home
os.environ["HERMES_HOME"] = str(home)
sys.path.insert(0, str(repository))

receipt_path = Path(sys.argv[4]).resolve()
assert receipt_path.is_relative_to(owned_root) and receipt_path.is_relative_to(home) and not receipt_path.exists()
me = psutil.Process()
birth = {"pid": me.pid, "created": me.create_time(), "exe": me.exe(), "argv": me.cmdline()}
birth_tmp = receipt_path.with_suffix(".birth.tmp")
with birth_tmp.open("x", encoding="utf-8") as stream:
    json.dump(birth, stream)
birth_tmp.replace(receipt_path.with_suffix(".birth.json"))
observed = receipt_path.with_suffix(".observed")
deadline = time.monotonic() + 8
while not observed.exists() and time.monotonic() < deadline:
    time.sleep(0.025)
assert observed.read_text(encoding="utf-8") == "observed"

from tools import mcp_tool as core
from tools.registry import registry

loop = thread = None
try:
    tools = core.discover_mcp_tools()
    loop, thread = core._mcp_loop, core._mcp_thread
    tool = "mcp__reports__write_sentinel"
    allowed = sys.argv[3] == "allowed"
    if allowed:
        assert tool in tools, core._server_connect_errors
        result = json.loads(registry.dispatch(tool, {"nonce": sys.argv[2]}))
        assert "error" not in result, result
    else:
        assert tool not in tools, tools
        assert any("non-interactive" in str(error) and "no cached tokens" in str(error)
                   for error in core._server_connect_errors.values()), core._server_connect_errors
        result = {"denied": True, "errors": list(core._server_connect_errors.values())}
    from hermes_cli.config import load_config
    configured_url = load_config()["mcp_servers"]["reports"]["url"]
    process = psutil.Process()
    evidence = {"pid": process.pid, "created": process.create_time(), "exe": process.exe(),
                "argv": process.cmdline(), "home": str(home), "allowed": allowed,
                "configured_url": configured_url, "result": result}
finally:
    if loop is None:
        loop, thread = core._mcp_loop, core._mcp_thread
    core.shutdown_mcp_servers()
    if loop is not None:
        assert loop.is_closed() and not loop.is_running()
        thread.join(timeout=4)
        assert not thread.is_alive()
with receipt_path.open("x", encoding="utf-8") as stream:
    json.dump(evidence, stream)
