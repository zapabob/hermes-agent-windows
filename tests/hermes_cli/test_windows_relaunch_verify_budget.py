"""A Windows update must budget for its own detached restart watchers."""

from __future__ import annotations

import sys
from types import SimpleNamespace
from unittest.mock import patch

import pytest

import gateway.status as gateway_status
import hermes_cli.gateway as gateway_cli
import hermes_cli.gateway_windows as gateway_windows
import hermes_cli.main as hermes_main
import hermes_cli.update_cmd as update_cmd
import psutil


def test_spawned_watcher_uses_the_budget_shared_with_update(monkeypatch):
    captured = []
    monkeypatch.setattr(
        gateway_windows,
        "windowless_gateway_restart_spec",
        lambda argv: (argv, "", {}),
    )
    monkeypatch.setattr(
        gateway_cli.subprocess,
        "Popen",
        lambda argv, **_kw: captured.append(argv),
    )
    monkeypatch.setattr(gateway_cli, "GATEWAY_RESTART_WATCHER_TIMEOUT_S", 137)

    assert gateway_cli.launch_detached_gateway_restart_by_cmdline(
        14980, ["python", "-m", "hermes_cli.main", "gateway", "run"]
    )
    assert len(captured) == 1
    assert "time.monotonic() + 137" in captured[0][2]


def test_resume_records_only_mapped_identities_handed_to_restart_watchers(monkeypatch):
    mapped_launches = []
    unmapped_launches = []
    unmapped_argv = ["python", "-m", "hermes_cli.main", "gateway", "run"]
    monkeypatch.setattr(hermes_main, "_is_windows", lambda: True)
    monkeypatch.setattr(hermes_main, "_refresh_windows_gateway_launchers", lambda: None)
    monkeypatch.setattr(
        gateway_cli,
        "launch_detached_profile_gateway_restart",
        lambda *args: mapped_launches.append(args) or True,
    )
    monkeypatch.setattr(
        gateway_cli,
        "launch_detached_gateway_restart_by_cmdline",
        lambda *args: unmapped_launches.append(args) or True,
    )
    token = {
        "resume_needed": True,
        "profiles": {"default": 14980},
        "profile_old_identities": {"default": (14980, 99.0)},
        "unmapped": [{"pid": 4242, "argv": unmapped_argv}],
        "services": [],
    }

    with patch("builtins.print"):
        update_cmd._resume_windows_gateways_after_update_impl(token)

    # An unmapped process cannot produce a profile state row for this probe.
    assert mapped_launches == [("default", 14980, 99.0)]
    assert unmapped_launches == [(4242, unmapped_argv)]
    assert token["watcher_old_identities"] == [(14980, 99.0)]
    assert token["resume_needed"] is False


def test_generic_manual_profile_restart_passes_identity_to_watcher(monkeypatch):
    seen = []
    monkeypatch.setattr(
        gateway_cli,
        "_capture_gateway_argv",
        lambda _pid: ["python", "-m", "hermes_cli.main", "gateway", "run"],
    )
    monkeypatch.setattr(
        gateway_cli,
        "launch_detached_profile_gateway_restart",
        lambda *args: seen.append(args) or True,
    )

    assert gateway_cli._prepare_profile_gateway_update_restart(
        "work", 14980, old_create_time=99.0
    ) == "detached"
    assert seen == [("work", 14980, 99.0)]


def test_generic_manual_cmdline_fallback_keeps_the_same_identity(monkeypatch):
    seen = []
    argv = ["python", "-m", "hermes_cli.main", "gateway", "run"]
    monkeypatch.setattr(gateway_cli, "_capture_gateway_argv", lambda _pid: argv)
    monkeypatch.setattr(
        gateway_cli,
        "launch_detached_profile_gateway_restart",
        lambda *_args: False,
    )
    monkeypatch.setattr(
        gateway_cli,
        "launch_detached_gateway_restart_by_cmdline",
        lambda *args: seen.append(args) or True,
    )

    assert gateway_cli._prepare_profile_gateway_update_restart(
        "work", 14980, old_create_time=99.0
    ) == "detached-cmdline"
    assert seen == [(14980, argv, 99.0)]


def test_unreadable_windows_profile_identity_returns_to_manual_stop_path(capsys):
    calls = []

    def find_profiles(**kwargs):
        calls.append(kwargs)
        raise RuntimeError("gateway creation time is unavailable")

    profiles, incomplete = update_cmd._find_manual_profile_gateways_for_restart(
        service_pids={101},
        manual_pids=[202],
        find_profile_gateway_processes=find_profiles,
        windows=True,
    )
    assert len(calls) == 1
    assert calls[0] == {
        "exclude_pids": {101},
        "strict": True,
        "strict_errors": [],
    }
    assert profiles == {}
    assert incomplete is True
    assert "manual restart" in capsys.readouterr().out


