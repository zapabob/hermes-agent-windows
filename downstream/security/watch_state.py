from __future__ import annotations

import hashlib
import json
import math
import os
import re
import secrets
import stat
import sys
import tempfile
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator

import psutil

from .bounded_walk import ReparsePathError, absolute_path_without_reparse


_STATE_VERSION = 1
_WATCHER_MODULE = "downstream.security.watcher"
_NONCE_RE = re.compile(r"^[0-9a-f]{32}$")
MAX_WATCH_STATE_BYTES = 64 * 1024


def _canonical_path(path: Path | str) -> str:
    return os.path.normcase(str(Path(path).resolve()))


def _new_nonce() -> str:
    return secrets.token_hex(16)


def _default_state(enabled: bool = False, request_nonce: str | None = None) -> dict[str, Any]:
    return {
        "version": _STATE_VERSION,
        "enabled": enabled,
        "request_nonce": request_nonce,
        "pid": None,
        "process_create_time": None,
        "owner_nonce": None,
        "profile_home": None,
        "python_executable": None,
    }


def _state_path(root: Path) -> Path:
    return root / "watch-state.json"


def _read_persisted(root: Path) -> tuple[dict[str, Any], str | None]:
    try:
        root = absolute_path_without_reparse(root)
        path = root / "watch-state.json"
        before = path.stat(follow_symlinks=False)
    except FileNotFoundError:
        return _default_state(), None
    except (OSError, ReparsePathError):
        return _default_state(), "invalid state file"
    reparse_flag = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0)
    if (
        stat.S_ISLNK(before.st_mode)
        or (reparse_flag and getattr(before, "st_file_attributes", 0) & reparse_flag)
        or not stat.S_ISREG(before.st_mode)
        or before.st_size < 0
        or before.st_size > MAX_WATCH_STATE_BYTES
    ):
        return _default_state(), "invalid state file"
    try:
        with path.open("rb") as handle:
            opened = os.fstat(handle.fileno())
            before_identity = (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns)
            opened_identity = (opened.st_dev, opened.st_ino, opened.st_size, opened.st_mtime_ns)
            if (
                not stat.S_ISREG(opened.st_mode)
                or opened_identity != before_identity
                or opened.st_size > MAX_WATCH_STATE_BYTES
            ):
                return _default_state(), "invalid state file"
            raw = handle.read(MAX_WATCH_STATE_BYTES + 1)
            after_handle = os.fstat(handle.fileno())
        after_path = path.stat(follow_symlinks=False)
        after_identity = (after_path.st_dev, after_path.st_ino, after_path.st_size, after_path.st_mtime_ns)
        if (
            len(raw) != before.st_size
            or len(raw) > MAX_WATCH_STATE_BYTES
            or (after_handle.st_dev, after_handle.st_ino, after_handle.st_size, after_handle.st_mtime_ns)
            != before_identity
            or after_identity != before_identity
        ):
            return _default_state(), "invalid state file"
        value = json.loads(raw.decode("utf-8"))
    except (OSError, UnicodeError, ValueError):
        return _default_state(), "invalid state file"
    if not isinstance(value, dict) or not isinstance(value.get("enabled"), bool):
        return _default_state(), "invalid state file"
    version = value.get("version")
    if version is not None and (type(version) is not int or version != _STATE_VERSION):
        return _default_state(), "invalid state file"
    pid = value.get("pid")
    if pid is not None and (type(pid) is not int or pid <= 0):
        return _default_state(), "invalid state file"
    return dict(value), None


def _atomic_write(root: Path, state: dict[str, Any]) -> None:
    root.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=".watch-state-",
        suffix=".tmp",
        dir=root,
    )
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as handle:
            json.dump(state, handle, ensure_ascii=False, sort_keys=True, allow_nan=False)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, _state_path(root))
        if os.name != "nt":
            directory_descriptor = os.open(root, os.O_RDONLY)
            try:
                os.fsync(directory_descriptor)
            finally:
                os.close(directory_descriptor)
    finally:
        temporary.unlink(missing_ok=True)


@contextmanager
def _file_lock(root: Path, name: str, *, blocking: bool) -> Iterator[bool]:
    root.mkdir(parents=True, exist_ok=True)
    path = root / name
    handle = path.open("a+b")
    acquired = False
    try:
        if path.stat().st_size == 0:
            handle.write(b"\0")
            handle.flush()
            os.fsync(handle.fileno())
        deadline = time.monotonic() + 5.0
        while True:
            try:
                handle.seek(0)
                if os.name == "nt":
                    import msvcrt

                    msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
                else:
                    import fcntl

                    fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                acquired = True
                break
            except (ImportError, OSError):
                if not blocking or time.monotonic() >= deadline:
                    break
                time.sleep(0.02)
        yield acquired
    finally:
        if acquired:
            try:
                handle.seek(0)
                if os.name == "nt":
                    import msvcrt

                    msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
                else:
                    import fcntl

                    fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
            except (ImportError, OSError):
                pass
        handle.close()


