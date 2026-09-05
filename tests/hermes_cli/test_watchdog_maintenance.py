from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

import pytest

from hermes_cli import uninstall
from hermes_cli import update_cmd
from hermes_cli import watchdog_maintenance as maintenance

REPO_ROOT = Path(__file__).resolve().parents[2]
WINDOWS_HANDOFF = REPO_ROOT / "scripts" / "desktop-update" / "windows.ps1"


def read_state(path: Path) -> dict[str, object]:
    return json.loads(path.read_text(encoding="utf-8"))


def test_maintenance_path_matches_go_watchdog_layout(tmp_path):
    assert maintenance.maintenance_path(
        {"LOCALAPPDATA": str(tmp_path)}, hermes_home=tmp_path / "home"
    ) == tmp_path / "HermesWatchdog" / "maintenance.json"
    assert maintenance.maintenance_path(
        {}, hermes_home=tmp_path / "home"
    ) == tmp_path / "home" / "watchdog-go" / "maintenance.json"


def test_desktop_handoff_waits_for_watchdog_before_drain():
    source = WINDOWS_HANDOFF.read_text(encoding="utf-8")
    prepare = source.index('Set-WatchdogMaintenanceState "UPDATE_PREPARE"')
    acknowledge = source.index("Wait-WatchdogMaintenanceAcknowledge", prepare)
    drain = source.index('Set-WatchdogMaintenanceState "UPSTREAM_DRAIN"')
    assert prepare < acknowledge < drain
    assert "HERMES_WATCHDOG_MAINTENANCE_NONCE" in source
    assert 'Set-WatchdogMaintenanceState "RECOVERY"' in source
    assert 'Set-WatchdogMaintenanceState "NORMAL"' in source


def test_lease_records_ordered_states_and_rejects_another_owner(tmp_path):
    path = tmp_path / "maintenance.json"
    now = datetime(2026, 9, 1, 3, 0, tzinfo=UTC)
    lease = maintenance.acquire(tmp_path, path=path, now=now)
    assert read_state(path)["state"] == maintenance.UPDATE_PREPARE

    for offset, state in enumerate(
        (maintenance.UPSTREAM_DRAIN, maintenance.UPDATE, maintenance.RECOVERY),
        start=1,
    ):
        maintenance.transition(
            lease, state, now=now + timedelta(seconds=offset)
        )
        payload = read_state(path)
        assert payload["state"] == state
        assert payload["owner"] == lease.owner
        assert payload["nonce"] == lease.nonce
        assert payload["epoch"] == lease.epoch

    with pytest.raises(RuntimeError, match="already owned"):
        maintenance.acquire(
            tmp_path,
            path=path,
            now=now + timedelta(minutes=1),
        )

    maintenance.release(lease)
    assert read_state(path)["state"] == maintenance.NORMAL


def test_expired_lease_can_be_replaced(tmp_path):
    path = tmp_path / "maintenance.json"
    now = datetime(2026, 9, 1, 3, 0, tzinfo=UTC)
    first = maintenance.acquire(
        tmp_path,
        path=path,
        now=now,
        lease_seconds=1,
    )
    second = maintenance.acquire(
        tmp_path,
        path=path,
        now=now + timedelta(seconds=2),
    )
    assert second.nonce != first.nonce
    assert read_state(path)["nonce"] == second.nonce


def test_python_updater_adopts_desktop_handoff_lease(tmp_path, monkeypatch):
    path = tmp_path / "maintenance.json"
    now = datetime(2026, 9, 1, 3, 0, tzinfo=UTC)
    parent = maintenance.acquire(tmp_path, path=path, now=now)
    monkeypatch.setenv("HERMES_WATCHDOG_MAINTENANCE_OWNER", parent.owner)
    monkeypatch.setenv("HERMES_WATCHDOG_MAINTENANCE_NONCE", parent.nonce)
    monkeypatch.setenv("HERMES_WATCHDOG_MAINTENANCE_EPOCH", str(parent.epoch))

    child = maintenance.acquire(
        tmp_path,
        path=path,
        now=now + timedelta(seconds=1),
    )

    assert child.handoff_parent is True
    assert child.nonce == parent.nonce
    maintenance.release(child)
    assert read_state(path)["state"] == maintenance.RECOVERY


