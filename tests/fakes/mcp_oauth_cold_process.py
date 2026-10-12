"""Owned native MCP OAuth process launcher and exception-preserving fixtures."""
import json
import subprocess
import sys
import time
from contextlib import contextmanager
from pathlib import Path

import psutil


def read_handshake(path, owned_root, deadline, process=None):
    """Read one owned handshake within its original deadline, preserving errors."""
    first_error = last_error = None
    while True:
        if first_error is not None:
            if time.monotonic() >= deadline or (process is not None and process.poll() is not None):
                first_error.add_note("Owned handshake deadline or process exit reached before another read; final read: " + repr(last_error))
                raise first_error
        assert path.is_absolute() and path.resolve() == path and path.is_relative_to(owned_root)
        for ancestor in (path, *path.parents):
            assert not ancestor.is_symlink()
            assert not (hasattr(ancestor, "is_junction") and ancestor.is_junction())
            if ancestor == owned_root:
                break
        try:
            return path.read_text(encoding="utf-8")
        except (FileNotFoundError, PermissionError) as error:
            if isinstance(error, PermissionError) and (sys.platform != "win32" or error.errno != 13):
                raise
            if first_error is None:
                first_error = error
            last_error = error
            remaining = deadline - time.monotonic()
            if remaining <= 0 or (process is not None and process.poll() is not None):
                first_error.add_note("Owned handshake did not become readable; final read: " + repr(error))
                raise first_error
            time.sleep(min(0.025, remaining))

def cold(home, nonce, allowed, owned_root):
    script = Path(__file__).resolve().parents[1] / "fakes/mcp_oauth_cold_child.py"
    owned_root = owned_root.resolve()
    assert home.resolve().is_relative_to(owned_root)
    receipt_path = home / "m03-cold-receipt.json"
    launcher = actual_identity = None
    actual_verified = False
    original_error = None
    cleanup_errors = []
    process = subprocess.Popen([sys.executable, str(script), str(home), nonce,
                                "allowed" if allowed else "denied", str(receipt_path), str(owned_root)],
                               stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, encoding="utf-8",
                               creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0)
    try:
        parent = psutil.Process(process.pid)
        launcher = identity(parent)
        assert Path(launcher["argv"][1]).resolve() == script.resolve()
        assert str(owned_root) in launcher["argv"]
        assert str(home) in launcher["argv"] and str(receipt_path) in launcher["argv"]
        birth = receipt_path.with_suffix(".birth.json")
        deadline = time.monotonic() + 6
        actual_identity = json.loads(read_handshake(birth, owned_root, deadline, process))

        actual = same_process(actual_identity)
        assert actual is not None
        assert actual.pid == parent.pid or actual.pid in {child.pid for child in parent.children(recursive=True)}
        assert Path(actual_identity["argv"][1]).resolve() == script.resolve()
        assert str(owned_root) in actual_identity["argv"]
        assert str(home) in actual_identity["argv"] and str(receipt_path) in actual_identity["argv"]
        actual_verified = True
        temporary = receipt_path.with_suffix(".observed.tmp")
        temporary.write_text("observed", encoding="utf-8")
        temporary.replace(receipt_path.with_suffix(".observed"))
        stdout, stderr = process.communicate(timeout=45)
        receipt_path.with_suffix(".stdout.log").write_text(stdout, encoding="utf-8")
        receipt_path.with_suffix(".stderr.log").write_text(stderr, encoding="utf-8")
        assert process.returncode == 0, (stdout, stderr)
        result = json.loads(receipt_path.read_text(encoding="utf-8"))
        assert {key: result[key] for key in ("pid", "created", "exe", "argv")} == actual_identity
        assert result["allowed"] is allowed
        assert Path(result["home"]).resolve() == home.resolve()
    except BaseException as error:
        original_error = error
    finally:
        def attempt(label, action):
            try:
                action()
            except BaseException as error:
                cleanup_errors.append(label + ": " + repr(error))

        def terminate_actual():
            actual = same_process(actual_identity)
            if actual is not None:
                actual.terminate()

        if actual_verified:
            attempt("terminate_owned_actual", terminate_actual)
        attempt("launcher_wait", lambda: process.wait(timeout=8 if actual_verified else 12))
        for label, pipe in (("stdout", process.stdout), ("stderr", process.stderr)):
            if pipe:
                attempt(label + "_close", pipe.close)
        for label, observed_identity in (("launcher", launcher), ("actual", actual_identity if actual_verified else None)):
            if observed_identity:
                attempt(label + "_exit_audit", lambda row=observed_identity: exited(row))
        cleanup = {"original_error": repr(original_error), "errors": cleanup_errors,
                   "launcher": launcher, "actual": actual_identity, "actual_verified": actual_verified}
        attempt("cleanup_receipt", lambda: receipt_path.with_suffix(".cleanup.json").write_text(json.dumps(cleanup), encoding="utf-8"))
    if original_error is not None:
        original_error.add_note("Owned cleanup: " + repr(cleanup_errors))
        raise original_error
    assert cleanup_errors == [], cleanup_errors
    return result


def identity(process):
    return {"pid": process.pid, "created": process.create_time(), "exe": process.exe(), "argv": process.cmdline()}


def same_process(row):
    try:
        process = psutil.Process(row["pid"])
        if process.create_time() != row["created"]:
            return None
        assert process.exe() == row["exe"] and process.cmdline() == row["argv"]
        return process
    except psutil.NoSuchProcess:
        return None


def exited(row):
    assert same_process(row) is None, row


@contextmanager
def preserve_body_cause(manager, label, secondary):
    """Keep an actual behavioral exception when owned fixture cleanup also fails."""
    value = manager.__enter__()
    cause = None
    try:
        yield value
    except BaseException:
        cause = sys.exc_info()
    finally:
        try:
            manager.__exit__(*(cause or (None, None, None)))
        except BaseException as error:
            if cause is None:
                raise
            secondary.append({"operation": label, "type": type(error).__name__, "message": str(error)})
        if cause is not None:
            raise cause[1].with_traceback(cause[2])
