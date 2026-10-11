"""Additional actual callback ownership controls; authorization is a seam."""
import inspect
import json
import sys
import threading
from types import SimpleNamespace

from tests.fakes.mcp_oauth_admission import admission as admission
from tests.fakes.mcp_oauth_gateway import homes as homes, refused


def _attempt(failures, label, action):
    try:
        action()
    except BaseException as error:
        failures.append(label + ": " + repr(error))


def test_unconfirmed_callback_start_retains_slot_until_actual_native_exit(
    admission, monkeypatch, record_property,
):
    rpc, release, callers, sessions, ledger, guard, auth_release, auth_held = admission
    threads, servers = [], []
    actual_thread = threading.Thread
    actual_server = sessions.http.server.HTTPServer
    failures = []
    initial_start_calls, listener_errors = [], []

    def observed_server(*args, **kwargs):
        server = actual_server(*args, **kwargs)
        servers.append(server)
        return server

    def thread_factory(*args, **kwargs):
        thread = actual_thread(*args, **kwargs)
        if kwargs.get("name") == "mcp-oauth-cb-reports":
            threads.append(thread)
            actual_run = thread.run
            def observed_run():
                try:
                    return actual_run()
                except BaseException as error:
                    listener_errors.append(repr(error))
                    raise
            thread.run = observed_run
            def unconfirmed_start():
                initial_start_calls.append("injected_before_original_native_start")
                raise RuntimeError("Owned unresolved callback start")
            thread.start = unconfirmed_start
        return thread

    try:
        with monkeypatch.context() as local:
            local.setattr(sessions, "threading", SimpleNamespace(Thread=thread_factory))
            local.setattr(sessions, "http", SimpleNamespace(server=SimpleNamespace(
                HTTPServer=observed_server,
                BaseHTTPRequestHandler=sessions.http.server.BaseHTTPRequestHandler)))
            response = rpc("start")
        assert response["error"]["code"] == 5024
        assert response["error"]["message"] == "Owned unresolved callback start"
        sid = response["error"]["data"]["session_id"]
        rec = sessions._sessions[sid]
        assert len(threads) == len(servers) == len(initial_start_calls) == 1
        assert threads[0]._target.__self__ is servers[0]
        assert rec["httpd"] is servers[0] and not rec["flow"].worker_done
        assert not threads[0]._started.is_set() and threads[0].ident is None
        refused(servers[0].server_address[1])
        rec["created_at"] -= sessions._SESSION_TTL_SECONDS + 1
        sessions._gc_sessions()
        assert sessions._sessions.get(sid) is rec
        duplicate = rpc("start")
        assert "already in progress" in duplicate["error"]["message"]
        assert list(sessions._sessions) == [sid]
        record_property("unconfirmed_callback_owner", json.dumps({
            "response": response, "duplicate": duplicate,
            "reservation_retained": True, "actual_socket_refused": True,
            "fixture_original_native_start_invoked": False,
            "product_native_absence_proven": False,
        }))
    finally:
        primary = sys.exception()
        # Only this fixture knows it deliberately skipped original start.
        # Acquire and join that same real Thread after the seam is removed;
        # its product-owned stopped target can then confirm native completion.
        for thread in threads:
            try:
                actual_thread.start(thread)
                thread.join(timeout=6)
                assert not thread.is_alive()
            except BaseException as error:
                failures.append(repr(error))
        for index, server in enumerate(servers):
            _attempt(failures, "actual_close_" + str(index), server.server_close)
            _attempt(failures, "actual_refusal_" + str(index), lambda server=server: refused(server.server_address[1]))
        _attempt(failures, "cleanup_property", lambda: record_property("unconfirmed_callback_fixture_recovery", json.dumps({
            "failures": failures, "thread_errors": listener_errors, "same_actual_threads": len(threads),
            "actual_native_ids": [thread.native_id for thread in threads],
            "fixture_native_start_is_product_absence_proof": False,
        })))
        if failures or listener_errors:
            if primary is not None:
                primary.add_note("Callback fixture recovery failed: " + repr(failures + listener_errors))
            else:
                raise AssertionError(failures + listener_errors)
    assert rec["flow"].worker_done and rec["httpd"] is None


