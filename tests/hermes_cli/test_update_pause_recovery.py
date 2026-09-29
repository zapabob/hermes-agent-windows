"""Exercise pause failure recovery without launching or stopping real processes."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

import hermes_cli.gateway as _gateway_mod
import hermes_cli.update_cmd as _update_cmd
from hermes_cli import main as cli_main

_REAL_LAUNCHER_IDENTITIES = _update_cmd._venv_launcher_ancestor_identities
_REAL_PROFILE_RESTART = _gateway_mod.launch_detached_profile_gateway_restart


@pytest.fixture
def pause_fleet(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> SimpleNamespace:
    import gateway.control_socket as socket_mod
    import gateway.status as status_mod
    import hermes_cli.gateway as gateway_mod
    import hermes_cli.update_cmd as update_cmd
    import psutil

    work = SimpleNamespace(
        profile="work",
        path=tmp_path / "work",
        pid=101,
        create_time=99.0,
    )
    work.path.mkdir()
    fleet = SimpleNamespace(
        profiles=[work],
        services=[],
        running=[101, 303, 404],
        paused=set(),
        stopped=[],
        restarted=[],
        replayed=[],
        service_stops=[],
        service_restores=[],
        fail_drain=False,
        fail_stop=None,
        fail_restart=False,
    )
    starts = {101: 99.0, 202: 202.0, 303: 303.0, 404: 404.0, 11: 11.0, 22: 22.0}
    argv = ["pythonw.exe", "-m", "hermes_cli.main", "gateway", "run"]
    monkeypatch.setattr(cli_main, "_is_windows", lambda: True)
    monkeypatch.setattr(update_cmd, "_ACTIVE_WATCHDOG_MAINTENANCE", None)
    monkeypatch.setattr(gateway_mod, "find_gateway_pids", lambda **_kw: fleet.running)
    monkeypatch.setattr(
        gateway_mod,
        "find_profile_gateway_processes",
        lambda **_kw: fleet.profiles,
    )
    monkeypatch.setattr(
        gateway_mod,
        "find_windows_gateway_services",
        lambda **_kw: fleet.services,
    )
    monkeypatch.setattr(gateway_mod, "_capture_gateway_argv", lambda _pid: argv)
    monkeypatch.setattr(gateway_mod, "_get_restart_drain_timeout", lambda: 1.0)
    monkeypatch.setattr(
        psutil,
        "Process",
        lambda pid: SimpleNamespace(create_time=lambda: starts[pid]),
    )
    monkeypatch.setattr(
        status_mod,
        "get_process_start_time",
        lambda pid: int(round(starts[pid] * 100)),
    )
    monkeypatch.setattr(
        cli_main,
        "_venv_launcher_ancestors",
        lambda pids: [
            parent for worker, parent in ((101, 11), (202, 22)) if worker in pids
        ],
    )
    monkeypatch.setattr(
        update_cmd,
        "_venv_launcher_ancestor_identities",
        lambda workers: [
            (parent, int(round(starts[parent] * 100)))
            for worker, parent in ((101, 11), (202, 22))
            if (worker, int(round(starts[worker] * 100))) in workers
        ],
    )
    monkeypatch.setattr(cli_main, "_refresh_windows_gateway_launchers", lambda: None)

    def pause(path: Path) -> dict:
        fleet.paused.add(path.name)
        return {"pausing": True, "drain_timeout": 1.0}

    def wait(_pids: list[int], *, timeout: float) -> set[int]:
        if fleet.fail_drain:
            raise RuntimeError("synthetic drain failure")
        return set()

    def stop(pid: int, *, force: bool, expected_start_time: int) -> None:
        assert force is True
        assert expected_start_time == int(round(starts[pid] * 100))
        fleet.stopped.append(pid)
        if pid == fleet.fail_stop:
            raise OSError("synthetic stop refusal")

    def restart(profile: str, pid: int, started: float) -> bool:
        fleet.restarted.append((profile, pid, started))
        if fleet.fail_restart:
            return False
        fleet.paused.discard(profile)
        return True

    def replay(pid: int, captured_argv: list[str]) -> bool:
        assert captured_argv == argv
        fleet.replayed.append(pid)
        return True

    monkeypatch.setattr(socket_mod, "pause_gateway_for_update", pause)
    monkeypatch.setattr(cli_main, "_wait_for_windows_update_gateway_exit", wait)
    monkeypatch.setattr(status_mod, "terminate_pid", stop)
    monkeypatch.setattr(gateway_mod, "launch_detached_profile_gateway_restart", restart)
    monkeypatch.setattr(
        gateway_mod, "launch_detached_gateway_restart_by_cmdline", replay
    )
    monkeypatch.setattr(
        update_cmd,
        "_stop_windows_gateway_service",
        lambda name, **_kw: fleet.service_stops.append(name),
    )
    monkeypatch.setattr(
        update_cmd,
        "_restore_windows_gateway_service",
        lambda name: fleet.service_restores.append(name),
    )
    return fleet


@pytest.mark.parametrize("failure", ["drain", "force_stop"])
def test_partial_pause_recovers_before_returning_failure(
    pause_fleet: SimpleNamespace,
    failure: str,
) -> None:
    """A late pause failure must not strand earlier profiles before token return."""
    pause_fleet.fail_drain = failure == "drain"
    pause_fleet.fail_stop = 303 if failure == "force_stop" else None

    with pytest.raises(RuntimeError):
        cli_main._pause_windows_gateways_for_update()

    assert pause_fleet.restarted == [("work", 101, 99.0)]
    assert pause_fleet.paused == set()
    # Only the attempted stop can need argv recovery. PID 404 was never touched.
    assert pause_fleet.replayed == ([303] if failure == "force_stop" else [])
    assert pause_fleet.service_stops == []
    assert pause_fleet.service_restores == []


def test_partial_pause_reports_recovery_failure(pause_fleet: SimpleNamespace) -> None:
    """A refused recovery remains visible alongside the original pause failure."""
    pause_fleet.fail_drain = True
    pause_fleet.fail_restart = True

    with pytest.raises(
        RuntimeError, match="rollback failures: ordinary gateways"
    ) as error:
        cli_main._pause_windows_gateways_for_update()

    assert "synthetic drain failure" in str(error.value)
    assert pause_fleet.restarted == [("work", 101, 99.0)]
    assert pause_fleet.paused == {"work"}
    assert pause_fleet.replayed == []


def test_scm_gateway_launcher_is_not_force_stopped_by_ordinary_pause(
    pause_fleet: SimpleNamespace,
    tmp_path: Path,
) -> None:
    """Only the ordinary gateway's launcher is eligible for the generic kill path."""
    pause_fleet.running.append(202)
    pause_fleet.profiles.append(
        SimpleNamespace(
            profile="service",
            path=tmp_path / "service",
            pid=202,
            create_time=202.0,
        )
    )
    pause_fleet.services.append(
        SimpleNamespace(
            name="HermesGatewayService",
            profile="service",
            service_pid=22,
            service_create_time=22.0,
            gateway_pid=202,
            gateway_create_time=202.0,
            descendant_identities=((202, 202.0),),
        )
    )

    token = cli_main._pause_windows_gateways_for_update()

    assert pause_fleet.stopped == [11, 303, 404]
    assert pause_fleet.paused == {"work"}
    assert pause_fleet.service_stops == ["HermesGatewayService"]
    assert pause_fleet.restarted == []
    assert token["profiles"] == {"work": 101}
    assert token["profile_old_identities"] == {"work": (101, 99.0)}
    assert token["services"] == ["HermesGatewayService"]