def test_unreadable_strict_identity_is_incomplete_with_empty_process_scan():
    def find_profiles(**_kwargs):
        raise RuntimeError("gateway creation time is unavailable")

    profiles, incomplete = update_cmd._find_manual_profile_gateways_for_restart(
        service_pids=set(),
        manual_pids=[],
        find_profile_gateway_processes=find_profiles,
        windows=True,
    )
    assert profiles == {}
    assert incomplete is True


def test_strict_profile_discovery_isolates_one_unreadable_profile(monkeypatch, tmp_path):
    profiles = [
        SimpleNamespace(name="bad", path=tmp_path / "bad"),
        SimpleNamespace(name="good", path=tmp_path / "good"),
    ]
    monkeypatch.setattr("hermes_cli.profiles.list_profiles", lambda: profiles)

    def strict_identity(pid_path):
        if pid_path.parent.name == "bad":
            raise RuntimeError("gateway creation time is unavailable")
        return 202, 99.0

    monkeypatch.setattr(
        gateway_status, "get_running_pid_identity_strict", strict_identity
    )
    errors = []
    found = gateway_cli.find_profile_gateway_processes(
        strict=True, strict_errors=errors
    )
    assert errors == ["bad"]
    assert [(proc.profile, proc.pid, proc.create_time) for proc in found] == [
        ("good", 202, 99.0)
    ]
    with pytest.raises(RuntimeError, match="Could not inspect gateway PID"):
        gateway_cli.find_profile_gateway_processes(strict=True)


def test_one_strict_error_preserves_other_manual_restart_candidates(capsys):
    good = SimpleNamespace(pid=202, profile="good", create_time=99.0)

    def find_profiles(**kwargs):
        kwargs["strict_errors"].append("bad")
        return [good]

    profiles, incomplete = update_cmd._find_manual_profile_gateways_for_restart(
        service_pids={101},
        manual_pids=[202, 303],
        find_profile_gateway_processes=find_profiles,
        windows=True,
    )
    assert profiles == {202: good}
    assert incomplete is True
    assert "manual restart" in capsys.readouterr().out


def test_verified_windows_profile_identity_remains_restartable():
    process = SimpleNamespace(pid=202, profile="work", create_time=99.0)
    profiles, incomplete = update_cmd._find_manual_profile_gateways_for_restart(
        service_pids={101},
        manual_pids=[202],
        find_profile_gateway_processes=lambda **kwargs: [process]
        if kwargs["exclude_pids"] == {101} and kwargs["strict"] is True
        else [],
        windows=True,
    )
    assert profiles == {202: process}
    assert incomplete is False


def test_fleet_wait_budget_tracks_pending_watchers_without_widening_others():
    token = {"watcher_old_identities": [(14980, 99.0)]}
    assert update_cmd._windows_relaunch_verify_timeout_s(
        token, lambda pid, started: (pid, started) == (14980, 99.0)
    ) > gateway_cli.GATEWAY_RESTART_WATCHER_TIMEOUT_S
    assert update_cmd._windows_relaunch_verify_timeout_s(
        token, lambda _pid, _started: False
    ) == 30.0
    assert update_cmd._windows_relaunch_verify_timeout_s(
        {"services": ["hermes-gateway"]}, lambda _pid, _started: True
    ) == 30.0


def test_up_row_cannot_end_fleet_probe_while_same_old_process_is_alive():
    now = [0.0]
    token = {"watcher_old_identities": [(14980, 99.0)]}

    def sleep(seconds):
        now[0] += seconds

    def identity_is_live(pid, started):
        return (pid, started) == (14980, 99.0) and now[0] < 120.0

    def collect_fleet_versions(*, pre_restart_pids):
        assert pre_restart_pids == [14980]
        return [
            {"state": "up", "profile": "bravo", "pid": 20202},
            {
                "state": "up",
                "profile": "alpha",
                "pid": 14980 if now[0] < 120.0 else 30303,
            },
        ]

    snapshot, pending = update_cmd._poll_fleet_versions_with_relaunch_budget(
        pre_restart_pids=[14980],
        windows_resume_token=token,
        collect_fleet_versions=collect_fleet_versions,
        monotonic=lambda: now[0],
        sleep=sleep,
        identity_is_live=identity_is_live,
    )
    assert now[0] >= 120.0
    assert snapshot[1]["pid"] == 30303
    assert pending is False