@contextmanager
def runtime_lock(root: Path) -> Iterator[bool]:
    """Hold the singleton watcher lock for the process lifetime."""
    with _file_lock(root, "watch-runtime.lock", blocking=False) as acquired:
        yield acquired


@contextmanager
def control_lock(root: Path) -> Iterator[None]:
    """Serialize enable, disable, migration, and boot recovery."""
    profile_home = root.parent.resolve()
    if profile_home.parent.name == "profiles":
        lock_root = profile_home.parent / ".security-watch-locks"
    else:
        lock_root = profile_home / ".security-watch-locks"
    identity = hashlib.sha256(_canonical_path(profile_home).encode("utf-8")).hexdigest()
    with _file_lock(lock_root, f"{identity}.lock", blocking=True) as acquired:
        if not acquired:
            raise TimeoutError("timed out waiting for watcher control lock")
        yield


@contextmanager
def _state_lock(root: Path) -> Iterator[None]:
    with _file_lock(root, "watch-state.lock", blocking=True) as acquired:
        if not acquired:
            raise TimeoutError("timed out waiting for watcher state lock")
        yield


def begin_watch_enable(root: Path) -> str:
    """Persist a new enable generation and return its request nonce."""
    request_nonce = _new_nonce()
    state = _default_state(enabled=True, request_nonce=request_nonce)
    state["profile_home"] = str(root.parent.resolve())
    with _state_lock(root):
        _atomic_write(root, state)
    return request_nonce


def preserve_watch_enable_intent(root: Path) -> str:
    """Invalidate a failed child while retaining durable enable intent."""
    return begin_watch_enable(root)


def _current_process_record(
    root: Path,
    request_nonce: str,
    owner_nonce: str,
) -> dict[str, Any]:
    process = psutil.Process(os.getpid())
    return {
        "version": _STATE_VERSION,
        "enabled": True,
        "request_nonce": request_nonce,
        "pid": process.pid,
        "process_create_time": process.create_time(),
        "owner_nonce": owner_nonce,
        "profile_home": str(root.parent.resolve()),
        "python_executable": str(Path(process.exe() or sys.executable).resolve()),
    }


def claim_watch_owner(
    root: Path,
    request_nonce: str,
    owner_nonce: str,
) -> dict[str, Any] | None:
    if not _NONCE_RE.fullmatch(request_nonce) or not _NONCE_RE.fullmatch(owner_nonce):
        raise ValueError("watcher nonces must be 32 lowercase hexadecimal characters")
    record = _current_process_record(root, request_nonce, owner_nonce)
    with _state_lock(root):
        current, error = _read_persisted(root)
        if (
            error is not None
            or current.get("enabled") is not True
            or current.get("request_nonce") != request_nonce
        ):
            return None
        _atomic_write(root, record)
    return record


def clear_watch_owner(root: Path, request_nonce: str, owner_nonce: str) -> bool:
    with _state_lock(root):
        current, error = _read_persisted(root)
        if (
            error is not None
            or current.get("request_nonce") != request_nonce
            or current.get("owner_nonce") != owner_nonce
        ):
            return False
        cleared = _default_state(
            enabled=bool(current.get("enabled")),
            request_nonce=request_nonce if current.get("enabled") else None,
        )
        cleared["profile_home"] = str(root.parent.resolve())
        _atomic_write(root, cleared)
    return True


def set_watch_enabled(root: Path, enabled: bool) -> dict[str, Any]:
    """Compatibility helper used by tests and state repair paths."""
    request_nonce = _new_nonce() if enabled else None
    state = _default_state(enabled=enabled, request_nonce=request_nonce)
    state["profile_home"] = str(root.parent.resolve())
    with _state_lock(root):
        _atomic_write(root, state)
    return state


def prepare_watch_disable(root: Path) -> tuple[dict[str, Any], psutil.Process | None]:
    """Persist disable intent and return only a fully verified owner process."""
    with _state_lock(root):
        current, error = _read_persisted(root)
        if error is not None:
            cleared = _default_state()
            cleared["profile_home"] = str(root.parent.resolve())
            _atomic_write(root, cleared)
            return cleared, None
        process, _identity_error = _process_for_state(root, current)
        if process is None:
            cleared = _default_state()
            cleared["profile_home"] = str(root.parent.resolve())
            _atomic_write(root, cleared)
            return cleared, None
        # Keep this owner's generation while it is stopping so status can
        # still authenticate and report the live process. A later enable
        # mints a fresh generation, so a delayed clear from this owner cannot
        # erase the replacement.
        current["enabled"] = False
        _atomic_write(root, current)
        return current, process