def test_actual_serve_entry_failure_returns_before_service_hook_release(
    admission, monkeypatch, record_property,
):
    rpc, release, callers, sessions, ledger, guard, auth_release, auth_held = admission
    entered, hook_release, returned = threading.Event(), threading.Event(), threading.Event()
    threads, servers, frames, barrier_errors, cleanup_errors = [], [], [], [], []
    outcomes = {}
    listener_errors = []
    actual_thread, actual_server = threading.Thread, sessions.http.server.HTTPServer
    cause = "Owned callback failure after actual HTTP serve entry"

    def observed_server(*args, **kwargs):
        server = actual_server(*args, **kwargs)
        servers.append(server)
        def held_service_actions():
            frame = inspect.currentframe().f_back
            while frame is not None and frame.f_code.co_name != "serve_forever":
                frame = frame.f_back
            frames.append({"function": frame.f_code.co_name if frame else None,
                "source": frame.f_code.co_filename if frame else None,
                "native_id": threading.get_native_id()})
            del frame
            entered.set()
            if not hook_release.wait(15):
                barrier_errors.append("Actual HTTP service hook was not released")
        server.service_actions = held_service_actions
        return server

    def factory(*args, **kwargs):
        if kwargs.get("name") == "mcp-oauth-cb-reports":
            target = kwargs["target"]
            def observed_target(*target_args, **target_kwargs):
                try:
                    return target(*target_args, **target_kwargs)
                except BaseException as error:
                    listener_errors.append(repr(error))
                    raise
            kwargs = {**kwargs, "target": observed_target}
        thread = actual_thread(*args, **kwargs)
        if kwargs.get("name") == "mcp-oauth-cb-reports":
            threads.append(thread)
            original_start = thread.start
            def failed_start():
                original_start()
                if not entered.wait(5):
                    barrier_errors.append("Actual HTTP serve entry was not observed")
                    raise RuntimeError("Invalid service hook experiment")
                raise RuntimeError(cause)
            thread.start = failed_start
        return thread

    def caller():
        try:
            outcomes["response"] = rpc("start")
        except BaseException as error:
            outcomes["error"] = repr(error)
        finally:
            returned.set()

    caller_thread = actual_thread(target=caller, name="owned-listener-service-entry-rpc", daemon=True)
    callers.append(caller_thread)
    try:
        with monkeypatch.context() as local:
            local.setattr(sessions, "threading", SimpleNamespace(Thread=factory))
            local.setattr(sessions, "http", SimpleNamespace(server=SimpleNamespace(
                HTTPServer=observed_server,
                BaseHTTPRequestHandler=sessions.http.server.BaseHTTPRequestHandler)))
            caller_thread.start()
            assert entered.wait(5) and not barrier_errors
            assert returned.wait(1), "Failure response blocked on held actual HTTP loop"
            assert "error" not in outcomes
            response = outcomes["response"]
            assert response["error"]["code"] == 5024 and response["error"]["message"] == cause
            sid = response["error"]["data"]["session_id"]
            rec = sessions._sessions[sid]
            assert len(threads) == len(servers) == len(frames) == 1
            assert frames[0]["function"] == "serve_forever" and frames[0]["source"].endswith("socketserver.py")
            assert frames[0]["native_id"] == threads[0].native_id
            assert rec["httpd"] is servers[0] and not rec["flow"].worker_done
            assert not hook_release.is_set()
            assert rpc("poll", session_id=sid)["result"]["error_message"] == cause
            foreign = rpc("poll", profile="other", session_id=sid)["result"]
            assert foreign["status"] == "error" and "session_id" not in foreign
            assert "already in progress" in rpc("start")["error"]["message"]
            record_property("actual_serve_entry_startup_failure", json.dumps({
                "response": response, "stdlib_frames": frames,
                "hook_release": False, "worker_done": False,
                "listener_owner_retained": True, "barrier_errors": barrier_errors,
            }))
            hook_release.set()
            threads[0].join(timeout=6)
            assert not threads[0].is_alive() and not listener_errors
            assert rec["flow"].worker_done and rec["httpd"] is None
            refused(servers[0].server_address[1])
    finally:
        primary = sys.exception()
        hook_release.set()
        if caller_thread._started.is_set():
            _attempt(cleanup_errors, "caller_join", lambda: caller_thread.join(timeout=6))
            if caller_thread.is_alive():
                cleanup_errors.append("Actual caller did not exit")
        for thread in threads:
            try:
                thread.join(timeout=6)
                assert not thread.is_alive()
            except BaseException as error:
                cleanup_errors.append(repr(error))
        for index, server in enumerate(servers):
            _attempt(cleanup_errors, "actual_close_" + str(index), server.server_close)
            _attempt(cleanup_errors, "actual_refusal_" + str(index), lambda server=server: refused(server.server_address[1]))
        _attempt(cleanup_errors, "cleanup_property", lambda: record_property("actual_serve_entry_cleanup", json.dumps({
            "failures": cleanup_errors, "barrier_errors": barrier_errors,
            "caller_exited": not caller_thread.is_alive(),
            "actual_listeners": len(threads),
            "native_ids": [thread.native_id for thread in threads],
            "listener_errors": listener_errors,
        })))
        if cleanup_errors or barrier_errors or listener_errors:
            if primary is not None:
                primary.add_note("Actual service entry cleanup failed: " + repr(cleanup_errors + barrier_errors + listener_errors))
            else:
                raise AssertionError(cleanup_errors + barrier_errors + listener_errors)
