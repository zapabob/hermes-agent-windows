from __future__ import annotations

import asyncio
import hashlib
import importlib
import json
import os
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from typing import cast
from unittest.mock import Mock

import pytest

from downstream.security.engines import StaticHeuristicsEngine
from downstream.security.models import EngineState, Finding, ScanResult, Verdict
from downstream.security.service import SecurityService
from downstream.security.store import SecurityStore


class YaraDetectionEngine:
    name = "yara"

    def version(self) -> str:
        return "inert-test-rules-1"

    def scan(self, _path: Path, _sha256: str) -> list[Finding]:
        return [Finding(self.name, "synthetic-test-detection", 80)]


class YaraSuspicionEngine:
    name = "yara"

    def version(self) -> str:
        return "inert-test-rules-1"

    def scan(self, _path: Path, _sha256: str) -> list[Finding]:
        return [Finding(self.name, "synthetic-test-suspicion", 40)]


class MutatingYaraEngine:
    name = "yara"

    def __init__(self, original_path: Path) -> None:
        self.original_path = original_path

    def version(self) -> str:
        return "inert-mutation-fixture-1"

    def scan(self, _snapshot_path: Path, _sha256: str) -> list[Finding]:
        self.original_path.write_bytes(b"changed inert fixture")
        return [Finding(self.name, "synthetic-test-detection", 80)]


