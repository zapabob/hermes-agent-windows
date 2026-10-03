"""Run unchanged native fixtures with a task-owned process identity ledger."""
import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time

import psutil

root = Path(sys.argv[1]).resolve() if len(sys.argv) > 1 else Path.cwd().resolve()
assert (root / "hermes_cli/_subprocess_compat.py").is_file()
sys.path.insert(0, str(root))
candidate = root / "tmp/s03-verification"
prepared = root / "tmp/s03-prepared.json"
if prepared.is_file():
    expected = json.loads(prepared.read_text(encoding="utf-8"))["candidate"]
else:
    expected = json.loads((root / "docs/windows/selective-security-20261003/S03/mutation.json").read_text(encoding="utf-8"))["candidate_head"]
assert subprocess.run(["git", "rev-parse", "HEAD"], cwd=candidate, capture_output=True,
                      text=True, check=True).stdout.strip() == expected
assert not subprocess.run(["git", "status", "--porcelain", "--untracked-files=no"],
                          cwd=candidate, capture_output=True, text=True, check=True).stdout.strip()
spec = importlib.util.spec_from_file_location("framework", root / "scripts/ci/engineering_repair_mutations.py")
framework = importlib.util.module_from_spec(spec)
spec.loader.exec_module(framework)
environment = framework.isolated_environment(root / "tmp/s03-ledger-runtime", shutil.which("git"))
audit_ancestors = {os.getpid(), *(process.pid for process in psutil.Process().parents())}

def owned_processes():
    found = []
    for process in psutil.process_iter(["pid", "create_time", "name"]):
        if process.pid in audit_ancestors:
            continue
        try:
            cwd = Path(process.cwd()).resolve()
            command = process.cmdline()
            in_temp = cwd.is_relative_to(root / "tmp")
            is_test = cwd == root and any("pytest" in item or "run_tests_parallel.py" in item for item in command)
            if in_temp or is_test:
                found.append(process.info)
        except (psutil.NoSuchProcess, psutil.AccessDenied, OSError):
            continue
    return found

before = owned_processes()
assert not before, before
launch = (
    "import pathlib,sys,importlib.util; root=pathlib.Path(sys.argv[1]).resolve(); "
    "sys.path.insert(0,str(root)); spec=importlib.util.find_spec('agent.engineering_diagnostics'); "
    "assert pathlib.Path(spec.origin).resolve().is_relative_to(root); "
    "import pytest; sys.exit(pytest.main(['--noconftest','-q','-rs','-o','addopts=']+sys.argv[2:]))"
)
argv = [sys.executable, "-I", "-B", "-c", launch, str(candidate),
        "tests/tools/test_child_credential_windows_native.py"]
process = subprocess.Popen(argv, cwd=candidate, env=environment, stdin=subprocess.DEVNULL,
                           stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
                           encoding="utf-8", creationflags=subprocess.CREATE_NO_WINDOW)
identity = psutil.Process(process.pid)
observed = {(process.pid, identity.create_time()): {"pid": process.pid, "create_time": identity.create_time(), "name": identity.name()}}
deadline = time.monotonic() + 90
try:
    while process.poll() is None:
        if time.monotonic() > deadline:
            from hermes_cli._subprocess_compat import kill_process_tree
            kill_process_tree(process)
            raise TimeoutError("Owned native ledger runner exceeded 90 seconds")
        try:
            for child in identity.children(recursive=True):
                info = {"pid": child.pid, "create_time": child.create_time(), "name": child.name()}
                observed[(child.pid, info["create_time"])] = info
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            pass
        time.sleep(0.1)
    output, _ = process.communicate(timeout=5)
finally:
    if process.poll() is None:
        from hermes_cli._subprocess_compat import kill_process_tree
        kill_process_tree(process)
        process.wait(timeout=5)

out = root / "docs/windows/selective-security-20261003/S03"
(out / "native-ledger-test.log").write_text(output, encoding="utf-8", newline="\n")
assert process.returncode == 0 and "28 passed" in output, output
after = owned_processes()
remaining_observed = []
for (pid, started), info in observed.items():
    try:
        live = psutil.Process(pid)
        if live.create_time() == started and live.is_running():
            remaining_observed.append(info)
    except psutil.NoSuchProcess:
        pass
connections = psutil.net_connections(kind="inet")
owned_pids = {item["pid"] for item in after + remaining_observed}
listeners = [{"pid": connection.pid, "address": list(connection.laddr)}
             for connection in connections if connection.pid in owned_pids and connection.status == psutil.CONN_LISTEN]
receipt = {"candidate": expected, "argv": argv, "isolated_environment_owner": "scripts/ci/engineering_repair_mutations.py",
           "excluded_audit_ancestor_pids": sorted(audit_ancestors),
           "before": before, "launched_runner": next(iter(observed.values())),
           "observed_process_identities": list(observed.values()), "after": after,
           "remaining_observed": remaining_observed, "owned_listeners": listeners,
           "exit_code": process.returncode, "native_passed": 28, "failed": 0, "skipped": 0,
           "limitation": "Descendant identity observations are polled at 100ms; very short-lived children may not appear. Final audit includes task temp cwd and pytest processes as well as all observed identities. No production process is signalled."}
(out / "native-process-ledger.json").write_text(json.dumps(receipt, indent=2) + "\n", encoding="utf-8", newline="\n")
assert not after and not remaining_observed and not listeners, receipt
sys.stdout.write(json.dumps({"native_passed": 28, "observed": len(observed), "remaining": 0, "listeners": 0}) + "\n")
