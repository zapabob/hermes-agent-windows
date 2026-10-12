"""Fresh owned process validates persisted OAuth through actual SDK and registry."""
import hashlib
import importlib.metadata
import inspect
import json
import os
import sys
import threading
import time
from pathlib import Path

import psutil


def physical(path, root):
    assert path.is_absolute() and path.resolve() == path and path.is_relative_to(root)
    for ancestor in (path, *path.parents):
        assert not ancestor.is_symlink()
        assert not (hasattr(ancestor, "is_junction") and ancestor.is_junction())
        if ancestor == root:
            break
    return path


repository = Path(__file__).absolute().parents[2]
physical(Path(__file__).absolute(), repository)
owned_root = Path(sys.argv[5]).absolute()
home = Path(sys.argv[1]).absolute()
assert owned_root.is_dir()
physical(home, owned_root)
os.environ["HERMES_HOME"] = str(home)
sys.path.insert(0, str(repository))
receipt_path = physical(Path(sys.argv[4]).absolute(), owned_root)
assert receipt_path.is_relative_to(home) and not receipt_path.exists()
me = psutil.Process()
birth = {"pid": me.pid, "created": me.create_time(), "exe": me.exe(), "argv": me.cmdline()}
try:
    from tests.fakes.mcp_oauth_cold_process import read_handshake

    birth_tmp = receipt_path.with_suffix(".birth.tmp")
    with birth_tmp.open("x", encoding="utf-8") as stream:
        json.dump(birth, stream)
    birth_tmp.replace(receipt_path.with_suffix(".birth.json"))
    observed = receipt_path.with_suffix(".observed")
    assert read_handshake(observed, owned_root, time.monotonic() + 8) == "observed"
except BaseException as handshake_error:
    failure = {
        **birth, "home": str(home), "allowed": sys.argv[3] == "allowed", "nonce": sys.argv[2],
        "stage": "birth_handshake_before_product_imports",
        "original_body_failure": {"type": type(handshake_error).__name__, "message": str(handshake_error)},
        "product_resources_acquired": False, "imports": [], "responses": [], "browser_calls": [],
        "cleanup": {"loop_observed": False, "loop_closed": None, "loop_running": None,
                    "threads": [], "clients": []},
        "observers_restored": {}, "secondary_cleanup_failures": [],
    }
    try:
        encoded = (json.dumps(failure, indent=2) + "\n").encode("utf-8")
        with receipt_path.open("xb") as stream:
            assert stream.write(encoded) == len(encoded)
            stream.flush()
            os.fsync(stream.fileno())
    except BaseException as receipt_error:
        handshake_error.add_note("Pre-import failure receipt failed: " + repr(receipt_error))
    raise

original_error = None
secondary, responses, browser_calls, worker_errors = [], [], [], []
clients = {}
loop = thread = None
evidence = {**birth, "home": str(home), "allowed": sys.argv[3] == "allowed",
            "nonce": sys.argv[2], "imports": [], "responses": responses,
            "browser_calls": browser_calls, "unexpected_thread_errors": worker_errors}
before_threads = set(threading.enumerate())
owned_threads = set()
core = transport = original_send = original_browser = original_hook = original_start = None


def attempt(label, action):
    try:
        return action()
    except BaseException as error:
        secondary.append({"operation": label, "type": type(error).__name__, "message": str(error)})


async def observe_send(client, request, *args, **kwargs):
    clients[id(client)] = client
    response = await original_send(client, request, *args, **kwargs)
    responses.append({"method": request.method, "url": str(request.url),
                      "status": response.status_code, "response_identity": id(response),
                      "_response": response})
    return response


def observe_start(thread, *args, **kwargs):
    owned_threads.add(thread)
    return original_start(thread, *args, **kwargs)


def forbidden_browser(url, *args, **kwargs):
    browser_calls.append(str(url))
    raise AssertionError("Owned noninteractive child attempted browser authorization")


def observe_thread_error(args):
    worker_errors.append({"type": args.exc_type.__name__, "message": str(args.exc_value),
                          "thread": args.thread.name, "ident": args.thread.ident})
    original_hook(args)


try:
    from tools import mcp_tool as core
    from tools.registry import registry
    transport = core.sdk_httpx()
    from mcp.client import streamable_http as sdk_transport
    assert transport is (getattr(sdk_transport, "httpx2", None)
                         or getattr(sdk_transport, "httpx", None))
    original_send = transport.AsyncClient._send_single_request
    original_browser = __import__("webbrowser").open
    original_hook = threading.excepthook
    original_start = threading.Thread.start
    transport.AsyncClient._send_single_request = observe_send
    __import__("webbrowser").open = forbidden_browser
    threading.excepthook = observe_thread_error
    threading.Thread.start = observe_start
    tools = core.discover_mcp_tools()
    loop, thread = core._mcp_loop, core._mcp_thread
    tool = "mcp__reports__write_sentinel"
    allowed = evidence["allowed"]
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
    evidence.update(configured_url=load_config()["mcp_servers"]["reports"]["url"], result=result)
    assert browser_calls == [], browser_calls
except BaseException:
    original_error = sys.exc_info()
