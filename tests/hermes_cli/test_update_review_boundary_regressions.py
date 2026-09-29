"""PR #160 process-ownership regressions without stopping real processes."""

from __future__ import annotations

import ctypes
from types import SimpleNamespace

import pytest

import gateway.status as gateway_status
import hermes_cli.gateway as gateway_cli
import hermes_cli.update_cmd as update_cmd


def test_refused_guarded_sweep_remains_an_incomplete_stop() -> None:
    def refuse(_pid: int, **_kwargs: object) -> None:
        raise OSError("process incarnation changed")

    def unexpected_signal(*_args: object) -> None:
        pytest.fail("Windows candidates must never reach PID-only signals")

    stopped, unverified = update_cmd._sweep_manual_gateway_pids(
        manual_pids=[81001],
        profile_processes={},
        unrestartable_pids=set(),
        windows=True,
        stop_guards={81001: 1100},
        kill=unexpected_signal,
        terminate=refuse,
    )

    assert stopped == set()
    assert unverified == [81001]


@pytest.mark.parametrize("current_guard", [1100, 50000], ids=["original", "reused"])
def test_windows_manual_stop_preserves_discovery_guard_even_when_wedged(
    monkeypatch: pytest.MonkeyPatch, current_guard: int
) -> None:
    stopped: list[int] = []

    def guarded_stop(pid: int, *, force: bool, expected_start_time: int) -> None:
        assert force is True
        assert expected_start_time == 1100
        if current_guard != expected_start_time:
            raise OSError("process incarnation changed")
        stopped.append(pid)

    def unexpected_pid_only_call(*_args: object, **_kwargs: object) -> None:
        pytest.fail("The Windows update must use its discovery-time identity")

    monkeypatch.setattr(update_cmd, "_terminate_guarded_pid", guarded_stop)
    monkeypatch.setattr(
        gateway_cli,
        "probe_gateway_loop_liveness",
        lambda _pid: gateway_cli.GATEWAY_LOOP_WEDGED,
    )
    monkeypatch.setattr(
        gateway_cli, "_escalate_wedged_gateway", unexpected_pid_only_call
    )
    monkeypatch.setattr(
        gateway_cli, "_graceful_restart_via_sigusr1", unexpected_pid_only_call
    )
    monkeypatch.setattr(update_cmd.os, "kill", unexpected_pid_only_call)

    accepted = update_cmd._stop_manual_gateway_for_update(
        81001, windows=True, stop_guards={81001: 1100}, drain_timeout=180.0
    )

    assert accepted is (current_guard == 1100)
    assert stopped == ([81001] if current_guard == 1100 else [])


@pytest.mark.parametrize("wedged", [False, True])
def test_posix_manual_stop_preserves_drain_and_wedged_routes(
    monkeypatch: pytest.MonkeyPatch, wedged: bool
) -> None:
    actions: list[tuple[str, float]] = []
    monkeypatch.setattr(
        gateway_cli,
        "probe_gateway_loop_liveness",
        lambda _pid: (
            gateway_cli.GATEWAY_LOOP_WEDGED
            if wedged
            else gateway_cli.GATEWAY_LOOP_ALIVE
        ),
    )
    monkeypatch.setattr(
        gateway_cli,
        "_escalate_wedged_gateway",
        lambda _pid: actions.append(("escalate", 0.0)) or True,
    )
    monkeypatch.setattr(
        gateway_cli,
        "_graceful_restart_via_sigusr1",
        lambda _pid, drain_timeout: actions.append(("drain", drain_timeout)) or True,
    )

    assert (
        update_cmd._stop_manual_gateway_for_update(
            81001, windows=False, stop_guards={}, drain_timeout=180.0
        )
        is True
    )
    assert actions == ([("escalate", 0.0)] if wedged else [("drain", 180.0)])


@pytest.mark.windows_only
def test_native_liveness_preserves_the_entire_handle(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Exercise actual ctypes argument conversion using harmless native callbacks."""
    from ctypes import wintypes

    handle = (1 << (ctypes.sizeof(ctypes.c_void_p) * 8 - 8)) | 0x1234
    waited: list[int] = []
    closed: list[int] = []
    callbacks = [
        ctypes.CFUNCTYPE(
            wintypes.HANDLE, wintypes.DWORD, wintypes.BOOL, wintypes.DWORD
        )(lambda _access, _inherit, _pid: handle),
        ctypes.CFUNCTYPE(wintypes.DWORD, wintypes.HANDLE, wintypes.DWORD)(
            lambda received, _timeout: waited.append(received) or 0x102
        ),
        ctypes.CFUNCTYPE(wintypes.BOOL, wintypes.HANDLE)(
            lambda received: closed.append(received) or 1
        ),
        ctypes.CFUNCTYPE(wintypes.DWORD)(lambda: 0),
    ]
    # DLL entry points have no declared argument types until the loader sets
    # them. Calling these callbacks through that same boundary catches the
    # pointer-to-C-int truncation that ordinary Python mocks cannot detect.
    entries = [
        ctypes.CFUNCTYPE(ctypes.c_int)(ctypes.cast(callback, ctypes.c_void_p).value)
        for callback in callbacks
    ]
    for entry in entries:
        entry.argtypes = None
    kernel32 = SimpleNamespace(
        OpenProcess=entries[0],
        WaitForSingleObject=entries[1],
        CloseHandle=entries[2],
        GetLastError=entries[3],
    )
    monkeypatch.setattr(ctypes.windll, "kernel32", kernel32)

    assert (
        gateway_status._windows_pid_liveness_strict(
            81001, gateway_status._load_windows_kernel32()
        )
        is True
    )
    assert waited == [handle]
    assert closed == [handle]
