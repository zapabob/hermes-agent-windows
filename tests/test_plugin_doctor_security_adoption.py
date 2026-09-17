"""Behavioral regression tests for native Plugin Doctor admission scanning.

The live doctor entry point is exercised; only its plugin-execution boundary
and scanner response are substituted. No candidate plugin code is executed.
"""
from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from hermes_cli import plugin_dev


@pytest.fixture
def candidate(tmp_path: Path) -> Path:
    path = tmp_path / "plugin space 日本語"
    path.mkdir()
    return path


@pytest.mark.parametrize("verdict", ["dangerous", "unknown", None])
def test_doctor_blocks_non_admissible_scan_before_runtime(candidate, verdict):
    with patch("tools.plugin_guard.scan_plugin", return_value=SimpleNamespace(verdict=verdict)) as scan, \
         patch("tools.plugin_guard.format_scan_report", return_value="fixture scan findings"), \
         patch.object(plugin_dev, "_doctor_runtime") as runtime:
        report = plugin_dev.doctor_plugin(candidate)

    assert not report.ok, "Doctor must fail closed for a non-admissible scan verdict"
    runtime.assert_not_called()
    scan.assert_called_once()
    assert Path(scan.call_args.args[0]) == candidate.resolve()
    assert any("security scan" in finding.message.lower() for finding in report.findings)


def test_doctor_scanner_failure_is_closed_and_does_not_echo_exception_secrets(candidate):
    secret = "synthetic-credential-must-not-appear"
    with patch("tools.plugin_guard.scan_plugin", side_effect=RuntimeError(secret)), \
         patch.object(plugin_dev, "_doctor_runtime") as runtime:
        report = plugin_dev.doctor_plugin(candidate)

    runtime.assert_not_called()
    assert not report.ok
    assert "RuntimeError" in report.format_text()
    assert secret not in report.format_text()


@pytest.mark.parametrize("verdict", ["safe", "caution"])
def test_doctor_scans_before_existing_registration_path(candidate, verdict):
    calls = []

    def scan(path, **kwargs):
        calls.append("scan")
        return SimpleNamespace(verdict=verdict)

    def runtime(path):
        calls.append("runtime")
        raise plugin_dev._DoctorLoadError("registration boundary reached")

    with patch("tools.plugin_guard.scan_plugin", side_effect=scan), \
         patch("tools.plugin_guard.format_scan_report", return_value="fixture scan findings"), \
         patch.object(plugin_dev, "_doctor_runtime", side_effect=runtime):
        report = plugin_dev.doctor_plugin(candidate)

    assert calls == ["scan", "runtime"], "Scan must precede any plugin registration"
    assert any("registration boundary reached" in f.message for f in report.findings)
    warnings = [f.message for f in report.findings if f.level == "warning"]
    assert bool(warnings) is (verdict == "caution")


def test_missing_plugin_does_not_invoke_scan_or_runtime(tmp_path):
    with patch("tools.plugin_guard.scan_plugin") as scan, \
         patch.object(plugin_dev, "_doctor_runtime") as runtime:
        report = plugin_dev.doctor_plugin(tmp_path / "missing")
    assert not report.ok
    scan.assert_not_called()
    runtime.assert_not_called()
