from __future__ import annotations

import json
import logging
import math
import secrets
import subprocess
import sys
import threading
import time
from argparse import Namespace
from pathlib import Path
from typing import Any, Protocol

import psutil

logger = logging.getLogger(__name__)

from hermes_cli._subprocess_compat import (
    windows_detach_flags,
    windows_detach_flags_without_breakaway,
    windows_hide_flags,
)
from tools.environments.local import hermes_subprocess_env

from .service import SecurityService
from .watch_state import (
    begin_watch_enable,
    control_lock,
    prepare_legacy_watch_transition,
    prepare_watch_disable,
    preserve_watch_enable_intent,
    read_watch_status,
    set_watch_enabled,
    verified_watch_owner,
)


class _WatchStore(Protocol):
    root: Path

    def event(
        self,
        event_type: str,
        subject: str,
        verdict: str | None,
        action: str,
        details: dict[str, Any],
    ) -> None: ...


class _WatchService(Protocol):
    config: dict[str, Any]
    store: _WatchStore

    def watch_status(self) -> dict[str, object]: ...


def _emit(value: Any, machine: bool) -> None:
    if machine:
        sys.stdout.write(json.dumps(value, ensure_ascii=False, indent=2, default=str) + "\n")
        return
    if isinstance(value, list):
        for item in value:
            sys.stdout.write(json.dumps(item, ensure_ascii=False, default=str) + "\n")
        return
    if isinstance(value, dict):
        for key, item in value.items():
            sys.stdout.write(f"{key}: {json.dumps(item, ensure_ascii=False, default=str)}\n")
        return
    sys.stdout.write(f"{value}\n")


def _stop_legacy_watcher(root: Path) -> str | None:
    process, error = prepare_legacy_watch_transition(root)
    if error is not None:
        return error
    if process is None:
        return None
    try:
        process.terminate()
        process.wait(timeout=10)
    except psutil.NoSuchProcess:
        return None
    except (OSError, psutil.Error):
        return "legacy watcher did not stop within 10 seconds"
    return None


def _spawn_watcher(argv: list[str], root: Path) -> subprocess.Popen[bytes]:
    child_env = hermes_subprocess_env(
        inherit_credentials=False,
        extra={"HERMES_HOME": str(root.parent.resolve())},
    )
    flags = windows_detach_flags() | windows_hide_flags()
    try:
        return subprocess.Popen(
            argv,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            env=child_env,
            creationflags=flags,
            start_new_session=sys.platform != "win32",
        )
    except OSError:
        if sys.platform != "win32":
            raise
        fallback = windows_detach_flags_without_breakaway() | windows_hide_flags()
        return subprocess.Popen(
            argv,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            env=child_env,
            creationflags=fallback,
            start_new_session=False,
        )