def test_update_wrapper_runs_official_recovery_before_normal(
    tmp_path, monkeypatch
):
    path = tmp_path / "maintenance.json"
    monkeypatch.setattr(
        maintenance, "maintenance_path", lambda: path
    )
    monkeypatch.setattr(
        update_cmd,
        "_m",
        lambda: SimpleNamespace(_is_windows=lambda: True, PROJECT_ROOT=tmp_path),
    )
    monkeypatch.setattr(update_cmd, "_WATCHDOG_MAINTENANCE_ATEXIT_REGISTERED", True)
    monkeypatch.setattr(update_cmd, "_ACTIVE_WATCHDOG_MAINTENANCE", None)
    (tmp_path / "pyproject.toml").write_text("[project]\n", encoding="utf-8")

    update_cmd._begin_watchdog_update_maintenance()
    assert read_state(path)["state"] == maintenance.UPDATE_PREPARE
    update_cmd._transition_watchdog_update_maintenance(
        maintenance.UPSTREAM_DRAIN, reason="test drain"
    )
    update_cmd._transition_watchdog_update_maintenance(
        maintenance.UPDATE, reason="test update"
    )
    update_cmd._resume_windows_gateways_after_update(None)
    assert read_state(path)["state"] == maintenance.NORMAL
    assert update_cmd._ACTIVE_WATCHDOG_MAINTENANCE is None


def test_failed_official_recovery_keeps_watchdog_in_recovery(
    tmp_path, monkeypatch
):
    path = tmp_path / "maintenance.json"
    monkeypatch.setattr(maintenance, "maintenance_path", lambda: path)
    monkeypatch.setattr(
        update_cmd,
        "_m",
        lambda: SimpleNamespace(_is_windows=lambda: True, PROJECT_ROOT=tmp_path),
    )
    monkeypatch.setattr(update_cmd, "_WATCHDOG_MAINTENANCE_ATEXIT_REGISTERED", True)
    monkeypatch.setattr(update_cmd, "_ACTIVE_WATCHDOG_MAINTENANCE", None)
    (tmp_path / "pyproject.toml").write_text("[project]\n", encoding="utf-8")
    update_cmd._begin_watchdog_update_maintenance()
    monkeypatch.setattr(
        update_cmd,
        "_resume_windows_gateways_after_update_impl",
        lambda _token: (_ for _ in ()).throw(RuntimeError("restart failed")),
    )

    with pytest.raises(RuntimeError, match="restart failed"):
        update_cmd._resume_windows_gateways_after_update({"resume_needed": True})

    assert read_state(path)["state"] == maintenance.RECOVERY
    assert update_cmd._ACTIVE_WATCHDOG_MAINTENANCE is not None
    update_cmd._release_watchdog_update_maintenance_at_exit()
    assert read_state(path)["state"] == maintenance.RECOVERY
    assert update_cmd._ACTIVE_WATCHDOG_MAINTENANCE is None


def test_uninstall_lifecycle_is_fenced_until_success(tmp_path, monkeypatch):
    path = tmp_path / "maintenance.json"
    calls = []
    monkeypatch.setattr(uninstall, "_is_windows", lambda: True)
    monkeypatch.setattr(maintenance, "maintenance_path", lambda: path)
    monkeypatch.setattr(
        "hermes_cli.watchdog_lifecycle.decommission_for_uninstall",
        lambda **kwargs: calls.append(kwargs),
    )

    with uninstall._watchdog_uninstall_fence(tmp_path, reason="test uninstall"):
        payload = read_state(path)
        assert payload["state"] == maintenance.UPDATE
        assert payload["owner"].startswith("hermes-update:")
        assert len(calls) == 1
        assert calls[0]["project_root"] == tmp_path
        assert calls[0]["lease"].nonce == payload["nonce"]

    assert read_state(path)["state"] == maintenance.NORMAL


def test_failed_uninstall_keeps_expiring_recovery_fence(tmp_path, monkeypatch):
    path = tmp_path / "maintenance.json"
    monkeypatch.setattr(uninstall, "_is_windows", lambda: True)
    monkeypatch.setattr(maintenance, "maintenance_path", lambda: path)
    monkeypatch.setattr(
        "hermes_cli.watchdog_lifecycle.decommission_for_uninstall",
        lambda **_kwargs: None,
    )

    with pytest.raises(RuntimeError, match="removal failed"):
        with uninstall._watchdog_uninstall_fence(tmp_path, reason="test uninstall"):
            raise RuntimeError("removal failed")

    payload = read_state(path)
    assert payload["state"] == maintenance.RECOVERY
    assert payload["leaseExpiresAt"] > payload["timestamp"]


def test_failed_watchdog_decommission_keeps_recovery_fence(tmp_path, monkeypatch):
    path = tmp_path / "maintenance.json"
    monkeypatch.setattr(uninstall, "_is_windows", lambda: True)
    monkeypatch.setattr(maintenance, "maintenance_path", lambda: path)

    def refuse(**_kwargs):
        raise RuntimeError("operator denied")

    monkeypatch.setattr(
        "hermes_cli.watchdog_lifecycle.decommission_for_uninstall",
        refuse,
    )

    with pytest.raises(RuntimeError, match="operator denied"):
        with uninstall._watchdog_uninstall_fence(tmp_path, reason="test uninstall"):
            pytest.fail("destructive uninstall body must not run")

    assert read_state(path)["state"] == maintenance.RECOVERY