finally:
    def acquire_remaining_resources():
        global loop, thread
        if loop is None and core is not None:
            loop, thread = core._mcp_loop, core._mcp_thread
        owned_threads.update(set(threading.enumerate()) - before_threads)
        if thread is not None:
            owned_threads.add(thread)

    def join_thread(candidate):
        if candidate is not threading.current_thread():
            if candidate.ident is not None:
                candidate.join(timeout=4)
            assert not candidate.is_alive(), candidate.name

    def closed_loop():
        if loop is not None:
            assert loop.is_closed() and not loop.is_running()

    def cleanup_observation():
        evidence["cleanup"] = {
            "loop_observed": loop is not None,
            "loop_closed": loop.is_closed() if loop is not None else None,
            "loop_running": loop.is_running() if loop is not None else None,
            "threads": [{"name": t.name, "ident": t.ident, "native_id": t.native_id,
                         "alive": t.is_alive()} for t in owned_threads],
            "clients": [{"identity": key, "is_closed": value.is_closed}
                        for key, value in clients.items()],
        }
        for row in responses:
            response = row.pop("_response")
            row["is_closed"] = response.is_closed
        assert all(client.is_closed for client in clients.values()), evidence["cleanup"]["clients"]
        assert all(row["is_closed"] for row in responses), responses

    def restore_send():
        if original_send is not None:
            transport.AsyncClient._send_single_request = original_send

    def restore_browser():
        if original_browser is not None:
            __import__("webbrowser").open = original_browser

    def restore_hook():
        if original_hook is not None:
            threading.excepthook = original_hook

    def restore_start():
        if original_start is not None:
            threading.Thread.start = original_start

    def restore_observation():
        restored = {
            "send": original_send is not None and transport.AsyncClient._send_single_request is original_send,
            "browser": original_browser is not None and __import__("webbrowser").open is original_browser,
            "thread_hook": original_hook is not None and threading.excepthook is original_hook,
            "thread_start": original_start is not None and threading.Thread.start is original_start,
        }
        evidence["observers_restored"] = restored
        assert all(restored.values()), restored

    def cleanup_resources():
        attempt("acquire_resources", acquire_remaining_resources)
        if core is not None:
            attempt("mcp_shutdown", core.shutdown_mcp_servers)
        attempt("acquire_final_resources", acquire_remaining_resources)
        for candidate in tuple(owned_threads):
            attempt("thread_join:" + candidate.name, lambda candidate=candidate: join_thread(candidate))
        attempt("loop_closed", closed_loop)
        attempt("cleanup_observation", cleanup_observation)
    attempt("resource_cleanup", cleanup_resources)
    attempt("restore_send", restore_send)
    attempt("restore_browser", restore_browser)
    attempt("restore_thread_hook", restore_hook)
    attempt("restore_thread_start", restore_start)
    attempt("restore_observation", restore_observation)

    def metadata_observation():
        names = ["tools.mcp_tool", "tools.registry", "tools.mcp_oauth",
                 "hermes_constants", "hermes_cli.config", "mcp.client.streamable_http", "threading"]
        if transport is not None:
            names.append(transport.__name__)
        if original_send is not None:
            names.append(original_send.__module__)
        for name in names:
            def bind(name=name):
                module = sys.modules[name]
                raw = Path(inspect.getsourcefile(module) or module.__file__).absolute()
                resolved = raw.resolve()
                return {"module": name, "raw_path": str(raw), "physical_path": str(resolved),
                        "sha256": hashlib.sha256(resolved.read_bytes()).hexdigest(),
                        "bytes": resolved.stat().st_size}
            row = attempt("import_binding:" + name, bind)
            if row is not None:
                evidence["imports"].append(row)
        if original_send is not None:
            def send_binding():
                raw = Path(inspect.getsourcefile(original_send)).absolute()
                source = raw.resolve()
                return {"module": original_send.__module__, "qualname": original_send.__qualname__,
                        "raw_path": str(raw),
                        "physical_path": str(source),
                        "sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
                        "bytes": source.stat().st_size}
            evidence["observed_send_binding"] = attempt("actual_send_producer_binding", send_binding)
        evidence["runtime"] = {
            "executable": sys.executable, "prefix": sys.prefix, "base_prefix": sys.base_prefix,
            "transport_module": transport.__name__ if transport is not None else None,
            "mcp_version": attempt("mcp_version", lambda: importlib.metadata.version("mcp")),
            "env_keys": sorted(os.environ),
            "environment": {key: os.environ.get(key) for key in
                ("HOME", "HERMES_HOME", "UV_OFFLINE", "UV_NO_CONFIG", "UV_PYTHON_DOWNLOADS",
                 "PYTHONUTF8", "PYTHONHASHSEED", "PYTHONIOENCODING", "CODEGRAPH_NO_DOWNLOAD")},
        }

    attempt("metadata_observation", metadata_observation)

    def save_receipt():
        physical(receipt_path, owned_root)
        evidence["original_body_failure"] = (
            {"type": original_error[0].__name__, "message": str(original_error[1])}
            if original_error else None)
        if worker_errors:
            secondary.append({"operation": "unexpected_owned_thread_error", "errors": worker_errors})
        evidence["secondary_cleanup_failures"] = secondary.copy()
        encoded = (json.dumps(evidence, indent=2) + "\n").encode("utf-8")
        with receipt_path.open("xb") as stream:
            stream.write(encoded)
            stream.flush()
            os.fsync(stream.fileno())
        assert receipt_path.read_bytes() == encoded

    attempt("save_receipt", save_receipt)
if original_error:
    if secondary:
        original_error[1].add_note("Independent child cleanup failures: " + repr(secondary))
    raise original_error[1].with_traceback(original_error[2])
if secondary:
    raise AssertionError("Independent child cleanup failures: " + repr(secondary))