def _watch_enable_locked(service: _WatchService) -> dict[str, Any]:
    root = service.store.root
    legacy_error = _stop_legacy_watcher(root)
    if legacy_error is not None:
        return {
            "ok": False,
            "enabled": True,
            "pid": None,
            "running": False,
            "error": legacy_error,
        }
    current = service.watch_status()
    if current.get("running"):
        if current.get("enabled"):
            return {"ok": True, **current}
        return {
            "ok": False,
            **current,
            "error": "previous watcher is still stopping",
        }
    request_nonce = begin_watch_enable(root)
    owner_nonce = secrets.token_hex(16)
    interval = float(service.config.get("watch_interval", 30))
    if not math.isfinite(interval):
        raise ValueError("watch interval must be finite")
    interval = max(2.0, interval)
    argv = [
        sys.executable,
        "-m",
        "downstream.security.watcher",
        "--interval",
        str(interval),
        "--request-nonce",
        request_nonce,
        "--owner-nonce",
        owner_nonce,
    ]
    try:
        process = _spawn_watcher(argv, root)
    except OSError as exc:
        set_watch_enabled(root, False)
        return {"ok": False, "enabled": False, "pid": None, "running": False, "error": str(exc)}
    deadline = time.monotonic() + 5.0
    while time.monotonic() < deadline:
        owner_process = verified_watch_owner(root, request_nonce, owner_nonce)
        if owner_process is not None:
            state = service.watch_status()
            service.store.event("watch", str(state.get("pid")), None, "enabled", {})
            return {"ok": True, **state}
        time.sleep(0.05)

    # Invalidate this generation before signalling the specifically spawned
    # Popen. On POSIX an unreaped child cannot have its PID reused; on Windows
    # Popen retains the process handle, so this cleanup never targets a
    # process discovered from an untrusted persisted PID.
    owner_process = verified_watch_owner(root, request_nonce, owner_nonce)
    set_watch_enabled(root, False)
    stopped = True
    if owner_process is not None:
        try:
            owner_process.terminate()
            owner_process.wait(timeout=3)
        except psutil.NoSuchProcess:
            pass
        except (OSError, psutil.Error):
            try:
                owner_process.kill()
                owner_process.wait(timeout=3)
            except (OSError, psutil.Error):
                stopped = False
    if owner_process is None or owner_process.pid != process.pid:
        try:
            if process.poll() is None:
                process.terminate()
            process.wait(timeout=3)
        except (OSError, subprocess.TimeoutExpired):
            try:
                process.kill()
                process.wait(timeout=3)
            except (OSError, subprocess.TimeoutExpired):
                stopped = False
    if stopped:
        preserve_watch_enable_intent(root)
    return {
        "ok": False,
        "enabled": stopped,
        "pid": process.pid,
        "running": not stopped,
        "error": (
            "watcher did not report ready within 5 seconds; enable intent was preserved"
            if stopped
            else "watcher did not report ready and cleanup failed"
        ),
    }


def _watch_enable(service: _WatchService) -> dict[str, Any]:
    root = service.store.root
    with control_lock(root):
        return _watch_enable_locked(service)


def disable_watch_for_profile(profile_home: Path) -> dict[str, Any]:
    """Stop a profile watcher without constructing the Security service."""
    root = profile_home.resolve() / "security"
    if not root.exists():
        return {"ok": True, "enabled": False, "pid": None, "running": False}
    with control_lock(root):
        legacy_error = _stop_legacy_watcher(root)
        if legacy_error is not None:
            return {
                "ok": False,
                "enabled": False,
                "pid": None,
                "running": True,
                "error": legacy_error,
            }
        state, process = prepare_watch_disable(root)
        raw_pid = state.get("pid")
        pid = raw_pid if type(raw_pid) is int else 0
        if process is not None:
            try:
                # psutil re-checks its cached create time immediately before
                # terminate/kill, closing the PID-reuse interval after our
                # persisted identity validation.
                process.terminate()
                process.wait(timeout=10)
            except psutil.NoSuchProcess:
                pass
            except (OSError, psutil.Error):
                return {
                    "ok": False,
                    "enabled": False,
                    "pid": pid,
                    "running": True,
                    "error": "watcher did not stop within 10 seconds",
                }
        set_watch_enabled(root, False)
        return {"ok": True, "enabled": False, "pid": None, "running": False}


def _watch_disable(service: _WatchService) -> dict[str, Any]:
    current = service.watch_status()
    raw_pid = current.get("pid")
    pid = raw_pid if type(raw_pid) is int else 0
    result = disable_watch_for_profile(service.store.root.parent)
    if result.get("ok"):
        service.store.event("watch", str(pid or "none"), None, "disabled", {})
    return result


def resume_watch_if_enabled(profile_home: Path | None = None) -> dict[str, Any]:
    """One-shot boot recovery for a persisted watcher request."""
    from hermes_constants import (
        get_hermes_home,
        reset_hermes_home_override,
        set_hermes_home_override,
    )

    home = (profile_home or get_hermes_home()).resolve()
    root = home / "security"
    current = read_watch_status(root)
    if current.get("error") and not current.get("enabled"):
        return {"ok": False, **current}
    if not current.get("enabled") or current.get("running"):
        return {"ok": True, **current}
    with control_lock(root):
        if not home.is_dir():
            return {"ok": True, "enabled": False, "pid": None, "running": False}
        current = read_watch_status(root)
        if not current.get("enabled") or current.get("running"):
            return {"ok": True, **current}
        token = set_hermes_home_override(home)
        try:
            return _watch_enable_locked(SecurityService())
        finally:
            reset_hermes_home_override(token)


