from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest


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


@pytest.mark.parametrize("raw", ["true", "TRUE", "1", "yes", "on", "'true'"])
def test_config_enabled_accepts_explicit_truthy_values(monkeypatch, raw):
    monkeypatch.setattr(MODULE, "config_value", lambda _key: raw)
    assert MODULE.config_enabled("unused") is True


def test_secure_defaults_have_no_configuration_findings(monkeypatch):
    values = {
        "browser.allow_private_urls": "false",
        "security.allow_private_urls": "false",
        "browser.use_real_profile": "false",
        "approvals.unattended_mode": "deny",
        "gateway.api_server.host": None,
    }
    monkeypatch.setattr(MODULE, "config_value", values.get)
    assert MODULE.configuration_findings() == []


def test_expanded_attack_surface_is_reported(monkeypatch):
    values = {
        "browser.allow_private_urls": "true",
        "security.allow_private_urls": "true",
        "browser.use_real_profile": "true",
        "approvals.unattended_mode": "approve",
        "gateway.api_server.host": "0.0.0.0",
    }
    monkeypatch.setattr(MODULE, "config_value", values.get)

    findings = MODULE.configuration_findings()

    assert {item["control"] for item in findings} == {
        "ssrf",
        "browser-isolation",
        "approvals",
        "api-exposure",
    }
    assert sum(item["control"] == "ssrf" for item in findings) == 2
    assert any(item["severity"] == "critical" for item in findings)