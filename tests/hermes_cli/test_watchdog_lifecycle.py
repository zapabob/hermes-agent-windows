from __future__ import annotations

import base64
from pathlib import Path

import pytest

from hermes_cli import watchdog_lifecycle
from hermes_cli.watchdog_maintenance import WatchdogMaintenanceLease

REPO_ROOT = Path(__file__).resolve().parents[2]
LIFECYCLE_SCRIPT = (
    REPO_ROOT / "scripts" / "windows" / "Invoke-HermesGoWatchdogLifecycle.ps1"
)


def _lease(tmp_path: Path) -> WatchdogMaintenanceLease:
    state = tmp_path / "maintenance.json"
    state.write_text("{}", encoding="utf-8")
    return WatchdogMaintenanceLease(
        path=state,
        owner="hermes-update:123",
        nonce="test-nonce",
        epoch=1,
        reason="test",
        lease_seconds=60,
        repo_root=str(REPO_ROOT),
    )


def test_operator_script_requires_identity_bound_update_lease():
    source = LIFECYCLE_SCRIPT.read_text(encoding="utf-8")

    assert "Test-IsElevatedOperator" in source
    assert '[string]$state.state -ne "UPDATE"' in source
    assert "$state.nonce" in source
    assert "$state.repoRoot" in source
    assert "$state.processStartTime" in source
    assert "leaseExpiresAt" in source


def test_operator_script_disables_before_exact_stop_and_unregisters_after():
    source = LIFECYCLE_SCRIPT.read_text(encoding="utf-8")
    disable = source.index("Disable-ScheduledTask")
    stop = source.index("& $launcher -Stop")
    unregister = source.index("Unregister-ScheduledTask")

    assert '"HermesGoWatchdogBootAutoStart"' in source
    assert "Refusing to alter a foreign scheduled task" in source
    assert disable < stop < unregister
    assert "ForceRestart" not in source


def test_lifecycle_runner_uses_uac_and_hides_nonce_in_encoded_command(
    tmp_path, monkeypatch
):
    lease = _lease(tmp_path)
    calls = []
    monkeypatch.setattr(watchdog_lifecycle.sys, "platform", "win32")
    monkeypatch.setattr(
        watchdog_lifecycle.subprocess,
        "run",
        lambda argv, **kwargs: calls.append((argv, kwargs))
        or type("Result", (), {"returncode": 0, "stdout": "", "stderr": ""})(),
    )

    watchdog_lifecycle.decommission_for_uninstall(
        project_root=REPO_ROOT,
        hermes_home=tmp_path,
        lease=lease,
    )

    argv, kwargs = calls[0]
    outer = argv[-1]
    assert "-Verb RunAs" in outer
    assert "-WindowStyle Hidden" in outer
    assert "test-nonce" not in outer
    assert kwargs["check"] is False
    encoded = outer.split("'-EncodedCommand','", 1)[1].split("'", 1)[0]
    inner = base64.b64decode(encoded).decode("utf-16-le")
    assert "Invoke-HermesGoWatchdogLifecycle.ps1" in inner
    assert "-MaintenanceNonce 'test-nonce'" in inner


def test_lifecycle_runner_fails_closed_when_operator_path_fails(
    tmp_path, monkeypatch
):
    lease = _lease(tmp_path)
    monkeypatch.setattr(watchdog_lifecycle.sys, "platform", "win32")
    monkeypatch.setattr(
        watchdog_lifecycle.subprocess,
        "run",
        lambda *_args, **_kwargs: type(
            "Result",
            (),
            {"returncode": 1223, "stdout": "", "stderr": ""},
        )(),
    )

    with pytest.raises(RuntimeError, match="operator approval was denied"):
        watchdog_lifecycle.decommission_for_uninstall(
            project_root=REPO_ROOT,
            hermes_home=tmp_path,
            lease=lease,
        )
