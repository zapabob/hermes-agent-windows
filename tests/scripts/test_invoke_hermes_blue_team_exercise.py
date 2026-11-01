from __future__ import annotations

import importlib.util
from pathlib import Path

MODULE_PATH = (
    Path(__file__).resolve().parents[2]
    / "scripts"
    / "windows"
    / "invoke_hermes_blue_team_exercise.py"
)
SPEC = importlib.util.spec_from_file_location("invoke_hermes_blue_team_exercise", MODULE_PATH)
assert SPEC is not None and SPEC.loader is not None
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def test_script_discovers_repository_root_without_machine_specific_drives() -> None:
    assert MODULE.ROOT == MODULE_PATH.parents[2]
    assert MODULE.OUTPUT == MODULE_PATH.parents[2] / "output" / "reports"


def test_main_returns_nonzero_for_blocking_posture_and_reports_only_control_ids(monkeypatch, tmp_path: Path) -> None:
    emitted: list[str] = []
    report = {
        "overall": "high_risk",
        "checks": [
            {"id": "approvals.interactive", "status": "fail", "severity": "high"},
            {"id": "host.network_listeners", "status": "review", "severity": "info"},
        ],
    }

    class Service:
        def __init__(self, *, read_only: bool) -> None:
            assert read_only is True

        def status(self):
            return {"watch": {}, "engines": {}}

    monkeypatch.setattr(MODULE, "SecurityService", Service)
    monkeypatch.setattr(MODULE, "load_config", lambda: {"approvals": {"mode": "off"}})
    monkeypatch.setattr(MODULE, "run_posture_audit", lambda **_kwargs: report)
    monkeypatch.setattr(
        MODULE,
        "write_posture_report",
        lambda _report, output: {
            "evidence": output / "evidence.json",
            "report": output / "report.md",
        },
    )
    monkeypatch.setattr(MODULE, "OUTPUT", tmp_path)
    monkeypatch.setattr(MODULE.LOG, "info", emitted.append)

    assert MODULE.main() == 1
    assert len(emitted) == 1
    assert '"failed_controls": ["approvals.interactive"]' in emitted[0]
    assert "ARTEX" not in emitted[0]
    assert "Docker" not in emitted[0]


def test_main_returns_zero_when_no_high_or_critical_control_failed(monkeypatch, tmp_path: Path) -> None:
    class Service:
        def __init__(self, *, read_only: bool) -> None:
            assert read_only is True

        def status(self):
            return {}

    monkeypatch.setattr(MODULE, "SecurityService", Service)
    monkeypatch.setattr(MODULE, "load_config", dict)
    monkeypatch.setattr(
        MODULE,
        "run_posture_audit",
        lambda **_kwargs: {
            "overall": "attention",
            "checks": [{"id": "host.network_listeners", "status": "review", "severity": "info"}],
        },
    )
    monkeypatch.setattr(
        MODULE,
        "write_posture_report",
        lambda _report, output: {
            "evidence": output / "evidence.json",
            "report": output / "report.md",
        },
    )
    monkeypatch.setattr(MODULE, "OUTPUT", tmp_path)
    monkeypatch.setattr(MODULE.LOG, "info", lambda _message: None)

    assert MODULE.main() == 0


def test_main_verifies_the_gateway_listener_owner(monkeypatch, tmp_path: Path) -> None:
    collected: list[tuple[dict[str, object], int | None]] = []

    class Service:
        def __init__(self, *, read_only: bool) -> None:
            assert read_only is True

        def status(self):
            return {}

    monkeypatch.setattr(MODULE, "SecurityService", Service)
    monkeypatch.setattr(MODULE, "load_config", lambda: {"gateway": {"api_server": {"port": 8642}}})
    monkeypatch.setattr(MODULE, "get_running_pid", lambda: 4242, raising=False)
    monkeypatch.setattr(
        MODULE,
        "collect_host_evidence",
        lambda config, *, expected_api_pid=None: collected.append((config, expected_api_pid)) or {},
        raising=False,
    )

    def _audit(**kwargs):
        kwargs["host_collector"](kwargs["config"])
        return {"overall": "attention", "checks": []}

    monkeypatch.setattr(MODULE, "run_posture_audit", _audit)
    monkeypatch.setattr(
        MODULE,
        "write_posture_report",
        lambda _report, output: {
            "evidence": output / "evidence.json",
            "report": output / "report.md",
        },
    )
    monkeypatch.setattr(MODULE, "OUTPUT", tmp_path)
    monkeypatch.setattr(MODULE.LOG, "info", lambda _message: None)

    assert MODULE.main() == 0
    assert collected == [({"gateway": {"api_server": {"port": 8642}}}, 4242)]