def test_scm_descendant_returned_by_gateway_scan_stays_under_scm_owner(
    pause_fleet: SimpleNamespace,
    tmp_path: Path,
) -> None:
    """A service launcher found by the generic scan must never gain ordinary ownership."""
    pause_fleet.running.extend([22, 202])
    pause_fleet.profiles.append(
        SimpleNamespace(
            profile="service",
            path=tmp_path / "service",
            pid=202,
            create_time=202.0,
        )
    )
    pause_fleet.services.append(
        SimpleNamespace(
            name="HermesGatewayService",
            profile="service",
            service_pid=22,
            service_create_time=22.0,
            gateway_pid=202,
            gateway_create_time=202.0,
            descendant_identities=((22, 22.0), (202, 202.0)),
        )
    )

    token = cli_main._pause_windows_gateways_for_update()

    assert 22 not in pause_fleet.stopped
    assert 22 not in pause_fleet.replayed
    assert token["unmapped_pids"] == [303, 404]
    assert [entry["pid"] for entry in token["unmapped"]] == [303, 404]
    assert pause_fleet.service_stops == ["HermesGatewayService"]


def test_launcher_pid_reuse_after_discovery_is_rejected_before_force_stop(
    pause_fleet: SimpleNamespace,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The launcher stop guard must stay bound to the incarnation that was inspected."""
    import gateway.status as status_mod
    import hermes_cli.update_cmd as update_cmd

    observed = {"launcher_identity_reads": 0}

    def launcher_identities(_pids: list[int]) -> list[tuple[int, int]]:
        observed["launcher_identity_reads"] += 1
        return [(11, 1100)]

    monkeypatch.setattr(
        update_cmd,
        "_venv_launcher_ancestor_identities",
        launcher_identities,
        raising=False,
    )
    monkeypatch.setattr(
        cli_main,
        "_venv_launcher_ancestor_identities",
        launcher_identities,
        raising=False,
    )

    original_get_start = status_mod.get_process_start_time

    def reused_start(pid: int):
        if pid == 11:
            return 11100
        return original_get_start(pid)

    monkeypatch.setattr(status_mod, "get_process_start_time", reused_start)

    with pytest.raises(RuntimeError, match="launcher identity"):
        cli_main._pause_windows_gateways_for_update()

    assert observed["launcher_identity_reads"] == 1
    assert 11 not in pause_fleet.stopped


def test_keyboard_interrupt_after_socket_pause_recovers_before_reraising(
    pause_fleet: SimpleNamespace,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Ctrl+C during the pre-return drain window must not strand a paused Gateway."""
    monkeypatch.setattr(
        cli_main,
        "_wait_for_windows_update_gateway_exit",
        lambda *_a, **_kw: (_ for _ in ()).throw(KeyboardInterrupt()),
    )

    with pytest.raises(KeyboardInterrupt):
        cli_main._pause_windows_gateways_for_update()

    assert pause_fleet.restarted == [("work", 101, 99.0)]
    assert pause_fleet.paused == set()


def test_recycled_worker_pid_never_puts_a_foreign_launcher_on_the_stop_set(
    pause_fleet: SimpleNamespace,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A mapped worker PID recycled after preflight must not nominate its new parent."""
    import gateway.status as status_mod
    import psutil

    monkeypatch.setattr(
        _update_cmd, "_venv_launcher_ancestor_identities", _REAL_LAUNCHER_IDENTITIES
    )
    venv_exe = str(cli_main.PROJECT_ROOT / "venv" / "Scripts" / "python.exe")
    worker_reads = {"count": 0}

    class FakeProc:
        def __init__(self, pid=None):
            self.pid = 999 if pid is None else int(pid)

        def parents(self):
            return []

        def cmdline(self):
            return []

        def parent(self):
            # After the recycle, PID 101 is a child of another venv python.
            return FakeProc(82) if self.pid == 101 else None

        def exe(self):
            return venv_exe if self.pid == 82 else ""

        def create_time(self):
            if self.pid == 101:
                worker_reads["count"] += 1
                # The owner-argv capture reads the original twice; the PID is
                # reused before the launcher walk starts.
                return 99.0 if worker_reads["count"] <= 2 else 777.0
            return {82: 500.0}.get(self.pid, float(self.pid))

    monkeypatch.setattr(psutil, "Process", FakeProc)
    starts = {101: 99.0, 82: 500.0, 303: 303.0, 404: 404.0}
    monkeypatch.setattr(
        status_mod,
        "get_process_start_time",
        lambda pid: int(round(starts[pid] * 100)),
    )

    token = cli_main._pause_windows_gateways_for_update()

    assert worker_reads["count"] > 2
    assert 82 not in pause_fleet.stopped
    assert pause_fleet.stopped == [303, 404]
    assert token["profiles"] == {"work": 101}


def test_interrupt_rollback_watcher_timeout_is_reported_not_counted_as_recovered(
    pause_fleet: SimpleNamespace,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Watcher creation alone must not count as a completed pause rollback.

    The paused gateway keeps draining for 180 s after Ctrl+C. The detached
    watcher gives up at its 120 s deadline without spawning a duplicate, so
    the rollback must surface the gateway as needing recovery.
    """
    import sys
    import time

    import gateway.status as status_mod
    import hermes_cli.gateway_windows as gateway_windows

    clock = {"now": 0.0}
    spawned: list[list[str]] = []
    monkeypatch.setattr(
        _gateway_mod, "launch_detached_profile_gateway_restart", _REAL_PROFILE_RESTART
    )
    monkeypatch.setattr(
        gateway_windows, "windowless_gateway_restart_spec", lambda argv: (argv, "", {})
    )
    monkeypatch.setattr(
        _gateway_mod.subprocess,
        "Popen",
        lambda argv, **_kw: spawned.append(list(argv)),
    )
    monkeypatch.setattr(
        status_mod,
        "_pid_identity_is_live",
        lambda pid, started: (pid, started) == (101, 99.0) and clock["now"] < 180.0,
    )
    monkeypatch.setattr(
        cli_main,
        "_wait_for_windows_update_gateway_exit",
        lambda *_a, **_kw: (_ for _ in ()).throw(KeyboardInterrupt()),
    )

    with pytest.raises(KeyboardInterrupt) as error:
        cli_main._pause_windows_gateways_for_update()

    notes = " ".join(getattr(error.value, "__notes__", ()))
    assert "recovery unverified" in notes
    assert "work" in notes
    assert "old gateway PID(s) 101 still running" in notes
    assert len(spawned) == 1

    # Run the detached watcher on a virtual clock: it must refuse at 120 s
    # while the old incarnation is still draining, and never spawn.
    watcher_argv = spawned[0]
    with monkeypatch.context() as watcher_patch:
        watcher_patch.setattr(time, "monotonic", lambda: clock["now"])
        watcher_patch.setattr(
            time,
            "sleep",
            lambda seconds: clock.__setitem__("now", clock["now"] + seconds),
        )
        watcher_patch.setattr(sys, "argv", ["-c", *watcher_argv[3:]])
        with pytest.raises(SystemExit) as watcher_exit:
            exec(compile(watcher_argv[2], "<gateway-restart-watcher>", "exec"), {})
    assert watcher_exit.value.code == 1
    assert 120.0 <= clock["now"] < 180.0
    assert len(spawned) == 1


def test_drain_failure_rollback_reports_unverified_watcher_handoff(
    pause_fleet: SimpleNamespace,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An ordinary pause failure carries the unverified recovery in its detail."""
    import gateway.status as status_mod

    pause_fleet.fail_drain = True
    monkeypatch.setattr(
        status_mod,
        "_pid_identity_is_live",
        lambda pid, started: (pid, started) == (101, 99.0),
    )

    with pytest.raises(RuntimeError) as error:
        cli_main._pause_windows_gateways_for_update()

    message = str(error.value)
    assert "synthetic drain failure" in message
    assert "rollback failures: ordinary gateways: recovery unverified" in message
    assert pause_fleet.restarted == [("work", 101, 99.0)]


@pytest.mark.parametrize("partial_failure", [False, True])
def test_abort_retains_unobserved_recovery_even_after_a_partial_restart_failure(
    pause_fleet: SimpleNamespace,
    monkeypatch: pytest.MonkeyPatch,
    partial_failure: bool,
) -> None:
    """An exception cannot discard the pending result of an already armed watcher."""
    captured: list[dict] = []
    receipts: list[tuple] = []
    pause_fleet.fail_drain = True

    def resume(token: dict) -> None:
        captured.append(token)
        token["relaunched_profiles"] = ["work"]
        token["watcher_old_identities"] = [(101, 99.0)]
        token["profiles"] = {}
        token["resume_needed"] = False
        if partial_failure:
            raise RuntimeError("another restart failed after arming work")

    monkeypatch.setattr(_update_cmd, "_resume_windows_gateways_after_update", resume)
    monkeypatch.setattr(
        _update_cmd, "_old_gateway_process_identity_is_live", lambda *_args: True
    )
    monkeypatch.setattr(
        "hermes_cli.update_receipt.record_step",
        lambda *args, **_kwargs: receipts.append(args),
    )

    with pytest.raises(RuntimeError) as error:
        cli_main._pause_windows_gateways_for_update()

    assert "recovery unverified" in str(error.value)
    assert captured[0]["rollback_recovery_pending"] is True
    assert "work" in captured[0]["rollback_recovery_detail"]
    assert any(
        step[0] == "windows_gateway_pause_rollback" and step[1] is False
        for step in receipts
    )
    if partial_failure:
        assert "another restart failed" in str(error.value)
