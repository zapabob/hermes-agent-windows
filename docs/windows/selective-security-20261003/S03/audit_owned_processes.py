"""Inspect only task-owned process footprints; never signal any process."""
import json
import os
from pathlib import Path
import subprocess
import sys

import psutil

root = Path(sys.argv[1]).resolve()
out = Path(sys.argv[2]).resolve()
assert out.is_relative_to(root / "docs/windows/selective-security-20261003")
excluded = {os.getpid(), *(item.pid for item in psutil.Process().parents())}
owned = []
for process in psutil.process_iter(["pid", "name", "create_time"]):
    if process.pid in excluded:
        continue
    try:
        cwd = Path(process.cwd()).resolve()
        in_task_temp = cwd.is_relative_to(root / "tmp")
        is_test_at_root = cwd == root and any(
            "pytest" in part or "run_tests_parallel.py" in part for part in process.cmdline()
        )
        if in_task_temp or is_test_at_root:
            owned.append(process.info)
    except (psutil.NoSuchProcess, psutil.AccessDenied, OSError):
        pass
pids = {item["pid"] for item in owned}
listeners = [{"pid": item.pid, "address": list(item.laddr)}
             for item in psutil.net_connections(kind="inet")
             if item.pid in pids and item.status == psutil.CONN_LISTEN]
head = subprocess.run(["git", "rev-parse", "HEAD"], cwd=root, capture_output=True,
                      text=True, encoding="utf-8", check=True).stdout.strip()
prepared = root / "tmp/s03-prepared.json"
receipt = {"root": str(root), "integration_head": head,
           "verification_candidate": json.loads(prepared.read_text(encoding="utf-8"))["candidate"] if prepared.is_file() else None,
           "excluded_audit_ancestor_pids": sorted(excluded),
           "owned_processes": owned, "owned_listeners": listeners,
           "signals_sent": 0,
           "scope": "Accessible process cwd under task tmp, or pytest/per-file runner at integration root; no unrelated command line or listener is retained."}
out.write_text(json.dumps(receipt, indent=2) + "\n", encoding="utf-8", newline="\n")
sys.stdout.write(json.dumps({"owned_processes": len(owned), "owned_listeners": len(listeners), "signals_sent": 0}) + "\n")
assert not owned and not listeners
