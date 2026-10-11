"""Test-owned native worker startup seam; copied as sitecustomize.py.

Never installed outside one fresh E2E sandbox. Public RPC results are observed
unchanged. Native ownership is retained until exact started events and joins.
"""
from __future__ import annotations

import functools
import hashlib
import importlib.abc
import importlib.machinery
import importlib.metadata
import json
import os
from pathlib import Path
import sys
import threading
import time

import psutil

BOOT = Path(__file__).resolve().parent
CONFIG = json.loads((BOOT / "configuration.json").read_text(encoding="utf-8"))
ROOT = Path(CONFIG["repository"]).resolve()
OWNED_TEMP = ROOT / "tmp/probes/v0216-20261010/temp"
HOME = Path(CONFIG["home"]).resolve()
assert BOOT.is_relative_to(OWNED_TEMP.resolve()) and HOME.is_relative_to(OWNED_TEMP.resolve())
assert BOOT.parent == HOME.parent and BOOT.name == "worker-bootstrap"
assert CONFIG["mode"] in {"constructor", "bootstrap_held"}
for candidate in (BOOT, HOME):
    for part in (candidate, *candidate.parents):
        assert not part.is_symlink() and not part.is_junction(), str(part)
        if part == OWNED_TEMP:
            break
assert hashlib.sha256(Path(__file__).read_bytes()).hexdigest() == CONFIG["hook_sha256"]
assert hashlib.sha256(Path(threading.__file__).read_bytes()).hexdigest() == CONFIG["threading_sha256"]

LOCK = threading.RLock()
ORIGINAL_THREAD = threading.Thread
ROWS = []
CONSTRUCTOR_FLOWS = []
RESTORERS = []
ABORT = threading.Event()
LOOPS = []
MODULES = {}
FAILURES = []
FAULT_USED = False
NATIVE_ACQUIRED = threading.Event()
BOOTSTRAP_RELEASE = threading.Event()
CONTROL_COMPLETE = threading.Event()
CONTROL = None
CONTROL_START_ATTEMPTED = False
CONTROL_STARTED_CONFIRMED = False
PUBLIC_HANDLERS = {}
SEQUENCE = 0
CAUSE = "Owned native Gateway worker startup failure"
ME = psutil.Process()
BIRTH = {"pid": ME.pid, "created": ME.create_time(), "executable": ME.exe(), "argv": ME.cmdline()}
LEDGER = BOOT / ("observations-" + str(ME.pid) + ".jsonl")
with LEDGER.open("x", encoding="utf-8") as stream:
    stream.flush()
    os.fsync(stream.fileno())


def record(kind, **values):
    global SEQUENCE
    with LOCK:
        SEQUENCE += 1
        row = {"sequence": SEQUENCE, "kind": kind, "birth": BIRTH, **values}
        with LEDGER.open("a", encoding="utf-8", newline="\n") as stream:
            stream.write(json.dumps(row) + "\n")
            stream.flush()
            os.fsync(stream.fileno())


def failure(label, error):
    with LOCK:
        FAILURES.append(label + ": " + repr(error))
    ABORT.set()
    try:
        record("operational_failure", label=label, error=repr(error))
    except BaseException as secondary:
        with LOCK:
            FAILURES.append("failure_record: " + repr(secondary))


def attempt(label, action):
    try:
        action()
    except BaseException as error:
        failure(label, error)


def actual_home():
    from hermes_constants import get_hermes_home
    return get_hermes_home().expanduser().resolve()


def bind(module):
    source = Path(module.__file__).resolve()
    expected = ROOT / CONFIG["modules"][module.__name__]["path"]
    assert source == expected.resolve()
    digest = hashlib.sha256(source.read_bytes()).hexdigest()
    assert digest == CONFIG["modules"][module.__name__]["sha256"], module.__name__
    record("module_binding", module=module.__name__, path=str(source), sha256=digest,
           actual_home=str(actual_home()), active=actual_home() == HOME)
    return actual_home() == HOME


