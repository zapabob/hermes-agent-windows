"""Fresh owned process exercising real MCP discovery and registry dispatch."""
import argparse
import json
import os
from pathlib import Path
import sys
import time

import psutil

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--owned", type=Path, required=True)
    parser.add_argument("--name", required=True)
    parser.add_argument("--nonce", required=True)
    parser.add_argument("--receipt", type=Path, required=True)
    args = parser.parse_args()
    owned = args.owned.resolve()
    home = Path(os.environ["HERMES_HOME"]).resolve()
    receipt_path = args.receipt.resolve()
    assert owned.name == "mcp-admission-owned" and home.is_relative_to(owned)
    assert receipt_path.is_relative_to(owned) and not receipt_path.exists()
    assert args.name == "native_m02_stdio"
    me = psutil.Process()
    birth = {"pid": me.pid, "created": me.create_time(), "exe": me.exe(), "argv": me.cmdline()}
    birth_path = receipt_path.with_suffix(".birth.json")
    go_path = receipt_path.with_suffix(".observed")
    birth_temporary = receipt_path.with_suffix(".birth.tmp")
    assert not birth_path.exists()
    with birth_temporary.open("x", encoding="utf-8") as stream:
        json.dump(birth, stream)
    birth_temporary.replace(birth_path)
    # Hold only for actual identity/lineage observation; no product owner is mocked.
    deadline = time.monotonic() + 8
    while not go_path.exists() and time.monotonic() < deadline:
        time.sleep(0.025)
    assert go_path.read_text(encoding="utf-8") == "observed"
    from tools import mcp_tool as core
    from tools.registry import registry
    receipt = {"process": {"pid": me.pid, "created": me.create_time(), "exe": me.exe(), "argv": me.cmdline()},
               "owner_module": str(Path(core.__file__).resolve()), "home": str(home), "registered": [], "result": None}
    identities = []
    loop = thread = None
    try:
        receipt["registered"] = core.discover_mcp_tools()
        target = "mcp__" + args.name + "__write_sentinel"
        if target in receipt["registered"]:
            receipt["result"] = json.loads(registry.dispatch(target, {"nonce": args.nonce}))
        for pid in core._stdio_pids:
            try:
                process = psutil.Process(pid)
                identity = {"pid": process.pid, "created": process.create_time(), "exe": process.exe(), "argv": process.cmdline()}
                assert any(Path(arg).resolve().is_relative_to(owned) for arg in identity["argv"] if arg.endswith(".py"))
                identities.append(identity)
                for child in process.children(recursive=True):
                    identities.append({"pid": child.pid, "created": child.create_time(), "exe": child.exe(), "argv": child.cmdline()})
            except psutil.NoSuchProcess:
                pass
        loop, thread = core._mcp_loop, core._mcp_thread
    finally:
        core.shutdown_mcp_servers()
        deadline = time.monotonic() + 8
        def survivors():
            live = []
            for identity in identities:
                try:
                    process = psutil.Process(identity["pid"])
                    if process.create_time() == identity["created"]:
                        assert process.exe() == identity["exe"] and process.cmdline() == identity["argv"]
                        live.append(identity["pid"])
                except psutil.NoSuchProcess:
                    pass
            return live
        while survivors() and time.monotonic() < deadline:
            time.sleep(0.025)
        receipt["owned_identities"] = identities
        receipt["survivors"] = survivors()
        receipt["loop_closed"] = loop is None or loop.is_closed()
        receipt["thread_exited"] = thread is None or not thread.is_alive()
        with receipt_path.open("x", encoding="utf-8") as stream:
            json.dump(receipt, stream, ensure_ascii=False, indent=2)
            stream.write("\n")
        assert receipt["survivors"] == [] and receipt["loop_closed"] and receipt["thread_exited"]


if __name__ == "__main__":
    main()
