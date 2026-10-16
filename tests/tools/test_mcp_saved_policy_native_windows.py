"""Real Windows transport, public config/discovery/registry and cancellation.

No fake session, scheduler, connection, config reader or registry. Each test
owns its HOME, child server, port, logs and explicit cleanup observation.
"""
from contextlib import contextmanager
import hashlib
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import threading
import time

import psutil
import pytest

ROOT = Path(__file__).resolve().parents[2]
SERVER = ROOT / "tests/fixtures/mcp_admission_server.py"
pytestmark = pytest.mark.skipif(sys.platform != "win32", reason="Native Windows transport and process identity qualification.")
OPERATIONS = (
    ("write_sentinel", {"nonce": "日本語の所有済みノンス"}, "tool_effect"),
    ("list_resources", {}, "list_resources"),
    ("read_resource", {"uri": "owned://sentinel"}, "read_resource"),
    ("list_prompts", {}, "list_prompts"),
    ("get_prompt", {"name": "owned-prompt"}, "get_prompt"),
)


def rows(path):
    if not path.exists():
        return []
    text = path.read_text(encoding="utf-8")
    lines = text.splitlines()
    if not text.endswith("\n"):
        lines = lines[:-1]  # A live writer may not have finished its last row.
    return [json.loads(line) for line in lines if line]


def wait_for(predicate, seconds=8):
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        if predicate():
            return
        time.sleep(0.025)
    assert predicate(), "Owned native condition did not become true within its deadline"