def install_banner(module):
    # The server imports this function during its own original module execution.
    # Binding must finish here, before the original server loader can continue.
    active_home = actual_home()
    assert active_home.is_relative_to(HOME.parent), active_home
    original = module.prefetch_update_check
    source = Path(module.__file__).resolve()
    assert original.__module__ == module.__name__
    assert original.__name__ == "prefetch_update_check"
    assert Path(original.__code__.co_filename).resolve() == source
    lifetime = "default_finish" if active_home == HOME else "owned_process_exit"

    @functools.wraps(original)
    def contained():
        assert module.prefetch_update_check is contained
        caller = sys._getframe(1)
        caller_source = Path(caller.f_code.co_filename).resolve()
        assert caller_source == (ROOT / CONFIG["modules"]["tui_gateway.server"]["path"]).resolve()
        assert hashlib.sha256(caller_source.read_bytes()).hexdigest() == CONFIG["modules"]["tui_gateway.server"]["sha256"]
        record("banner_prefetch_contained", original_invoked=False,
               caller_path=str(caller_source), caller_line=caller.f_lineno,
               actual_home=str(actual_home()), lifetime=lifetime)

    def restore():
        def check_identity():
            assert module.prefetch_update_check is contained
        def check_restoration():
            assert module.prefetch_update_check is original
        attempt("banner_containment_identity", check_identity)
        attempt("banner_containment_restore", lambda: setattr(module, "prefetch_update_check", original))
        attempt("banner_containment_restore_identity", check_restoration)
        attempt("banner_containment_restore_record", lambda: record("banner_containment_restored",
                module=module.__name__, path=str(source), original_identity=module.prefetch_update_check is original,
                completed=not FAILURES, actual_home=str(actual_home()), lifetime=lifetime))

    module.prefetch_update_check = contained
    # Foreign profile backends retain only this no-op until their confirmed
    # owned process exit. They acquire no additional watcher or fault injection.
    if active_home == HOME:
        MODULES["hermes_cli.banner"] = module
        MODULES["banner_original_prefetch"] = original
        RESTORERS.append(("banner_prefetch", restore))
    record("banner_containment_installed", module=module.__name__, path=str(source),
           sha256=CONFIG["modules"][module.__name__]["sha256"], original_identity_bound=True,
           actual_home=str(active_home), lifetime=lifetime, extra_watcher_acquired=False)


def release_file(name, timeout):
    path = BOOT / name
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if ABORT.is_set():
            raise RuntimeError('Owned native bootstrap aborted: ' + repr(FAILURES))
        if path.exists():
            assert not path.is_symlink() and not path.is_junction()
            assert path.read_text(encoding="utf-8") == "release"
            return
        time.sleep(0.025)
    raise TimeoutError("Owned native release missing: " + name)


def row_snapshot(row):
    worker, flow = row["worker"], row["flow"]
    return {"flow_id": flow.flow_id, "object_id": id(worker), "ident": worker.ident,
            "actual_started_event": worker._started.is_set(), "worker_done": flow.worker_done,
            "snapshot": flow.snapshot(), "native_acquired": row.get("native_acquired", False),
            "native_id": row.get("native_id"), "original_start_invoked": row.get("original_start_invoked", False)}


def ensure_loop(module):
    original = module._ensure_mcp_loop
    @functools.wraps(original)
    def observed(*args, **kwargs):
        try:
            return original(*args, **kwargs)
        finally:
            loop, worker = module._mcp_loop, module._mcp_thread
            if loop is not None:
                with LOCK:
                    if not any(row["loop"] is loop for row in LOOPS):
                        LOOPS.append({"loop": loop, "worker": worker})
                        attempt("loop_acquisition_record", lambda: record("sdk_loop_acquired", object_id=id(loop),
                                thread_object_id=id(worker), ident=None if worker is None else worker.ident))
    module._ensure_mcp_loop = observed
    MODULES["core_original_ensure"] = original
    RESTORERS.append(('core_ensure_loop', lambda: setattr(module, '_ensure_mcp_loop', original)))