class SwapRestoreYaraEngine:
    name = "yara"

    def __init__(self, original_path: Path, original_bytes: bytes) -> None:
        self.original_path = original_path
        self.original_bytes = original_bytes
        self.clean_bytes = b"SAFE-DATA-123456"
        self.scanned_bytes = b""
        self.snapshot_path: Path | None = None
        self.snapshot_write_blocked = False
        self.snapshot_acl_sids: set[str] = set()
        self.snapshot_directory_acl_sids: set[str] = set()

    def version(self) -> str:
        return "inert-swap-restore-fixture-1"

    def scan(self, path: Path, _sha256: str) -> list[Finding]:
        self.snapshot_path = path
        metadata = self.original_path.stat()
        self.original_path.write_bytes(self.clean_bytes)
        os.utime(self.original_path, ns=(metadata.st_atime_ns, metadata.st_mtime_ns))
        self.scanned_bytes = path.read_bytes()
        self.original_path.write_bytes(self.original_bytes)
        os.utime(self.original_path, ns=(metadata.st_atime_ns, metadata.st_mtime_ns))

        if path != self.original_path:
            try:
                path.write_bytes(b"REPLACED-SNAPSHOT")
            except OSError:
                self.snapshot_write_blocked = True
            if os.name == "nt":
                win32security = importlib.import_module("win32security")
                for item_path, target_sids in (
                    (path, self.snapshot_acl_sids),
                    (path.parent, self.snapshot_directory_acl_sids),
                ):
                    descriptor = win32security.GetFileSecurity(
                        str(item_path), win32security.DACL_SECURITY_INFORMATION
                    )
                    acl = descriptor.GetSecurityDescriptorDacl()
                    target_sids.update(
                        win32security.ConvertSidToStringSid(acl.GetAce(index)[2])
                        for index in range(acl.GetAceCount())
                    )

        if self.scanned_bytes == self.original_bytes:
            return [Finding(self.name, "synthetic-test-detection", 80)]
        return [Finding(self.name, "no_detection", 0)]


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
        ((YaraSuspicionEngine(), ClamAVErrorEngine()), "suspicious"),
        ((UnavailableEngine("clamav"), UnavailableEngine("yara")), "unverified"),
    ],
    ids=("malicious-with-engine-error", "suspicious-with-engine-error", "no-authoritative-scanner"),
)
def test_terminal_tool_blocks_candidates_requiring_review(
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
    assert result.file_identity is not None
    assert "file_identity" not in projection


def test_suspicion_with_scanner_error_requires_review(tmp_path: Path) -> None:
    target = tmp_path / "inert-suspicion-fixture.bin"
    target.write_bytes(b"inert scanner fixture")
    service = SecurityService(
        SecurityStore(tmp_path / "security"),
        {"security": {"malware": {"auto_quarantine": False}}},
    )
    service.engines = (YaraSuspicionEngine(), ClamAVErrorEngine())

    result = service.scan_file(target, quarantine=False)
    projection = result.to_dict()

    assert result.verdict.value == "SUSPICIOUS"
    assert projection["file_verdict"] == "SUSPICIOUS"
    assert projection["engine_health"] == "DEGRADED"
    assert projection["execution_decision"] == "REVIEW"
    assert result.action == "blocked_pending_review"


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


def test_file_changed_during_scan_is_not_cached_or_recorded(tmp_path: Path) -> None:
    target = tmp_path / "inert-mutating-fixture.bin"
    target.write_bytes(b"original inert fixture")
    store = SecurityStore(tmp_path / "security")
    service = SecurityService(
        store,
        {"security": {"malware": {"auto_quarantine": True}}},
    )
    service.engines = (MutatingYaraEngine(target),)

    result = service.scan_file(target, quarantine=False)

    assert result.action == "blocked_pending_review"
    assert result.execution_decision.value == "REVIEW"
    assert result.file_verdict.value == "UNKNOWN"
    assert result.score == 0
    assert result.findings == ()
    assert result.error == "file_changed_during_scan"
    assert result.sha256 == ""
    assert result.to_dict()["error"] == "file_changed_during_scan"
    with store.connection() as connection:
        assert connection.execute("SELECT COUNT(*) FROM scan_results").fetchone()[0] == 0
    assert not (store.root / "quarantine").exists()
    assert not (store.root / "vault-key.dpapi").exists()


@pytest.mark.windows_only
def test_scanners_read_snapshot_bytes_when_original_is_swapped_and_restored(tmp_path: Path) -> None:
    target = tmp_path / "inert-swap-restore-fixture.bin"
    original_bytes = b"EVIL-DATA-123456"
    target.write_bytes(original_bytes)
    store = SecurityStore(tmp_path / "security")
    service = SecurityService(
        store,
        {"security": {"malware": {"auto_quarantine": False}}},
    )
    engine = SwapRestoreYaraEngine(target, original_bytes)
    service.engines = (engine,)

    result = service.scan_file(target, quarantine=False, use_cache=False)

    assert result.execution_decision.value == "BLOCK"
    assert result.verdict.value == "MALICIOUS"
    assert engine.scanned_bytes == original_bytes
    assert target.read_bytes() == original_bytes
    assert engine.snapshot_path is not None
    assert engine.snapshot_path != target
    assert engine.snapshot_write_blocked is True
    assert engine.snapshot_acl_sids
    assert engine.snapshot_directory_acl_sids
    descriptor = importlib.import_module("win32security")
    owner_name = importlib.import_module("win32api").GetUserNameEx(2)
    owner_sid, _, _ = descriptor.LookupAccountName(None, owner_name)
    system_sid = descriptor.CreateWellKnownSid(descriptor.WinLocalSystemSid, None)
    assert engine.snapshot_acl_sids == {
        descriptor.ConvertSidToStringSid(owner_sid),
        descriptor.ConvertSidToStringSid(system_sid),
    }
    assert engine.snapshot_directory_acl_sids == engine.snapshot_acl_sids
    assert not engine.snapshot_path.exists()


def test_snapshot_scan_preserves_original_path_heuristics(tmp_path: Path) -> None:
    download = tmp_path / "Downloads"
    download.mkdir()
    target = download / "inert-heuristic-fixture.ps1"
    target.write_text("Write-Output 'inert fixture'\n", encoding="utf-8")
    service = SecurityService(
        SecurityStore(tmp_path / "security"),
        {"security": {"malware": {"auto_quarantine": False}}},
    )
    service.engines = (StaticHeuristicsEngine(),)

    result = service.scan_file(target, quarantine=False, use_cache=False)

    assert any(
        finding.name == "executable_in_transient_location"
        for finding in result.findings
    )


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


@pytest.mark.parametrize("mutation", ["change", "replace", "remove"])
def test_terminal_revalidates_candidate_before_execution(
    monkeypatch,
    tmp_path: Path,
    mutation: str,
) -> None:
    target = tmp_path / "inert-preflight-fixture.ps1"
    original = b"Write-Output 'inert fixture'\n"
    target.write_bytes(original)
    service = SecurityService(
        SecurityStore(tmp_path / "security"),
        {"security": {"malware": {"auto_quarantine": False}}},
    )
    service.engines = (CleanEngine(),)

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
    executed = Mock(return_value={"output": "ran"})

    def create_environment(**_kwargs):
        if mutation == "change":
            target.write_bytes(b"changed inert fixture")
        elif mutation == "replace":
            replacement = tmp_path / "replacement.ps1"
            replacement.write_bytes(original)
            os.replace(replacement, target)
        else:
            target.unlink()
        return SimpleNamespace(execute=executed)

    monkeypatch.setattr(terminal, "_create_environment", Mock(side_effect=create_environment))

    response = terminal.terminal_tool(f'pwsh -File "{target}"', workdir=str(tmp_path))

    assert executed.call_count == 0
    assert "Security Center" in json.loads(response)["error"]


def test_terminal_security_preflight_uses_explicit_workdir(
    monkeypatch,
    tmp_path: Path,
) -> None:
    default_cwd = tmp_path / "default-cwd"
    workdir = tmp_path / "explicit-workdir"
    default_cwd.mkdir()
    workdir.mkdir()
    target = workdir / "inert-workdir-fixture.ps1"
    target.write_text("Write-Output 'inert fixture'\n", encoding="utf-8")
    service = SecurityService(
        SecurityStore(tmp_path / "security"),
        {"security": {"malware": {"auto_quarantine": False}}},
    )
    service.engines = (YaraDetectionEngine(),)

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
            "cwd": str(default_cwd),
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
    executor = Mock(return_value=SimpleNamespace(execute=Mock(return_value={"output": "ran"})))
    monkeypatch.setattr(terminal, "_create_environment", executor)

    response = terminal.terminal_tool(f'pwsh -File "{target.name}"', workdir=str(workdir))

    executor.assert_not_called()
    assert "Security Center blocked a malicious execution candidate" in json.loads(response)["error"]


@pytest.mark.parametrize("include_resolved_candidate", [False, True])
def test_terminal_blocks_unresolved_script_candidates(
    monkeypatch,
    tmp_path: Path,
    include_resolved_candidate: bool,
) -> None:
    unresolved = tmp_path / "missing-inert-fixture.ps1"
    resolved = tmp_path / "clean-inert-fixture.ps1"
    resolved.write_text("Write-Output 'inert fixture'\n", encoding="utf-8")
    service = SecurityService(
        SecurityStore(tmp_path / "security"),
        {"security": {"malware": {"auto_quarantine": False}}},
    )
    service.engines = (CleanEngine(),)

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
    executor = Mock(return_value=SimpleNamespace(execute=Mock(return_value={"output": "ran"})))
    monkeypatch.setattr(terminal, "_create_environment", executor)
    candidates = [f'"{resolved}"'] if include_resolved_candidate else []
    candidates.append(f'"{unresolved}"')
    command = "pwsh -File " + " ".join(candidates)

    response = terminal.terminal_tool(command, workdir=str(tmp_path))

    executor.assert_not_called()
    assert "Security Center" in json.loads(response)["error"]


def test_execution_gate_fails_closed_on_parse_and_path_errors(monkeypatch, tmp_path: Path) -> None:
    execution_gate = importlib.import_module("downstream.security.execution_gate")
    monkeypatch.setattr(
        execution_gate,
        "load_config",
        lambda: {"security": {"malware": {"enabled": True, "execution_gate": True}}},
    )

    def invalid_parse(_command: str) -> list[str]:
        raise ValueError("invalid command")

    monkeypatch.setattr(execution_gate, "split_command_line", invalid_parse)
    parse_failure = execution_gate.preflight_command("pwsh -File script.ps1", str(tmp_path))
    assert parse_failure["allowed"] is False
    assert parse_failure["blocked"][0]["error"] == "candidate_parse_failed"
    assert not execution_gate.revalidate_command("pwsh -File script.ps1", str(tmp_path), {})

    monkeypatch.undo()
    monkeypatch.setattr(
        execution_gate,
        "load_config",
        lambda: {"security": {"malware": {"enabled": True, "execution_gate": True}}},
    )
    nul_path = execution_gate.preflight_command('pwsh -File "invalid\x00.ps1"', str(tmp_path))
    assert nul_path["allowed"] is False
    assert nul_path["blocked"][0]["error"] == "candidate_unresolved"


@pytest.mark.parametrize(
    ("command", "reason"),
    [
        (
            "pwsh -File " + " ".join(f"missing-{index}.ps1" for index in range(40)),
            "candidate_limit_exceeded",
        ),
        ('pwsh -File "' + ("a" * 3000) + '.ps1"', "candidate_reference_too_long"),
        (
            "pwsh -File missing-first.ps1 -File missing-second.ps1",
            "candidate_unresolved",
        ),
    ],
)
def test_execution_gate_bounds_candidate_refusals(
    monkeypatch,
    tmp_path: Path,
    command: str,
    reason: str,
) -> None:
    execution_gate = importlib.import_module("downstream.security.execution_gate")
    monkeypatch.setattr(
        execution_gate,
        "load_config",
        lambda: {"security": {"malware": {"enabled": True, "execution_gate": True}}},
    )

    result = execution_gate.preflight_command(command, str(tmp_path))
    serialized = json.dumps(result)

    assert result["allowed"] is False
    assert len(result["blocked"]) == 1
    assert result["blocked"][0]["error"] == reason
    assert result["blocked"][0]["path"] == "execution candidate unavailable"
    assert len(result["blocked"][0]["path"]) <= 256
    assert "missing-first.ps1" not in serialized
    assert ("a" * 300) not in serialized


def test_public_scan_path_is_bounded() -> None:
    result = ScanResult(
        "C:/sensitive/" + ("x" * 3000) + ".ps1",
        "a" * 64,
        4,
        Verdict.CLEAN,
        0,
        "allow",
        (),
        {},
    )

    assert len(result.to_dict()["path"]) <= 256


def test_public_scan_projection_bounds_findings_and_reports_truncation() -> None:
    result = ScanResult(
        "inert-many-findings.bin",
        "a" * 64,
        4,
        Verdict.SUSPICIOUS,
        40,
        "warn",
        tuple(Finding("yara", f"synthetic-finding-{index}", 1) for index in range(100)),
        {},
    )

    projection = result.to_dict()

    assert len(projection["findings"]) == 64
    assert projection["finding_count"] == 100
    assert projection["findings_truncated"] is True


def test_execution_gate_resolves_attached_script_switch_values(tmp_path: Path) -> None:
    script = tmp_path / "inert-attached-fixture.ps1"
    script.write_text("Write-Output 'inert fixture'\n", encoding="utf-8")
    execution_gate = importlib.import_module("downstream.security.execution_gate")

    assert execution_gate._candidates(f"pwsh -File={script.name}", tmp_path) == [script]


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
