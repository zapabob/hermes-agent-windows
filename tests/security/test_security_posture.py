from __future__ import annotations

import json

from downstream.security import posture
from downstream.security.posture import build_posture_report, run_posture_audit, write_posture_report


def test_posture_report_flags_ambient_authority_without_optional_runtime_requirements() -> None:
    config = {
        "approvals": {"mode": "off", "unattended_mode": "allow"},
        "browser": {
            "allow_private_urls": True,
            "auto_local_for_private_urls": True,
            "use_real_profile": True,
        },
        "security": {
            "allow_private_urls": True,
            "malware": {"execution_gate": False},
        },
        "gateway": {"api_server": {"host": "0.0.0.0", "port": 8642}},
        "model": {"api_key": "must-not-leak"},
    }

    report = build_posture_report(
        config=config,
        security_status={},
        host_evidence={},
        supply_chain={},
        generated_at="2026-11-01T00:00:00+00:00",
    )

    failed = {check["id"] for check in report["checks"] if check["status"] == "fail"}
    assert {
        "approvals.interactive",
        "approvals.unattended",
        "browser.auto_local_private",
        "browser.private_urls",
        "browser.real_profile",
        "tools.private_urls",
        "gateway.api_bind",
        "malware.execution_gate",
    } <= failed
    assert report["overall"] == "critical"
    assert "ARTEX" not in json.dumps(report)
    assert "Docker" not in json.dumps(report)
    assert "must-not-leak" not in json.dumps(report)


def test_posture_report_separates_runtime_health_supply_chain_and_listener_review() -> None:
    report = build_posture_report(
        config={
            "approvals": {"mode": "smart", "unattended_mode": "deny"},
            "browser": {"allow_private_urls": False, "use_real_profile": False},
            "security": {"allow_private_urls": False, "malware": {"execution_gate": True}},
            "gateway": {"api_server": {"host": "127.0.0.1", "port": 8642}},
        },
        security_status={
            "enabled": True,
            "engines": {"clamav": "database-1", "yara": "rules-1"},
            "watch": {"enabled": True, "running": False, "pid": None},
        },
        host_evidence={
            "platform": "win32",
            "defender": {
                "status": "running",
                "antivirus_enabled": True,
                "realtime_enabled": True,
                "signature_age_hours": 4,
            },
            "firewall": {
                "profiles": {
                    "Domain": {"enabled": True, "default_inbound_action": "block"},
                    "Private": {"enabled": True, "default_inbound_action": "block"},
                    "Public": {"enabled": True, "default_inbound_action": "block"},
                }
            },
            "disk": {"free_bytes": 20 * 1024**3},
            "listeners": {
                "loopback": 8,
                "network": 2,
                "api_addresses": ["127.0.0.1"],
                "api_owner_verified": True,
            },
        },
        supply_chain={
            "status": "ok",
            "total_components_scanned": 12,
            "finding_count": 1,
            "findings": [
                {
                    "package": "fixture",
                    "version": "1.0",
                    "source": "venv",
                    "vuln_id": "GHSA-test",
                    "severity": "HIGH",
                    "fixed_versions": ["1.1"],
                }
            ],
        },
        generated_at="2026-11-01T00:00:00+00:00",
    )

    checks = {check["id"]: check for check in report["checks"]}
    assert checks["malware.watcher"]["status"] == "fail"
    assert checks["host.defender"]["status"] == "pass"
    assert checks["host.firewall"]["status"] == "pass"
    assert checks["gateway.live_bind"]["status"] == "pass"
    assert checks["host.network_listeners"]["status"] == "review"
    assert checks["supply_chain.known_vulnerabilities"]["status"] == "fail"
    assert report["supply_chain"]["severity_counts"] == {"HIGH": 1}
    assert report["overall"] == "high_risk"


def test_posture_audit_uses_bounded_collectors_and_returns_sanitized_evidence() -> None:
    report = run_posture_audit(
        config={"gateway": {"api_server": {"host": "127.0.0.1", "port": 8642}}},
        security_status={"engines": {}, "watch": {}},
        host_collector=lambda _config: {
            "platform": "win32",
            "defender": {
                "status": "running",
                "antivirus_enabled": True,
                "realtime_enabled": True,
                "signature_age_hours": 1,
                "raw_secret": "hidden",
            },
            "firewall": {"profiles": {"Public": {"enabled": True, "default_inbound_action": "block"}}},
            "disk": {"free_bytes": 20 * 1024**3},
            "listeners": {
                "loopback": 1,
                "network": 0,
                "api_addresses": ["127.0.0.1"],
                "api_owner_verified": True,
                "records": [
                    {
                        "address": "127.0.0.1",
                        "port": 8642,
                        "pid": 42,
                        "process_name": "python.exe",
                        "exposure": "loopback",
                        "raw_secret": "listener-hidden",
                    }
                ],
            },
        },
        supply_chain_collector=lambda: {
            "status": "ok",
            "total_components_scanned": 1,
            "findings": [],
        },
        generated_at="2026-11-01T00:00:00+00:00",
    )

    assert report["generated_at"] == "2026-11-01T00:00:00+00:00"
    assert report["host"]["listeners"] == {
        "api_addresses": ["127.0.0.1"],
        "api_owner_verified": True,
        "loopback": 1,
        "network": 0,
        "records": [
            {
                "address": "127.0.0.1",
                "port": 8642,
                "pid": 42,
                "process_name": "python.exe",
                "exposure": "loopback",
            }
        ],
    }
    assert "raw_secret" not in json.dumps(report)
    assert "listener-hidden" not in json.dumps(report)