def settle_workers(label):
    with LOCK:
        rows, constructor_flows = list(ROWS), list(CONSTRUCTOR_FLOWS)
    for flow in constructor_flows:
        def settled_constructor(flow=flow):
            assert flow.worker_done and flow.snapshot()["status"] == "error"
            assert flow.snapshot()["error"] == CAUSE
            assert not any(row["flow"] is flow for row in rows)
            record("constructor_settled", phase=label, flow_id=flow.flow_id,
                   worker_done=flow.worker_done, worker_acquired=False, snapshot=flow.snapshot())
        attempt("constructor_settled_" + flow.flow_id, settled_constructor)
    for row in rows:
        def join_worker(row=row):
            worker = row["worker"]
            assert row["original_start_invoked"], "No original native start authority"
            assert worker._started.wait(timeout=15), "Actual native startup unconfirmed"
            worker.join(timeout=30)
            assert not worker.is_alive(), "Exact native worker still alive"
            assert row["flow"].worker_done, "Actual worker finally did not complete"
            record("native_worker_joined", phase=label, **row_snapshot(row))
        attempt("worker_join_" + row["flow"].flow_id, join_worker)
    core = MODULES.get("tools.mcp_tool")
    if core is not None:
        attempt("actual_sdk_shutdown", core.shutdown_mcp_servers)
    with LOCK:
        loops = list(LOOPS)
    for row in loops:
        def observe_loop_closed(row=row):
            assert row["loop"].is_closed() and not row["loop"].is_running()
            record("sdk_loop_closed", phase=label, object_id=id(row["loop"]))
        def join_loop_thread(row=row):
            worker = row["worker"]
            assert worker is not None and worker._started.wait(timeout=5)
            worker.join(timeout=8)
            assert not worker.is_alive()
            record("sdk_loop_thread_joined", phase=label, object_id=id(row["loop"]), thread_object_id=id(worker))
        attempt("loop_closed_" + str(id(row["loop"])), observe_loop_closed)
        attempt("loop_thread_join_" + str(id(row["loop"])), join_loop_thread)

def restore_waits_and_release():
    with LOCK:
        rows = list(ROWS)
    try:
        for row in rows:
            if row.get("original_wait") is not None:
                attempt("restore_wait_" + row["flow"].flow_id,
                        lambda row=row: setattr(row["worker"]._started, "wait", row["original_wait"]))
    finally:
        BOOTSTRAP_RELEASE.set()


def terminal_cleanup(*, preserve_poll=False):
    restore_waits_and_release()
    settle_workers("terminal-cleanup")
    for label, restore in reversed(RESTORERS):
        attempt("restore_" + label, restore)
    finder = globals().get("OWNED_FINDER")
    if finder in sys.meta_path:
        attempt("restore_import_finder", lambda: sys.meta_path.remove(finder))
    server = MODULES.get("tui_gateway.server")
    if server is not None:
        for method, handler in PUBLIC_HANDLERS.items():
            # Keep one existing read handler until it can join this controller.
            if not preserve_poll or method != "mcp.servers.oauth.poll":
                attempt("restore_" + method, lambda method=method, handler=handler: server._methods.__setitem__(method, handler))


def control_body():
    try:
        release_file("release-worker", 180)
        restore_waits_and_release()
        settle_workers("failed-start")
        record("failed_start_cleanup", completed=not FAILURES, failures=list(FAILURES))
        assert not FAILURES, FAILURES
        release_file("finish", 180)
    except BaseException as error:
        failure("owned_control", error)
    finally:
        attempt("terminal_cleanup", lambda: terminal_cleanup(preserve_poll=True))
        CONTROL_COMPLETE.set()
        attempt("control_completion_record", lambda: record("control_completed", completed=not FAILURES, failures=list(FAILURES)))