@contextmanager
def native_owner(transport, tmp_path, monkeypatch, record_property):
    from hermes_cli.mcp_config import _replace_mcp_servers
    import tools.mcp_tool as core
    from tools.registry import registry

    tmp_path = (tmp_path / "mcp-admission-owned").resolve()
    tmp_path.mkdir()
    assert tmp_path.name == "mcp-admission-owned"
    owned_home = tmp_path / "owned-hermes"
    monkeypatch.setenv("HERMES_HOME", str(owned_home))
    monkeypatch.delenv("HERMES_SAFE_MODE", raising=False)
    effects = tmp_path / "effects.jsonl"
    server_dir = tmp_path / "日本語 空白 サーバー"
    server_dir.mkdir()
    owned_server = server_dir / "所有済み MCP サーバー.py"
    owned_server.write_bytes(SERVER.read_bytes())
    server_args = [str(owned_server), "--transport", transport, "--effects", str(effects), "--task-root", str(tmp_path)]
    name = "native_m02_" + transport
    child = None
    child_log = None
    owned_pids = set()
    owned_identities = {}
    owned_loops = []
    workers = []
    port = None
    prefix = "mcp__" + name + "__"
    def capture_process(process, *, observed_descendant=False):
        identity = {"pid": process.pid, "created": process.create_time(), "exe": process.exe(), "argv": process.cmdline()}
        if any(Path(arg).resolve() == owned_server for arg in identity["argv"] if arg.endswith(".py")):
            assert str(effects) in identity["argv"]
            identity["kind"] = "server"
        else:
            # Windows can attach a console host to the owned Python shim.
            # Observe its exact identity and require exit, but never kill it.
            assert observed_descendant
            assert Path(identity["exe"]).resolve() == (Path(os.environ["SYSTEMROOT"]) / "System32" / "conhost.exe").resolve()
            identity["kind"] = "console_host"
        owned_identities[(identity["pid"], identity["created"])] = identity
        owned_pids.add(process.pid)

    def capture_boots():
        for row in rows(effects):
            if row["operation"] == "boot":
                identity = {**row["identity"], "kind": "server"}
                assert any(Path(arg).resolve() == owned_server for arg in identity["argv"] if arg.endswith(".py"))
                assert str(effects) in identity["argv"]
                owned_identities[(identity["pid"], identity["created"])] = identity
                owned_pids.add(identity["pid"])

    def capture_owned_snapshot():
        capture_boots()
        if child is not None and child.poll() is None:
            parent = psutil.Process(child.pid)
            capture_process(parent)
            for descendant in parent.children(recursive=True):
                try:
                    capture_process(descendant, observed_descendant=True)
                except psutil.NoSuchProcess:
                    pass
        for pid, owner_name in core._stdio_pids.items():
            if owner_name == name:
                try:
                    capture_process(psutil.Process(pid))
                except psutil.NoSuchProcess:
                    pass

    def current_owned(identity):
        try:
            process = psutil.Process(identity["pid"])
            if process.create_time() != identity["created"]:
                return None
            assert process.exe() == identity["exe"] and process.cmdline() == identity["argv"], "Owned process identity changed"
            return process
        except psutil.NoSuchProcess:
            return None
    def save(enabled):
        ok, issues = _replace_mcp_servers({name: {**cfg, "enabled": enabled}})
        assert ok and issues == [], issues

    try:
        if transport == "stdio":
            cfg = {"command": sys.executable, "args": server_args,
                   "connect_timeout": 8, "timeout": 8}
        else:
            with socket.socket() as reservation:
                reservation.bind(("127.0.0.1", 0))
                port = reservation.getsockname()[1]
            child_log = (tmp_path / "http-server.log").open("xb")
            child = subprocess.Popen([sys.executable, *server_args, "--port", str(port)],
                                     cwd=ROOT, env=dict(os.environ), stdin=subprocess.DEVNULL,
                                     stdout=child_log, stderr=subprocess.STDOUT, creationflags=subprocess.CREATE_NO_WINDOW)
            owned_pids.add(child.pid)
            capture_process(psutil.Process(child.pid))

            def listening():
                assert child.poll() is None, "Owned HTTP server exited during startup"
                try:
                    with socket.create_connection(("127.0.0.1", port), timeout=0.1):
                        return True
                except OSError:
                    return False
            wait_for(listening)
            cfg = {"url": f"http://127.0.0.1:{port}/mcp", "transport": "http", "connect_timeout": 8, "timeout": 8}
        save(True)
        registered = core.discover_mcp_tools()
        owned_loops.append((core._mcp_loop, core._mcp_thread))
        handles = {}
        for operation, _, _ in OPERATIONS:
            tool = prefix + operation
            assert tool in registered, (tool, registered, core._server_connect_errors)
            handles[operation] = registry.get_entry(tool).handler
        capture_owned_snapshot()
        yield core, registry, name, save, handles, effects, workers
    finally:
        from tools.interrupt import set_interrupt
        errors = []
        checks = {}

        def attempt(label, action):
            try:
                action()
                checks[label] = True
            except BaseException as exc:
                checks[label] = False
                errors.append(f"{label}: {type(exc).__name__}: {exc}")

        def stop_workers():
            for index, worker in enumerate(workers):
                def signal_one(worker=worker):
                    if worker.is_alive():
                        set_interrupt(True, worker.ident, reason="Owned native fixture cleanup")
                attempt(f"interrupt_owned_worker_{index}", signal_one)
            for index, worker in enumerate(workers):
                def join_one(worker=worker):
                    if worker.ident is not None:
                        worker.join(timeout=5)
                    assert not worker.is_alive(), "Owned invocation worker survived cleanup"
                attempt(f"join_owned_worker_{index}", join_one)
                if not worker.is_alive() and worker.ident is not None:
                    attempt(f"clear_owned_worker_interrupt_{index}", lambda worker=worker: set_interrupt(False, worker.ident))

        def stop_child():
            # Reuse the owned-probe identity guard: only saved creation/exe/argv
            # matches can be stopped, including a Windows venv shim descendant.
            for identity in reversed(list(owned_identities.values())):
                if identity.get("kind") == "console_host":
                    continue
                def terminate_one(identity=identity):
                    process = current_owned(identity)
                    if process is not None:
                        process.terminate()
                attempt(f"terminate_owned_{identity['pid']}", terminate_one)
            for identity in owned_identities.values():
                def reap_one(identity=identity):
                    process = current_owned(identity)
                    if process is not None:
                        try:
                            process.wait(timeout=5)
                        except psutil.TimeoutExpired:
                            assert identity.get("kind") != "console_host", "Owned console host survived; no console termination authorised"
                            process = current_owned(identity)
                            if process is not None:
                                process.kill()
                                process.wait(timeout=5)
                attempt(f"reap_owned_{identity['pid']}", reap_one)
            if child is not None:
                child.wait(timeout=5)

        def inspect_loops():
            assert core._mcp_loop is None and core._mcp_thread is None
            assert not core._servers and not core._server_connecting
            for loop, thread in owned_loops:
                if loop is not None:
                    assert not loop.is_running() and loop.is_closed()
                if thread is not None:
                    assert not thread.is_alive()

        def inspect_listener():
            if port is not None:
                # A short nonblocking connect_ex can report WSAEWOULDBLOCK
                # before Windows delivers refusal. Require the actual error.
                def refused():
                    try:
                        with socket.create_connection(("127.0.0.1", port), timeout=4):
                            return False
                    except ConnectionRefusedError as exc:
                        assert exc.winerror == 10061, exc
                        return True
                wait_for(refused)

        attempt("capture_process_identities", capture_owned_snapshot)
        if core._mcp_loop is not None:
            owned_loops.append((core._mcp_loop, core._mcp_thread))
        attempt("workers_exited", stop_workers)
        attempt("shutdown", core.shutdown_mcp_servers)
        if transport == "stdio":
            attempt("stdio_shutdown_exited_before_fixture_reap", lambda: wait_for(
                lambda: all(current_owned(identity) is None for identity in owned_identities.values())))
        attempt("http_child_exited", stop_child)
        attempt("http_log_closed", lambda: child_log.close() if child_log is not None else None)
        attempt("all_owned_process_identities_exited", lambda: wait_for(lambda: all(current_owned(identity) is None for identity in owned_identities.values())))
        attempt("actual_loops_closed_and_threads_exited", inspect_loops)
        attempt("listener_connection_refused", inspect_listener)
        receipt = {"transport": transport, "owned_pids": sorted(owned_pids), "owned_identities": list(owned_identities.values()), "port": port,
                   "checks": checks, "cleanup_errors": errors, "all_cleanup_checks_passed": not errors,
                   "effects_sha256": hashlib.sha256(effects.read_bytes()).hexdigest() if effects.exists() else None}
        (tmp_path / "cleanup.json").write_text(json.dumps(receipt, indent=2) + "\n", encoding="utf-8")
        record_property("native_cleanup", json.dumps(receipt, sort_keys=True))
        assert not errors, errors