def test_posture_requires_effective_defender_firewall_and_api_owner_controls() -> None:
    report = build_posture_report(
        config={"gateway": {"api_server": {"host": "127.0.0.1", "port": 8642}}},
        security_status={
            "engines": {"clamav": "database-1"},
            "watch": {"enabled": True, "running": True},
        },
        host_evidence={
            "platform": "win32",
            "defender": {
                "status": "running",
                "antivirus_enabled": False,
                "realtime_enabled": False,
                "signature_age_hours": 1,
            },
            "firewall": {
                "profiles": {
                    "Public": {"enabled": True, "default_inbound_action": "allow"},
                }
            },
            "disk": {"free_bytes": 20 * 1024**3},
            "listeners": {
                "loopback": 1,
                "network": 0,
                "api_addresses": ["127.0.0.1"],
                "api_owner_verified": False,
            },
        },
        supply_chain={"status": "ok", "total_components_scanned": 1, "findings": []},
        generated_at="2026-11-01T00:00:00+00:00",
    )

    checks = {check["id"]: check for check in report["checks"]}
    assert checks["host.defender"]["status"] == "fail"
    assert checks["host.firewall"]["status"] == "fail"
    assert checks["gateway.live_bind"]["status"] == "fail"


def test_firewall_collector_reads_the_effective_active_policy(monkeypatch) -> None:
    scripts: list[str] = []

    def _collect(script: str):
        scripts.append(script)
        return [
            {"Name": "Domain", "Enabled": True, "DefaultInboundAction": "Block"},
            {"Name": "Private", "Enabled": True, "DefaultInboundAction": "Block"},
            {"Name": "Public", "Enabled": True, "DefaultInboundAction": "Block"},
        ]

    monkeypatch.setattr(posture, "_run_powershell_json", _collect)

    result = posture._collect_windows_firewall()

    assert "-PolicyStore ActiveStore" in scripts[0]
    assert result["profiles"]["Public"] == {
        "enabled": True,
        "default_inbound_action": "block",
    }


def test_supply_chain_counts_all_findings_and_never_treats_unknown_as_pass() -> None:
    findings = [
        {
            "package": f"fixture-{index}",
            "version": "1.0",
            "source": "venv",
            "vuln_id": f"OSV-{index}",
            "severity": "HIGH" if index < 70 else "UNKNOWN",
            "fixed_versions": [],
        }
        for index in range(71)
    ]
    report = build_posture_report(
        config={},
        security_status={},
        host_evidence={},
        supply_chain={
            "status": "ok",
            "total_components_scanned": 80,
            "findings": findings,
        },
        generated_at="2026-11-01T00:00:00+00:00",
    )

    assert report["supply_chain"]["severity_counts"] == {"HIGH": 70, "UNKNOWN": 1}
    assert len(report["supply_chain"]["findings"]) == 64
    assert report["supply_chain"]["findings_truncated"] is True

    unknown_only = build_posture_report(
        config={},
        security_status={},
        host_evidence={},
        supply_chain={
            "status": "ok",
            "total_components_scanned": 1,
            "findings": [findings[-1]],
        },
        generated_at="2026-11-01T00:00:00+00:00",
    )
    check = next(
        item
        for item in unknown_only["checks"]
        if item["id"] == "supply_chain.known_vulnerabilities"
    )
    assert check["status"] == "review"


def test_watcher_failure_exposes_a_bounded_reason_code_without_raw_error_text() -> None:
    report = build_posture_report(
        config={},
        security_status={
            "engines": {"clamav": "database-1"},
            "watch": {
                "enabled": True,
                "running": False,
                "error": "watcher did not report ready within 5 seconds; token=must-not-leak",
            },
        },
        host_evidence={},
        supply_chain={"status": "unavailable", "findings": []},
        generated_at="2026-11-01T00:00:00+00:00",
    )

    check = next(item for item in report["checks"] if item["id"] == "malware.watcher")
    assert check["observed"] == {
        "enabled": True,
        "running": False,
        "error_code": "watcher_ready_timeout",
    }
    assert "must-not-leak" not in json.dumps(report)


def test_posture_report_writer_persists_machine_evidence_and_bounded_markdown(tmp_path) -> None:
    report = {
        "schema": "hermes-security-posture-v1",
        "generated_at": "2026-11-01T00:00:00+00:00",
        "overall": "high_risk",
        "counts": {"fail": 1},
        "checks": [
            {
                "id": "approvals.interactive",
                "status": "fail",
                "severity": "high",
                "observed": "off",
                "expected": "smart",
            }
        ],
        "host": {},
        "supply_chain": {"finding_count": 0},
    }

    written = write_posture_report(report, tmp_path, run_id="20261101-000000")

    assert json.loads(written["evidence"].read_text(encoding="utf-8")) == report
    markdown = written["report"].read_text(encoding="utf-8")
    assert "Hermes Windows Blue-Team Exercise" in markdown
    assert "approvals.interactive" in markdown
    assert "HIGH" in markdown