def install_sessions(module):
    global CONTROL, CONTROL_START_ATTEMPTED, CONTROL_STARTED_CONFIRMED
    MODULES[module.__name__] = module
    class ThreadProxy:
        def __getattr__(self, name):
            return getattr(threading, name)

        def Thread(self, *args, **kwargs):
            global FAULT_USED
            if kwargs.get("name") != "mcp-oauth-reports" or kwargs.get("target") is not module._worker:
                return ORIGINAL_THREAD(*args, **kwargs)
            arguments = kwargs["args"]
            if Path(arguments[1]).resolve() != HOME or arguments[2] != 'reports':
                return ORIGINAL_THREAD(*args, **kwargs)
            flow = module._sessions[arguments[0]]["flow"]
            with LOCK:
                inject = not FAULT_USED
                if inject:
                    FAULT_USED = True
            if inject and CONFIG["mode"] == "constructor":
                CONSTRUCTOR_FLOWS.append(flow)
                record("constructor_failure_gate", flow_id=flow.flow_id, worker_acquired=False,
                       worker_done=flow.worker_done, cause=CAUSE)
                release_file("return-failure", 120)
                raise RuntimeError(CAUSE)
            worker = ORIGINAL_THREAD(*args, **kwargs)
            row = {"worker": worker, "flow": flow, "original_start_invoked": False}
            with LOCK:
                ROWS.append(row)
            original_start = worker.start
            def start():
                row["original_start_invoked"] = True
                record("worker_start_attempt", injected=inject, **row_snapshot(row))
                return original_start()
            worker.start = start
            RESTORERS.append(('worker_start_' + flow.flow_id, lambda worker=worker, original_start=original_start: setattr(worker, 'start', original_start)))
            if inject:
                original_bootstrap, original_wait = worker._bootstrap_inner, worker._started.wait
                row["original_wait"] = original_wait
                def bootstrap():
                    # Avoid current_thread() before original ident assignment.
                    row["native_acquired"] = True
                    row["native_id"] = threading.get_native_id()
                    row["native_ident"] = threading.get_ident()
                    try:
                        record("native_before_ident", **row_snapshot(row))
                        NATIVE_ACQUIRED.set()
                        assert BOOTSTRAP_RELEASE.wait(180), "Owned bootstrap release timed out"
                    except BaseException as error:
                        failure("native_bootstrap", error)
                    finally:
                        worker._bootstrap_inner = original_bootstrap
                        original_bootstrap()
                def wait(timeout=None):
                    assert NATIVE_ACQUIRED.wait(15), "Native acquisition unconfirmed"
                    record("native_failure_gate", **row_snapshot(row), cause=CAUSE)
                    release_file("return-failure", 120)
                    raise RuntimeError(CAUSE)
                RESTORERS.append(('worker_bootstrap_' + flow.flow_id, lambda worker=worker, original_bootstrap=original_bootstrap: setattr(worker, '_bootstrap_inner', original_bootstrap)))
                worker._bootstrap_inner = bootstrap
                worker._started.wait = wait
            return worker
    original_threading = module.threading
    RESTORERS.append(('sessions_threading', lambda: setattr(module, 'threading', original_threading)))
    module.threading = ThreadProxy()
    CONTROL = ORIGINAL_THREAD(target=control_body, daemon=True, name="owned-native-startup-control")
    CONTROL_START_ATTEMPTED = True
    CONTROL.start()
    CONTROL_STARTED_CONFIRMED = CONTROL._started.wait(timeout=5)
    assert CONTROL_STARTED_CONFIRMED, 'Actual control startup unconfirmed'
    record("worker_hook_ready", actual_home=str(actual_home()), control_ident=CONTROL.ident,
           control_object_id=id(CONTROL), mode=CONFIG["mode"],
           control_original_start_attempted=CONTROL_START_ATTEMPTED, control_actual_started=CONTROL_STARTED_CONFIRMED)


