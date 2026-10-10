"""Owned issuer controlled by the native Electron test through stdin only."""

import json
import sys
import time
from pathlib import Path

import psutil

owned = Path(sys.argv[1]).resolve()
owned_root = Path(sys.argv[2]).resolve()
assert owned_root.is_dir() and owned.is_relative_to(owned_root)
sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
process = psutil.Process()
birth = {"pid": process.pid, "created": process.create_time(), "executable": process.exe(), "argv": process.cmdline()}
temporary = owned / "birth.tmp"
temporary.write_text(json.dumps(birth), encoding="utf-8")
temporary.replace(owned / "birth.json")
deadline = time.monotonic() + 8
while not (owned / "observed").exists() and time.monotonic() < deadline:
    time.sleep(0.025)
assert (owned / "observed").read_text(encoding="utf-8") == "observed"

from tests.fakes.mcp_oauth_issuer import serve_issuer

with serve_issuer() as owner:
    print(json.dumps({"ready": True, "base": owner.base, "issuer": owner.issuer, "mcp_url": owner.mcp_url}), flush=True)
    for line in sys.stdin:
        message = json.loads(line)
        action = message["action"]
        if action == "quit":
            owner.token_release.set()
            break
        if action == "authorize":
            code, state, redirect = owner.issue_code(message["url"])
            result = {"code": code, "state": state, "redirect": redirect, "iss": owner.issuer}
        elif action == "hold":
            owner.token_release.clear()
            result = {"held": True}
        elif action == "release":
            owner.token_release.set()
            result = {"released": True}
        elif action == "ledger":
            with owner.lock:
                result = {"ledger": list(owner.ledger), "token_started": owner.token_started.is_set()}
        else:
            raise AssertionError(action)
        print(json.dumps(result), flush=True)