def test_same_pid_new_start_time_does_not_widen_the_wait():
    token = {"watcher_old_identities": [(14980, 99.0)]}
    current_start_time = 100.0
    assert update_cmd._windows_relaunch_verify_timeout_s(
        token, lambda pid, started: pid == 14980 and started == current_start_time
    ) == 30.0


def test_watcher_receives_the_old_start_time_for_pid_reuse(monkeypatch):
    captured = []
    monkeypatch.setattr(
        gateway_windows,
        "windowless_gateway_restart_spec",
        lambda argv: (argv, "", {}),
    )
    monkeypatch.setattr(
        gateway_cli.subprocess,
        "Popen",
        lambda argv, **_kw: captured.append(argv),
    )

    assert gateway_cli.launch_detached_profile_gateway_restart(
        "default", 14980, old_create_time=99.0
    )
    assert len(captured) == 1
    watcher_source = captured[0][2]
    assert "_old_create_time = 99.0" in watcher_source
    assert "_pid_identity_is_live(pid, _old_create_time)" in watcher_source
    assert "if _old_process_alive():\n    sys.exit(1)" in watcher_source


@pytest.mark.parametrize("old_identity_live", [False, True])
def test_generated_watcher_relaunches_only_after_old_incarnation_exits(
    monkeypatch, old_identity_live
):
    captured = []
    monkeypatch.setattr(
        gateway_windows,
        "windowless_gateway_restart_spec",
        lambda argv: (argv, "", {}),
    )
    monkeypatch.setattr(
        gateway_cli.subprocess,
        "Popen",
        lambda argv, **_kw: captured.append(argv),
    )
    monkeypatch.setattr(gateway_cli, "GATEWAY_RESTART_WATCHER_TIMEOUT_S", 0)
    monkeypatch.setattr(
        gateway_status,
        "_pid_identity_is_live",
        lambda pid, started: old_identity_live and (pid, started) == (14980, 99.0),
    )

    assert gateway_cli.launch_detached_profile_gateway_restart(
        "default", 14980, old_create_time=99.0
    )
    watcher_argv = captured[0]
    monkeypatch.setattr(sys, "argv", ["-c", *watcher_argv[3:]])
    if old_identity_live:
        with pytest.raises(SystemExit) as error:
            exec(compile(watcher_argv[2], "<gateway-restart-watcher>", "exec"), {})
        assert error.value.code == 1
        assert len(captured) == 1
    else:
        exec(compile(watcher_argv[2], "<gateway-restart-watcher>", "exec"), {})
        assert captured[1] == watcher_argv[4:]


def test_old_row_collected_just_before_exit_requires_a_fresh_snapshot():
    token = {"watcher_old_identities": [(14980, 99.0)]}
    state = {"clock": 0.0, "checks": 0, "collects": 0}

    def identity_is_live(pid, started):
        assert (pid, started) == (14980, 99.0)
        state["checks"] += 1
        return state["checks"] <= 2

    def collect_fleet_versions(*, pre_restart_pids):
        assert pre_restart_pids == [14980]
        state["collects"] += 1
        return [{"state": "up", "pid": 14980 if state["collects"] == 1 else 30303}]

    snapshot, pending = update_cmd._poll_fleet_versions_with_relaunch_budget(
        pre_restart_pids=[14980],
        windows_resume_token=token,
        collect_fleet_versions=collect_fleet_versions,
        monotonic=lambda: state["clock"],
        sleep=lambda seconds: state.__setitem__("clock", state["clock"] + seconds),
        identity_is_live=identity_is_live,
    )
    assert state["collects"] == 2
    assert snapshot == [{"state": "up", "pid": 30303}]
    assert pending is False


def test_live_pid_requires_the_original_start_time(monkeypatch):
    monkeypatch.setattr(
        psutil,
        "Process",
        lambda _pid: SimpleNamespace(
            is_running=lambda: True,
            create_time=lambda: 100.0,
        ),
    )
    assert update_cmd._old_gateway_process_identity_is_live(14980, 99.0) is False
    assert update_cmd._old_gateway_process_identity_is_live(14980, 100.0) is True


def test_old_process_still_alive_at_deadline_is_not_verified():
    now = [0.0]
    token = {"watcher_old_identities": [(14980, 99.0)]}

    def sleep(seconds):
        now[0] += seconds

    snapshot, pending = update_cmd._poll_fleet_versions_with_relaunch_budget(
        pre_restart_pids=[14980],
        windows_resume_token=token,
        collect_fleet_versions=lambda **_kw: [{"state": "up", "pid": 14980}],
        monotonic=lambda: now[0],
        sleep=sleep,
        identity_is_live=lambda pid, started: (pid, started) == (14980, 99.0),
    )
    assert snapshot[0]["pid"] == 14980
    assert now[0] >= 150.0
    assert pending is True