def no_control_cleanup(server):
    # A name-only poll returns before the sessions lazy import. This path may
    # settle an acquired SDK loop, but must never invent worker/control exit.
    finish = BOOT / "finish"
    assert finish.is_file() and not finish.is_symlink()
    assert finish.resolve() == finish.absolute() and finish.read_bytes() == b"release"
    assert actual_home() == HOME and MODULES.get("tui_gateway.server") is server
    process = psutil.Process(BIRTH["pid"])
    assert process.create_time() == BIRTH["created"]
    assert process.exe() == BIRTH["executable"] and process.cmdline() == BIRTH["argv"]
    with LOCK:
        assert CONTROL is None and not CONTROL_START_ATTEMPTED and not CONTROL_STARTED_CONFIRMED
        assert not FAULT_USED and not ROWS and not CONSTRUCTOR_FLOWS
        loops = list(LOOPS)
    # Both the actual shutdown and the exact thread joins run outside LOCK.
    attempt("no_control_terminal_cleanup", terminal_cleanup)

    def verify_restoration():
        assert actual_home() == HOME
        with LOCK:
            assert CONTROL is None and not CONTROL_START_ATTEMPTED and not CONTROL_STARTED_CONFIRMED
            assert not FAULT_USED and not ROWS and not CONSTRUCTOR_FLOWS
            assert len(LOOPS) == len(loops) and all(a is b for a, b in zip(LOOPS, loops))
        assert MODULES["hermes_cli.banner"].prefetch_update_check is MODULES["banner_original_prefetch"]
        assert OWNED_FINDER not in sys.meta_path
        assert all(server._methods[key] is original for key, original in PUBLIC_HANDLERS.items())
        for row in loops:
            assert row["loop"].is_closed() and not row["loop"].is_running()
            worker = row["worker"]
            assert worker is not None and worker._started.is_set() and not worker.is_alive()

    attempt("no_control_restoration_check", verify_restoration)
    def observe_cleanup():
        record("no_control_cleanup", actual_home=str(actual_home()),
               control_acquired=CONTROL is not None,
               control_start_attempted=CONTROL_START_ATTEMPTED,
               control_started_confirmed=CONTROL_STARTED_CONFIRMED,
               fault_used=FAULT_USED, oauth_workers=len(ROWS), constructor_flows=len(CONSTRUCTOR_FLOWS),
               acquired_sdk_loops=len(loops), sdk_loops=[{
                   "object_id": id(row["loop"]), "closed": row["loop"].is_closed(),
                   "running": row["loop"].is_running(), "thread_object_id": id(row["worker"]),
                   "ident": None if row["worker"] is None else row["worker"].ident,
                   "native_id": None if row["worker"] is None else row["worker"].native_id,
                   "actual_started": row["worker"] is not None and row["worker"]._started.is_set(),
                   "alive": None if row["worker"] is None else row["worker"].is_alive()
               } for row in loops],
               banner_original_identity=MODULES["hermes_cli.banner"].prefetch_update_check is MODULES["banner_original_prefetch"],
               import_finder_restored=OWNED_FINDER not in sys.meta_path,
               rpc_handlers_restored=all(server._methods[key] is original for key, original in PUBLIC_HANDLERS.items()),
               controller_join_claimed=False, completed=not FAILURES, failures=list(FAILURES))
    attempt("no_control_cleanup_record", observe_cleanup)


def install_server(module):
    MODULES[module.__name__] = module
    for action in ("start", "poll", "cancel", "callback"):
        method = "mcp.servers.oauth." + action
        original = module._methods[method]
        PUBLIC_HANDLERS[method] = original
        def make(original, action):
            @functools.wraps(original)
            def observed(rid, params):
                try:
                    result = original(rid, params)
                except BaseException as error:
                    failure("actual_public_handler_" + action, error)
                    raise
                # Preserve the real wire result even when observation fails.
                attempt("public_response_record_" + action, lambda: record("public_rpc", action=action,
                        params=params, response=result, owner_rows=[row_snapshot(row) for row in list(ROWS)],
                        constructor_rows=[{"flow_id": flow.flow_id, "worker_done": flow.worker_done,
                                           "snapshot": flow.snapshot()} for flow in list(CONSTRUCTOR_FLOWS)]))
                if action == "poll" and CONTROL is None and (BOOT / "finish").is_file():
                    attempt("no_control_cleanup", lambda: no_control_cleanup(module))
                if action == "poll" and CONTROL_COMPLETE.is_set() and CONTROL is not None:
                    joined = []
                    def join_control():
                        assert CONTROL_START_ATTEMPTED and CONTROL._started.wait(timeout=5)
                        CONTROL.join(timeout=5)
                        assert not CONTROL.is_alive(), "Exact control thread still alive"
                        joined.append(True)
                    attempt("exact_control_join", join_control)
                    for method, handler in PUBLIC_HANDLERS.items():
                        attempt("restore_public_" + method,
                                lambda method=method, handler=handler: module._methods.__setitem__(method, handler))
                    attempt("control_join_record", lambda: record("control_joined", object_id=id(CONTROL),
                            ident=CONTROL.ident, actual_join_confirmed=bool(joined), completed=not FAILURES,
                            failures=list(FAILURES), rpc_handlers_restored=all(module._methods[key] is original
                                    for key, original in PUBLIC_HANDLERS.items())))
                return result
            return observed
        module._methods[method] = make(original, action)
    record("public_observer_ready", actual_home=str(actual_home()))