def resume_all_profile_watches() -> list[dict[str, Any]]:
    """Resume durable watch requests for the default and named profiles."""
    from hermes_cli.profiles import get_profile_dir, list_profile_names

    results: list[dict[str, Any]] = []
    for name in list_profile_names():
        home = get_profile_dir(name)
        if (home / "security" / "watch-state.json").is_file():
            result = resume_watch_if_enabled(home)
            results.append({"profile": name, **result})
    return results


def _kick_daily_auto_update_if_due(service: SecurityService) -> None:
    """CLI利用時の一日一回自動更新を裏スレッドで蹴る(起動時チェック相当)。

    status/scan等の参照系コマンドから呼ばれ、最終ok更新から24h(既定)
    経過時のみClamAV+YARAを更新する。freshclamは最大300s掛かるため
    必ずdaemonスレッドで実行し、本体コマンドを絶対に遅延・失敗させない。
    """
    try:
        from .updates import is_auto_update_due
        from hermes_cli.config import load_config

        try:
            config = load_config()
            malware = (config.get("security") or {}).get("malware") or {}
        except Exception:
            return
        if not malware.get("auto_update_enabled", True):
            return
        try:
            interval = float(malware.get("auto_update_interval_hours", 24))
        except (TypeError, ValueError):
            interval = 24.0
        try:
            if not is_auto_update_due(service.store, interval):
                return
        except Exception:
            return

        def _run() -> None:
            try:
                from .updates import maybe_auto_update

                maybe_auto_update(service.store, config)
            except Exception:
                logger.debug("security auto-update background run failed", exc_info=True)

        threading.Thread(target=_run, daemon=True, name="security-auto-update").start()
    except Exception:
        logger.debug("security auto-update kick failed", exc_info=True)


def command(args: Namespace) -> int:
    service = SecurityService()
    subcommand = args.security_command
    machine = bool(getattr(args, "json", False))
    if subcommand in ("status", "scan", "feeds"):
        _kick_daily_auto_update_if_due(service)
    try:
        if subcommand == "status":
            result = service.status()
        elif subcommand == "scan":
            paths = service.quick_paths() if args.quick else service.full_paths() if args.full else [Path(args.path)]
            result = [item.to_dict() for item in service.scan_paths(paths, quarantine=not args.no_quarantine)]
        elif subcommand == "update":
            result = service.update()
        elif subcommand == "feeds":
            result = service.store.status_rows("feed_state", 200)
        elif subcommand == "watch":
            result = service.watch_status() if args.watch_command == "status" else _watch_enable(service) if args.watch_command == "enable" else _watch_disable(service)
        elif subcommand == "quarantine":
            if args.quarantine_command == "list":
                result = service.store.status_rows("quarantine_items", 200)
            elif args.quarantine_command == "inspect":
                result = service.vault.inspect(args.item_id)
            elif args.quarantine_command == "restore":
                target = Path(args.destination).resolve() if args.destination else None
                restored = service.vault.restore(args.item_id, lambda path: service.scan_file(path, quarantine=False, use_cache=False), target, args.force)
                result = {"ok": True, "path": str(restored)}
            else:
                service.vault.delete(args.item_id)
                result = {"ok": True, "id": args.item_id, "deleted": True}
        else:
            raise ValueError(f"unknown security subcommand: {subcommand}")
    except (FileNotFoundError, KeyError, PermissionError, RuntimeError, TimeoutError, ValueError) as exc:
        _emit({"ok": False, "error": str(exc)}, machine)
        return 2
    _emit(result, machine)
    if isinstance(result, dict) and result.get("ok") is False:
        return 1
    return 0
