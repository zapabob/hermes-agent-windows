from __future__ import annotations

import asyncio
import hashlib
import importlib
import json
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from typing import cast
from unittest.mock import Mock

import pytest

from downstream.security.models import EngineState, Finding, ScanResult, Verdict
from downstream.security.service import SecurityService
from downstream.security.store import SecurityStore


class YaraDetectionEngine:
    name = "yara"

    def version(self) -> str:
        return "inert-test-rules-1"

    def scan(self, _path: Path, _sha256: str) -> list[Finding]:
        return [Finding(self.name, "synthetic-test-detection", 80)]


class ClamAVErrorEngine:
    name = "clamav"

    def version(self) -> str:
        return "scanner-error-fixture"

    def scan(self, _path: Path, _sha256: str) -> list[Finding]:
        return [
            Finding(
                self.name,
                "scanner-error",
                0,
                EngineState.ENGINE_ERROR,
                {"error": "private path detail"},
            )
        ]


class CleanEngine:
    name = "clamav"

    def version(self) -> str:
        return "inert-clean-fixture"

    def scan(self, _path: Path, _sha256: str) -> list[Finding]:
        return [Finding(self.name, "no_detection", 0)]


class YaraErrorEngine:
    name = "yara"

    def version(self) -> str:
        return "inert-error-fixture"

    def scan(self, _path: Path, _sha256: str) -> list[Finding]:
        return [Finding(self.name, "scanner-error", 0, EngineState.ENGINE_ERROR)]


class UnavailableEngine:
    def __init__(self, name: str) -> None:
        self.name = name

    def version(self) -> str:
        return EngineState.SCANNER_UNAVAILABLE.value

    def scan(self, _path: Path, _sha256: str) -> list[Finding]:
        return [Finding(self.name, "scanner-unavailable", 0, EngineState.SCANNER_UNAVAILABLE)]


@pytest.mark.parametrize(
    ("engines", "expected_kind"),
    [
        ((YaraDetectionEngine(), ClamAVErrorEngine()), "malicious"),
        ((UnavailableEngine("clamav"), UnavailableEngine("yara")), "unverified"),
    ],
    ids=("malicious-with-engine-error", "no-authoritative-scanner"),
)
def test_terminal_tool_blocks_malicious_and_unverified_candidates(
    monkeypatch,
    tmp_path: Path,
    engines: tuple[object, ...],
    expected_kind: str,
) -> None:
    target = tmp_path / "inert-fixture.ps1"
    target.write_text("Write-Output 'inert fixture'\n", encoding="utf-8")
    service = SecurityService(
        SecurityStore(tmp_path / "security"),
        {"security": {"malware": {"auto_quarantine": False}}},
    )
    service.engines = engines

    execution_gate = importlib.import_module("downstream.security.execution_gate")
    monkeypatch.setattr(
        execution_gate,
        "load_config",
        lambda: {"security": {"malware": {"enabled": True, "execution_gate": True}}},
    )
    monkeypatch.setattr(execution_gate, "SecurityService", lambda **_kwargs: service)

    terminal = importlib.import_module("tools.terminal_tool")
    monkeypatch.setattr(
        terminal,
        "_get_env_config",
        lambda: {
            "env_type": "local",
            "cwd": str(tmp_path),
            "timeout": 10,
            "docker_image": "",
            "singularity_image": "",
            "modal_image": "",
            "daytona_image": "",
        },
    )
    monkeypatch.setattr(terminal, "resolve_task_overrides", lambda _task_id: {})
    monkeypatch.setattr(terminal, "get_session_cwd", lambda _task_id: None)
    monkeypatch.setattr(terminal, "_resolve_task_host_cwd", lambda _config, _task_id: None)
    monkeypatch.setattr(terminal, "_start_cleanup_thread", lambda: None)
    monkeypatch.setattr(terminal, "_active_environments", {})
    executor = Mock(return_value=SimpleNamespace(execute=Mock(return_value={"output": "ran"})))
    monkeypatch.setattr(terminal, "_create_environment", executor)

    response = terminal.terminal_tool(f'pwsh -File "{target}"', workdir=str(tmp_path))

    executor.assert_not_called()
    assert f"blocked a {expected_kind} execution candidate" in json.loads(response)["error"]


def test_only_explicit_allowlist_can_allow_a_malicious_file() -> None:
    result = ScanResult(
        "inert-fixture.bin",
        "a" * 64,
        4,
        Verdict.MALICIOUS,
        80,
        "allow",
        (Finding("yara", "synthetic-test-detection", 80),),
        {},
    )

    assert result.execution_decision.value == "BLOCK"
    assert replace(result, action="allowlisted").execution_decision.value == "ALLOW"


def test_yara_detection_and_clamav_error_have_independent_dimensions(tmp_path: Path) -> None:
    target = tmp_path / "inert-fixture.bin"
    target.write_bytes(b"inert scanner fixture")
    service = SecurityService(
        SecurityStore(tmp_path / "security"),
        {"security": {"malware": {"auto_quarantine": False}}},
    )
    service.engines = (YaraDetectionEngine(), ClamAVErrorEngine())

    result = service.scan_file(target, quarantine=False)
    projection = result.to_dict()

    assert result.verdict.value == "MALICIOUS"
    assert projection["file_verdict"] == "MALICIOUS"
    assert projection["engine_health"] == "DEGRADED"
    assert projection["execution_decision"] == "BLOCK"
    assert projection["action"] == "quarantine"
    assert any(item["name"] == "synthetic-test-detection" for item in projection["findings"])
    assert all(item["details"] == {} for item in projection["findings"] if item["state"] != "available")
    assert "private path detail" not in json.dumps(projection)