class ObservedLoader(importlib.abc.Loader):
    def __init__(self, original, fullname):
        self.original, self.fullname = original, fullname

    def create_module(self, spec):
        return self.original.create_module(spec)

    def exec_module(self, module):
        try:
            self.original.exec_module(module)
            active = bind(module)
            if self.fullname == "hermes_cli.banner":
                install_banner(module)
            if not active:
                return
            if self.fullname == "tui_gateway.mcp_oauth_sessions":
                install_sessions(module)
            elif self.fullname == "tui_gateway.server":
                install_server(module)
            elif self.fullname == "tools.mcp_tool":
                MODULES[self.fullname] = module
                ensure_loop(module)
                sdk = importlib.import_module("mcp.client.auth.oauth2")
                source = Path(sdk.__file__).resolve()
                assert source == (ROOT / ".venv/Lib/site-packages/mcp/client/auth/oauth2.py").resolve()
                sdk_hash = hashlib.sha256(source.read_bytes()).hexdigest()
                assert sdk_hash == "912f43f60a023b66b05d102a5f2312affbccb6a626644f195aa6739d52c8717c"
                assert importlib.metadata.version("mcp") == "2.0.0"
                record("installed_sdk_binding", path=str(source), sha256=sdk_hash, version="2.0.0")
        except BaseException as error:
            failure("module_install_" + self.fullname, error)
            # Original import/install failures retain their own exception.
            # A partially created core may already own a loop/thread.
            if self.fullname == "tools.mcp_tool":
                partial_loop = getattr(module, "_mcp_loop", None)
                if partial_loop is not None:
                    LOOPS.append({"loop": partial_loop, "worker": getattr(module, "_mcp_thread", None)})
                    if hasattr(module, "shutdown_mcp_servers"):
                        MODULES[self.fullname] = module
            restore_waits_and_release()
            if CONTROL is not None and CONTROL_START_ATTEMPTED:
                def settle_control_start():
                    assert CONTROL._started.wait(timeout=5), "Control native startup unconfirmed after attempted start"
                    CONTROL.join(timeout=60)
                    assert not CONTROL.is_alive(), "Control termination unconfirmed after import failure"
                    record("failed_import_control_joined", object_id=id(CONTROL), ident=CONTROL.ident)
                attempt("failed_import_control_start_join", settle_control_start)
            attempt("partial_install_terminal_cleanup", terminal_cleanup)
            raise


class OwnedFinder(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname not in CONFIG["modules"]:
            return None
        spec = importlib.machinery.PathFinder.find_spec(fullname, path, target)
        assert spec is not None and spec.loader is not None
        spec.loader = ObservedLoader(spec.loader, fullname)
        return spec


for required in ("hermes_cli.banner", "tui_gateway.server"):
    if required in sys.modules:
        error = RuntimeError("Pre-import banner containment unavailable: " + required)
        failure("banner_preimport_boundary", error)
        raise error
assert "hermes_cli.banner" in CONFIG["modules"]
OWNED_FINDER = OwnedFinder()
sys.meta_path.insert(0, OWNED_FINDER)
record("bootstrap_bound", hook_sha256=CONFIG["hook_sha256"], threading_sha256=CONFIG["threading_sha256"],
       expected_home=str(HOME), mode=CONFIG["mode"], runtime=sys.version)