@pytest.mark.parametrize("transport", ("stdio", "http"))
def test_real_transport_disable_reenable_retained_registry_and_restart(transport, tmp_path, monkeypatch, record_property):
    with native_owner(transport, tmp_path, monkeypatch, record_property) as (core, registry, name, save, handles, effects, workers):
        prefix = "mcp__" + name + "__"
        schemas = {op: json.dumps(registry.get_schema(prefix + op), sort_keys=True) for op, _, _ in OPERATIONS}
        for operation, arguments, effect in OPERATIONS:
            before = sum(row["operation"] == effect for row in rows(effects))
            result = json.loads(registry.dispatch(prefix + operation, arguments))
            assert "error" not in result, result
            assert sum(row["operation"] == effect for row in rows(effects)) == before + 1
        save(False)
        before_denied = rows(effects)
        for operation, arguments, _ in OPERATIONS:
            for result in (registry.dispatch(prefix + operation, arguments), handles[operation](arguments)):
                assert json.loads(result).get("mcp_policy") == "disabled", result
            assert registry.get_entry(prefix + operation).handler is handles[operation]
            assert json.dumps(registry.get_schema(prefix + operation), sort_keys=True) == schemas[operation]
        assert rows(effects) == before_denied
        assert core._server_error_counts.get(core._resolve_server_key(name), 0) == 0
        save(True)
        for operation, arguments, effect in OPERATIONS:
            before = sum(row["operation"] == effect for row in rows(effects))
            assert "error" not in json.loads(handles[operation](arguments))
            assert sum(row["operation"] == effect for row in rows(effects)) == before + 1
        previous_loop, previous_thread = core._mcp_loop, core._mcp_thread
        core.shutdown_mcp_servers()
        assert not core._servers and core._mcp_loop is None
        assert previous_loop.is_closed() and not previous_loop.is_running()
        assert not previous_thread.is_alive()
        assert prefix + "write_sentinel" in core.discover_mcp_tools()
        result = json.loads(handles["write_sentinel"]({"nonce": "再起動後の所有済みノンス"}))
        assert "error" not in result, result
        assert any(row["operation"] == "tool_effect" and row["nonce"] == "再起動後の所有済みノンス" for row in rows(effects))


@pytest.mark.parametrize("transport", ("stdio", "http"))
def test_real_transport_admitted_completion_then_explicit_interrupt_cleanup(transport, tmp_path, monkeypatch, record_property):
    from tools.interrupt import set_interrupt
    with native_owner(transport, tmp_path, monkeypatch, record_property) as (core, registry, name, save, handles, effects, workers):
        result = []
        def call(nonce):
            try:
                result.append(json.loads(handles["write_sentinel"]({"nonce": nonce, "delay": 2})))
            finally:
                set_interrupt(False)
        worker = threading.Thread(target=call, args=("admitted-before-disable",), daemon=True)
        workers.append(worker)
        worker.start()
        wait_for(lambda: any(row["operation"] == "tool_begin" and row.get("nonce") == "admitted-before-disable" for row in rows(effects)))
        save(False)
        assert worker.is_alive(), "The admitted operation already ended before the disable acknowledgement"
        assert not any(row["operation"] == "tool_effect" and row.get("nonce") == "admitted-before-disable" for row in rows(effects))
        worker.join(timeout=5)
        assert not worker.is_alive() and len(result) == 1 and "error" not in result[0], result
        assert any(row["operation"] == "tool_effect" and row.get("nonce") == "admitted-before-disable" for row in rows(effects))
        assert json.loads(handles["write_sentinel"]({"nonce": "next-denied"})).get("mcp_policy") == "disabled"
        save(True)
        result.clear()
        worker = threading.Thread(target=call, args=("explicit-interrupt",), daemon=True)
        workers.append(worker)
        worker.start()
        wait_for(lambda: any(row["operation"] == "tool_begin" and row.get("nonce") == "explicit-interrupt" for row in rows(effects)))
        set_interrupt(True, worker.ident, reason="Owned M02 qualification interrupt")
        worker.join(timeout=5)
        assert not worker.is_alive() and len(result) == 1 and "error" in result[0], result
        wait_for(lambda: any(row["operation"] == "tool_cancelled" and row.get("nonce") == "explicit-interrupt" for row in rows(effects)))
        assert not any(row["operation"] == "tool_effect" and row.get("nonce") == "explicit-interrupt" for row in rows(effects))
        server = core._servers[core._resolve_server_key(name)]
        wait_for(lambda: not server._inflight_tasks)