def _command_matches(command: list[str], request_nonce: str, owner_nonce: str) -> bool:
    if len(command) != 9 or command[1:3] != ["-m", _WATCHER_MODULE]:
        return False
    if command[3] != "--interval" or command[5] != "--request-nonce" or command[7] != "--owner-nonce":
        return False
    try:
        interval = float(command[4])
    except (TypeError, ValueError):
        return False
    return (
        math.isfinite(interval)
        and interval >= 2.0
        and command[6] == request_nonce
        and command[8] == owner_nonce
    )


def _legacy_command_matches(command: list[str]) -> bool:
    if len(command) != 5 or command[1:4] != ["-m", _WATCHER_MODULE, "--interval"]:
        return False
    try:
        interval = float(command[4])
    except (TypeError, ValueError):
        return False
    return math.isfinite(interval) and interval >= 2.0


def _process_for_state(root: Path, state: dict[str, Any]) -> tuple[psutil.Process | None, str | None]:
    pid = state.get("pid")
    if pid is None:
        return None, None
    create_time = state.get("process_create_time")
    required = (
        create_time,
        state.get("request_nonce"),
        state.get("owner_nonce"),
        state.get("profile_home"),
        state.get("python_executable"),
    )
    if (
        not isinstance(create_time, (int, float))
        or not math.isfinite(float(create_time))
        or not isinstance(required[1], str)
        or not _NONCE_RE.fullmatch(required[1])
        or not isinstance(required[2], str)
        or not _NONCE_RE.fullmatch(required[2])
        or not isinstance(required[3], str)
        or not isinstance(required[4], str)
    ):
        return None, "watcher identity is incomplete"
    if _canonical_path(required[3]) != _canonical_path(root.parent):
        return None, "watcher profile does not match state path"
    try:
        process = psutil.Process(pid)
        if not process.is_running() or process.status() == psutil.STATUS_ZOMBIE:
            return None, "watcher process is not running"
        if abs(process.create_time() - float(create_time)) > 0.01:
            return None, "watcher process identity changed"
        if not _command_matches(process.cmdline(), required[1], required[2]):
            return None, "watcher command does not match"
        if _canonical_path(process.exe()) != _canonical_path(required[4]):
            return None, "watcher executable does not match"
        return process, None
    except (OSError, TypeError, ValueError, psutil.Error):
        return None, "watcher process is not running"


def prepare_legacy_watch_transition(root: Path) -> tuple[psutil.Process | None, str | None]:
    """Fence an identifiable pre-generation watcher before upgrade.

    The caller holds ``control_lock`` and must wait for the returned process
    before writing the requested new state. An unidentifiable legacy PID is
    never signalled and blocks a potentially concurrent replacement.
    """
    with _state_lock(root):
        state, error = _read_persisted(root)
        if error is not None:
            return None, error
        if state.get("version") is not None:
            return None, None
        pid = state.get("pid")
        if state.get("enabled") is not True or pid is None:
            cleared = _default_state()
            cleared["profile_home"] = str(root.parent.resolve())
            _atomic_write(root, cleared)
            return None, None
        try:
            process = psutil.Process(pid)
            if (
                not process.is_running()
                or process.status() == psutil.STATUS_ZOMBIE
                or not _legacy_command_matches(process.cmdline())
                or _canonical_path(process.exe()) != _canonical_path(sys.executable)
            ):
                return None, "legacy watcher identity could not be verified"
            # Invalidate the legacy state before signalling. The old watcher
            # may write its legacy disabled record while exiting; the caller
            # waits for that write before persisting the new generation.
            fenced = _default_state()
            fenced["profile_home"] = str(root.parent.resolve())
            _atomic_write(root, fenced)
            return process, None
        except (OSError, TypeError, ValueError, psutil.Error):
            return None, "legacy watcher identity could not be verified"


def verified_watch_process(root: Path, state: dict[str, Any] | None = None) -> psutil.Process | None:
    candidate = state
    if candidate is None:
        candidate, error = _read_persisted(root)
        if error is not None:
            return None
    process, _error = _process_for_state(root, candidate)
    return process


def verified_watch_owner(
    root: Path,
    request_nonce: str,
    owner_nonce: str,
) -> psutil.Process | None:
    """Return the live owner only when both generation nonces match."""
    state, error = _read_persisted(root)
    if (
        error is not None
        or state.get("request_nonce") != request_nonce
        or state.get("owner_nonce") != owner_nonce
    ):
        return None
    process, _identity_error = _process_for_state(root, state)
    return process


def read_watch_status(root: Path) -> dict[str, Any]:
    state, error = _read_persisted(root)
    if error is not None:
        return {"enabled": False, "pid": None, "running": False, "error": error}
    process, identity_error = _process_for_state(root, state)
    result: dict[str, Any] = {
        "enabled": bool(state.get("enabled")),
        "pid": state.get("pid"),
        "running": process is not None,
    }
    if identity_error is not None:
        result["error"] = identity_error
    return result