def test_clean_finding_with_scanner_error_is_not_projected_as_clean(tmp_path: Path) -> None:
    target = tmp_path / "inert-clean-fixture.bin"
    target.write_bytes(b"inert scanner fixture")
    service = SecurityService(
        SecurityStore(tmp_path / "security"),
        {"security": {"malware": {"auto_quarantine": False}}},
    )
    service.engines = (CleanEngine(), YaraErrorEngine())

    result = service.scan_file(target, quarantine=False)
    projection = result.to_dict()

    assert result.verdict.value == "SCAN_ERROR"
    assert projection["file_verdict"] == "UNKNOWN"
    assert projection["engine_health"] == "DEGRADED"
    assert projection["execution_decision"] == "REVIEW"
    assert not any(item["score"] >= 80 for item in projection["findings"])


def test_quarantine_failure_retains_malicious_block_decision(
    monkeypatch,
    tmp_path: Path,
) -> None:
    target = tmp_path / "inert-quarantine-fixture.bin"
    target.write_bytes(b"inert scanner fixture")
    service = SecurityService(
        SecurityStore(tmp_path / "security"),
        {"security": {"malware": {"auto_quarantine": True}}},
    )
    service.engines = (YaraDetectionEngine(),)
    monkeypatch.setattr(service.vault, "quarantine", Mock(side_effect=PermissionError("private path detail")))

    result = service.scan_file(target)
    projection = result.to_dict()

    assert target.read_bytes() == b"inert scanner fixture"
    assert result.verdict.value == "MALICIOUS"
    assert projection["file_verdict"] == "MALICIOUS"
    assert projection["execution_decision"] == "BLOCK"
    assert result.action == "quarantine_failed"
    assert projection["error"] == "quarantine_failed"
    assert "private path detail" not in json.dumps(projection)


def test_cached_result_uses_current_allowlist_policy(tmp_path: Path) -> None:
    target = tmp_path / "inert-cache-fixture.bin"
    target.write_bytes(b"inert scanner fixture")
    service = SecurityService(
        SecurityStore(tmp_path / "security"),
        {"security": {"malware": {"auto_quarantine": False}}},
    )
    service.engines = (YaraDetectionEngine(),)
    original = service.scan_file(target, quarantine=False)
    sha256 = hashlib.sha256(target.read_bytes()).hexdigest()
    with service.store.connection() as connection:
        connection.execute(
            "INSERT INTO allowlist(kind,value,reason,created_by,created_at) "
            "VALUES('sha256',?,?,?,datetime('now'))",
            (sha256, "inert test allowlist", "test-user"),
        )

    allowed = service.scan_file(target, quarantine=False)
    with service.store.connection() as connection:
        connection.execute("DELETE FROM allowlist WHERE kind='sha256' AND value=?", (sha256,))
    blocked_again = service.scan_file(target, quarantine=False)

    assert original.cached is False
    assert allowed.cached is True
    assert allowed.action == "allowlisted"
    assert allowed.to_dict()["execution_decision"] == "ALLOW"
    assert blocked_again.cached is True
    assert blocked_again.action == "quarantine"
    assert blocked_again.to_dict()["execution_decision"] == "BLOCK"


def test_security_scan_api_projects_typed_decision_fields(monkeypatch, tmp_path: Path) -> None:
    target = tmp_path / "inert-api-fixture.bin"
    target.write_bytes(b"inert scanner fixture")
    service = SecurityService(
        SecurityStore(tmp_path / "security"),
        {"security": {"malware": {"auto_quarantine": False}}},
    )
    service.engines = (YaraDetectionEngine(), ClamAVErrorEngine())
    web_server = importlib.import_module("hermes_cli.web_server")
    monkeypatch.setattr(
        web_server,
        "_call_security_for_profile",
        lambda _profile, operation, **_kwargs: operation(service),
    )

    response = asyncio.run(
        web_server.security_scan(
            web_server.SecurityScanRequest(scope="custom", path=str(target), quarantine=False)
        )
    )
    result = response["results"][0]

    assert result["verdict"] == "MALICIOUS"
    assert result["action"] == "quarantine"
    assert result["cached"] is False
    assert result["file_verdict"] == "MALICIOUS"
    assert result["engine_health"] == "DEGRADED"
    assert result["execution_decision"] == "BLOCK"


def test_status_does_not_initialize_quarantine_vault(tmp_path: Path) -> None:
    root = tmp_path / "security"
    service = SecurityService(
        SecurityStore(root),
        {"security": {"malware": {"auto_quarantine": False}}},
    )

    status = service.status()

    summary = cast(dict[str, object], status["summary"])
    assert summary["files_scanned"] == 0
    assert not (root / "quarantine").exists()
    assert not (root / "vault-key.dpapi").exists()
