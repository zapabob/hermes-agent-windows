from __future__ import annotations

from collections.abc import Callable, Mapping
import datetime as dt
import ipaddress
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
from typing import Any

import psutil


_SEVERITY_RANK = {
    "info": 0,
    "low": 1,
    "medium": 2,
    "high": 3,
    "critical": 4,
}


def _mapping(value: object) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _nested(config: Mapping[str, Any], *path: str, default: object = None) -> object:
    current: object = config
    for part in path:
        current = _mapping(current).get(part, default)
    return current


def _check(
    check_id: str,
    *,
    passed: bool,
    severity: str,
    observed: object,
    expected: object,
) -> dict[str, object]:
    return {
        "id": check_id,
        "status": "pass" if passed else "fail",
        "severity": "info" if passed else severity,
        "observed": observed,
        "expected": expected,
    }


def _state_check(
    check_id: str,
    *,
    status: str,
    severity: str,
    observed: object,
    expected: object,
) -> dict[str, object]:
    return {
        "id": check_id,
        "status": status,
        "severity": "info" if status == "pass" else severity,
        "observed": observed,
        "expected": expected,
    }


def _configuration_checks(config: Mapping[str, Any]) -> list[dict[str, object]]:
    approvals_mode = str(_nested(config, "approvals", "mode", default="smart") or "smart").lower()
    unattended_mode = str(_nested(config, "approvals", "unattended_mode", default="deny") or "deny").lower()
    browser_private = _nested(config, "browser", "allow_private_urls", default=False) is True
    auto_local_private = _nested(config, "browser", "auto_local_for_private_urls", default=True) is True
    tool_private = _nested(config, "security", "allow_private_urls", default=False) is True
    real_profile = _nested(config, "browser", "use_real_profile", default=False) is True
    execution_gate = _nested(config, "security", "malware", "execution_gate", default=True) is not False
    api_host = str(_nested(config, "gateway", "api_server", "host", default="127.0.0.1") or "127.0.0.1").lower()
    loopback_hosts = {"127.0.0.1", "::1", "localhost"}

    return [
        _check(
            "approvals.interactive",
            passed=approvals_mode != "off",
            severity="high",
            observed=approvals_mode,
            expected="smart",
        ),
        _check(
            "approvals.unattended",
            passed=unattended_mode == "deny",
            severity="critical",
            observed=unattended_mode,
            expected="deny",
        ),
        _check(
            "browser.private_urls",
            passed=not browser_private,
            severity="high",
            observed=browser_private,
            expected=False,
        ),
        _check(
            "browser.auto_local_private",
            passed=not auto_local_private,
            severity="high",
            observed=auto_local_private,
            expected=False,
        ),
        _check(
            "browser.real_profile",
            passed=not real_profile,
            severity="high",
            observed=real_profile,
            expected=False,
        ),
        _check(
            "tools.private_urls",
            passed=not tool_private,
            severity="high",
            observed=tool_private,
            expected=False,
        ),
        _check(
            "gateway.api_bind",
            passed=api_host in loopback_hosts,
            severity="high",
            observed=api_host,
            expected="loopback",
        ),
        _check(
            "malware.execution_gate",
            passed=execution_gate,
            severity="high",
            observed=execution_gate,
            expected=True,
        ),
    ]


def _is_loopback(value: object) -> bool:
    if not isinstance(value, str):
        return False
    try:
        return ipaddress.ip_address(value.split("%", 1)[0]).is_loopback
    except ValueError:
        return value.lower() == "localhost"


def _watch_error_code(value: object) -> str | None:
    if not isinstance(value, str) or not value.strip():
        return None
    lowered = value.lower()
    if "did not report ready" in lowered:
        return "watcher_ready_timeout"
    if "cleanup failed" in lowered:
        return "watcher_cleanup_failed"
    if "still stopping" in lowered:
        return "watcher_stopping"
    if "lock" in lowered:
        return "watcher_lock_error"
    return "watcher_error"


def _runtime_checks(
    security_status: Mapping[str, Any],
    host_evidence: Mapping[str, Any],
) -> list[dict[str, object]]:
    checks: list[dict[str, object]] = []
    watch = _mapping(security_status.get("watch"))
    if watch:
        enabled = watch.get("enabled") is True
        running = watch.get("running") is True
        observed: dict[str, object] = {"enabled": enabled, "running": running}
        error_code = _watch_error_code(watch.get("error"))
        if error_code is not None:
            observed["error_code"] = error_code
        checks.append(
            _state_check(
                "malware.watcher",
                status="pass" if enabled and running else "fail" if enabled else "warn",
                severity="high" if enabled else "medium",
                observed=observed,
                expected={"enabled": True, "running": True},
            )
        )
    else:
        checks.append(
            _state_check(
                "malware.watcher",
                status="unavailable",
                severity="medium",
                observed="unavailable",
                expected={"enabled": True, "running": True},
            )
        )

    engines = _mapping(security_status.get("engines"))
    authoritative = [str(engines.get(name, "")) for name in ("clamav", "yara")]
    unhealthy_markers = ("unavailable", "error", "timeout", "stale")
    engine_ready = any(version and not any(marker in version.lower() for marker in unhealthy_markers) for version in authoritative)
    checks.append(
        _state_check(
            "malware.authoritative_scanner",
            status="pass" if engine_ready else "fail" if engines else "unavailable",
            severity="high",
            observed={"available": engine_ready},
            expected={"available": True},
        )
    )

    defender = _mapping(host_evidence.get("defender"))
    defender_status = str(defender.get("status", "unavailable")).lower()
    antivirus_enabled = defender.get("antivirus_enabled") is True
    realtime_enabled = defender.get("realtime_enabled") is True
    signature_age = defender.get("signature_age_hours")
    signature_fresh = isinstance(signature_age, (int, float)) and not isinstance(signature_age, bool) and 0 <= signature_age <= 72
    defender_available = (
        defender_status != "unavailable"
        and isinstance(defender.get("antivirus_enabled"), bool)
        and isinstance(defender.get("realtime_enabled"), bool)
        and isinstance(signature_age, (int, float))
        and not isinstance(signature_age, bool)
    )
    defender_ok = defender_status == "running" and antivirus_enabled and realtime_enabled and signature_fresh
    checks.append(
        _state_check(
            "host.defender",
            status="pass" if defender_ok else "fail" if defender_available else "unavailable",
            severity="critical",
            observed={
                "service": defender_status,
                "antivirus_enabled": antivirus_enabled,
                "realtime_enabled": realtime_enabled,
                "signature_age_hours": signature_age if isinstance(signature_age, (int, float)) else None,
            },
            expected={"service": "running", "antivirus_enabled": True, "realtime_enabled": True, "max_signature_age_hours": 72},
        )
    )

    firewall_profiles = _mapping(_mapping(host_evidence.get("firewall")).get("profiles"))
    firewall_rows = [_mapping(value) for value in firewall_profiles.values()]
    firewall_available = bool(firewall_rows) and all(
        isinstance(row.get("enabled"), bool) and isinstance(row.get("default_inbound_action"), str)
        for row in firewall_rows
    )
    firewall_enabled = firewall_available and all(
        row.get("enabled") is True and str(row.get("default_inbound_action", "")).lower() == "block"
        for row in firewall_rows
    )
    checks.append(
        _state_check(
            "host.firewall",
            status="pass" if firewall_enabled else "fail" if firewall_available else "unavailable",
            severity="high",
            observed={
                str(name)[:32]: {
                    "enabled": _mapping(value).get("enabled") is True,
                    "default_inbound_action": str(_mapping(value).get("default_inbound_action", "unknown"))[:16],
                }
                for name, value in list(firewall_profiles.items())[:8]
            },
            expected={"enabled": True, "default_inbound_action": "block"},
        )
    )

    disk = _mapping(host_evidence.get("disk"))
    free_bytes = disk.get("free_bytes")
    disk_available = isinstance(free_bytes, int) and not isinstance(free_bytes, bool)
    disk_ok = disk_available and free_bytes >= 10 * 1024**3
    checks.append(
        _state_check(
            "host.system_disk",
            status="pass" if disk_ok else "fail" if disk_available else "unavailable",
            severity="high",
            observed=free_bytes if disk_available else "unavailable",
            expected={"minimum_free_bytes": 10 * 1024**3},
        )
    )

    listeners = _mapping(host_evidence.get("listeners"))
    network_count = listeners.get("network")
    listeners_available = isinstance(network_count, int) and not isinstance(network_count, bool)
    checks.append(
        _state_check(
            "host.network_listeners",
            status="pass" if listeners_available and network_count == 0 else "review" if listeners_available else "unavailable",
            severity="info",
            observed=network_count if listeners_available else "unavailable",
            expected=0,
        )
    )

    api_addresses = listeners.get("api_addresses")
    addresses = [value for value in api_addresses if isinstance(value, str)] if isinstance(api_addresses, list) else []
    owner_verified = listeners.get("api_owner_verified")
    live_bind_ok = bool(addresses) and all(_is_loopback(value) for value in addresses) and owner_verified is True
    checks.append(
        _state_check(
            "gateway.live_bind",
            status="pass" if live_bind_ok else "fail" if addresses and owner_verified is False else "review" if addresses else "unavailable",
            severity="high",
            observed={"addresses": addresses[:8], "owner_verified": owner_verified} if addresses else "unavailable",
            expected={"address": "loopback", "owner_verified": True},
        )
    )
    return checks


def _supply_chain_projection(supply_chain: Mapping[str, Any]) -> tuple[dict[str, object], dict[str, object]]:
    raw_findings = supply_chain.get("findings")
    findings = [item for item in raw_findings if isinstance(item, Mapping)] if isinstance(raw_findings, list) else []
    severity_counts: dict[str, int] = {}
    projected: list[dict[str, object]] = []
    allowed = ("package", "version", "source", "vuln_id", "severity", "fixed_versions")
    for index, item in enumerate(findings):
        severity = str(item.get("severity", "UNKNOWN")).upper()
        severity_counts[severity] = severity_counts.get(severity, 0) + 1
        if index < 64:
            projected.append({key: item[key] for key in allowed if key in item})

    total = supply_chain.get("total_components_scanned")
    payload: dict[str, object] = {
        "total_components_scanned": total if isinstance(total, int) and not isinstance(total, bool) else 0,
        "finding_count": len(findings),
        "severity_counts": severity_counts,
        "findings": projected,
        "findings_truncated": len(findings) > len(projected),
    }
    audit_status = supply_chain.get("status")
    if audit_status != "ok":
        return payload, _state_check(
            "supply_chain.known_vulnerabilities",
            status="unavailable",
            severity="medium",
            observed="unavailable",
            expected=0,
        )

    critical = severity_counts.get("CRITICAL", 0)
    high = severity_counts.get("HIGH", 0)
    moderate = severity_counts.get("MODERATE", 0) + severity_counts.get("MEDIUM", 0)
    unknown = severity_counts.get("UNKNOWN", 0)
    low = severity_counts.get("LOW", 0)
    total_components = payload["total_components_scanned"]
    status = (
        "fail"
        if critical or high
        else "warn"
        if moderate
        else "review"
        if unknown or low or total_components == 0
        else "pass"
    )
    severity = "critical" if critical else "high" if high else "medium" if moderate or unknown else "low" if low else "info"
    return payload, _state_check(
        "supply_chain.known_vulnerabilities",
        status=status,
        severity=severity,
        observed={"critical": critical, "high": high, "moderate": moderate, "low": low, "unknown": unknown},
        expected=0,
    )


def _host_projection(host_evidence: Mapping[str, Any]) -> dict[str, object]:
    defender = _mapping(host_evidence.get("defender"))
    firewall = _mapping(host_evidence.get("firewall"))
    disk = _mapping(host_evidence.get("disk"))
    listeners = _mapping(host_evidence.get("listeners"))
    profiles = _mapping(firewall.get("profiles"))
    addresses = listeners.get("api_addresses")
    listener_records = listeners.get("records")
    projected_records: list[dict[str, object]] = []
    if isinstance(listener_records, list):
        for value in listener_records[:64]:
            record = _mapping(value)
            address = record.get("address")
            port = record.get("port")
            exposure = record.get("exposure")
            process_name = record.get("process_name")
            pid = record.get("pid")
            if (
                not isinstance(address, str)
                or type(port) is not int
                or not 0 < port <= 65535
                or exposure not in {"loopback", "network"}
                or not isinstance(process_name, str)
                or (pid is not None and (type(pid) is not int or pid <= 0))
            ):
                continue
            projected_records.append(
                {
                    "address": address[:64],
                    "port": port,
                    "pid": pid,
                    "process_name": process_name[:80],
                    "exposure": exposure,
                }
            )
    return {
        "platform": str(host_evidence.get("platform", "unknown"))[:32],
        "defender": {
            "status": str(defender.get("status", "unavailable"))[:32],
            "antivirus_enabled": defender.get("antivirus_enabled") if isinstance(defender.get("antivirus_enabled"), bool) else None,
            "realtime_enabled": defender.get("realtime_enabled") if isinstance(defender.get("realtime_enabled"), bool) else None,
            "signature_age_hours": defender.get("signature_age_hours")
            if isinstance(defender.get("signature_age_hours"), (int, float))
            and not isinstance(defender.get("signature_age_hours"), bool)
            else None,
        },
        "firewall": {
            "profiles": {
                str(name)[:32]: {
                    "enabled": _mapping(value).get("enabled") is True,
                    "default_inbound_action": str(_mapping(value).get("default_inbound_action", "unknown"))[:16],
                }
                for name, value in list(profiles.items())[:8]
            }
        },
        "disk": {
            "free_bytes": disk.get("free_bytes")
            if isinstance(disk.get("free_bytes"), int) and not isinstance(disk.get("free_bytes"), bool)
            else None
        },
        "listeners": {
            "api_addresses": [value for value in addresses[:8] if isinstance(value, str)]
            if isinstance(addresses, list)
            else [],
            "api_owner_verified": listeners.get("api_owner_verified")
            if isinstance(listeners.get("api_owner_verified"), bool)
            else None,
            "loopback": listeners.get("loopback") if type(listeners.get("loopback")) is int else None,
            "network": listeners.get("network") if type(listeners.get("network")) is int else None,
            "records": projected_records,
        },
    }


def _run_powershell_json(script: str) -> object | None:
    shell = shutil.which("powershell.exe") or shutil.which("pwsh.exe")
    if not shell:
        return None
    try:
        completed = subprocess.run(
            [shell, "-NoLogo", "-NoProfile", "-NonInteractive", "-Command", script],
            capture_output=True,
            check=False,
            encoding="utf-8",
            errors="replace",
            timeout=15,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    if completed.returncode != 0 or not completed.stdout.strip():
        return None
    try:
        return json.loads(completed.stdout)
    except json.JSONDecodeError:
        return None


def _collect_windows_defender() -> dict[str, object]:
    try:
        service_status = str(psutil.win_service_get("WinDefend").status()).lower()
    except (AttributeError, OSError, psutil.Error):
        service_status = "unavailable"
    payload = _run_powershell_json(
        "$ErrorActionPreference='Stop';"
        "$s=Get-MpComputerStatus;"
        "$age=if($null -ne $s.AntivirusSignatureLastUpdated)"
        "{[math]::Round(((Get-Date)-$s.AntivirusSignatureLastUpdated).TotalHours,2)}else{$null};"
        "[pscustomobject]@{AntivirusEnabled=[bool]$s.AntivirusEnabled;"
        "RealTimeProtectionEnabled=[bool]$s.RealTimeProtectionEnabled;"
        "SignatureAgeHours=$age}|ConvertTo-Json -Compress"
    )
    if not isinstance(payload, Mapping):
        return {"status": service_status}
    signature_age = payload.get("SignatureAgeHours")
    return {
        "status": service_status,
        "antivirus_enabled": payload.get("AntivirusEnabled") if isinstance(payload.get("AntivirusEnabled"), bool) else None,
        "realtime_enabled": payload.get("RealTimeProtectionEnabled")
        if isinstance(payload.get("RealTimeProtectionEnabled"), bool)
        else None,
        "signature_age_hours": signature_age
        if isinstance(signature_age, (int, float)) and not isinstance(signature_age, bool)
        else None,
    }


def _collect_windows_firewall() -> dict[str, object]:
    payload = _run_powershell_json(
        "$ErrorActionPreference='Stop';"
        "@(Get-NetFirewallProfile -PolicyStore ActiveStore|ForEach-Object{[pscustomobject]@{Name=$_.Name;"
        "Enabled=[bool]$_.Enabled;DefaultInboundAction=$_.DefaultInboundAction.ToString()}})"
        "|ConvertTo-Json -Compress"
    )
    if payload is None:
        return {"profiles": {}}
    rows = payload if isinstance(payload, list) else [payload]
    profiles: dict[str, dict[str, object]] = {}
    for row in rows[:8]:
        if not isinstance(row, Mapping):
            continue
        name = row.get("Name")
        enabled = row.get("Enabled")
        inbound = row.get("DefaultInboundAction")
        if isinstance(name, str) and isinstance(enabled, bool) and isinstance(inbound, str):
            profiles[name[:32]] = {
                "enabled": enabled,
                "default_inbound_action": inbound.lower(),
            }
    return {"profiles": profiles}


def _listener_address(value: object) -> tuple[str, int] | None:
    if not value:
        return None
    address = getattr(value, "ip", None)
    port = getattr(value, "port", None)
    if address is None and isinstance(value, tuple) and len(value) >= 2:
        address, port = value[0], value[1]
    if not isinstance(address, str) or type(port) is not int:
        return None
    return address, port


def _process_name(pid: int | None) -> str:
    if type(pid) is not int or pid <= 0:
        return "unknown"
    try:
        return psutil.Process(pid).name()[:80]
    except (OSError, psutil.Error):
        return "unknown"


def _collect_listeners(api_port: int, expected_api_pid: int | None = None) -> dict[str, object]:
    loopback = 0
    network = 0
    api_addresses: set[str] = set()
    api_pids: set[int] = set()
    records: list[dict[str, object]] = []
    try:
        connections = psutil.net_connections(kind="tcp")
    except (OSError, psutil.Error):
        return {
            "loopback": None,
            "network": None,
            "api_addresses": [],
            "api_owner_verified": None,
            "records": [],
        }
    for connection in connections:
        if connection.status != psutil.CONN_LISTEN:
            continue
        local = _listener_address(connection.laddr)
        if local is None:
            continue
        address, port = local
        if _is_loopback(address):
            loopback += 1
            exposure = "loopback"
        else:
            network += 1
            exposure = "network"
        records.append(
            {
                "address": address[:64],
                "port": port,
                "pid": connection.pid if type(connection.pid) is int else None,
                "process_name": _process_name(connection.pid),
                "exposure": exposure,
            }
        )
        if port == api_port:
            api_addresses.add(address)
            if type(connection.pid) is int:
                api_pids.add(connection.pid)
    records.sort(key=lambda row: (row["port"] != api_port, row["exposure"] != "network", str(row["address"]), int(row["port"])))
    owner_verified = None
    if type(expected_api_pid) is int:
        owner_verified = bool(api_pids) and api_pids == {expected_api_pid}
    return {
        "loopback": loopback,
        "network": network,
        "api_addresses": sorted(api_addresses),
        "api_owner_verified": owner_verified,
        "records": records[:64],
    }


def collect_host_evidence(
    config: Mapping[str, Any],
    *,
    expected_api_pid: int | None = None,
) -> dict[str, object]:
    """Collect bounded host evidence without returning command output or secrets."""
    raw_port = _nested(config, "gateway", "api_server", "port", default=8642)
    api_port = raw_port if type(raw_port) is int and 0 < raw_port <= 65535 else 8642
    anchor = Path.home().anchor or f"{os.environ.get('SystemDrive', 'C:')}\\"
    try:
        free_bytes = shutil.disk_usage(anchor).free
    except OSError:
        free_bytes = None
    windows = sys.platform == "win32"
    return {
        "platform": sys.platform,
        "defender": _collect_windows_defender() if windows else {"status": "unavailable"},
        "firewall": _collect_windows_firewall() if windows else {"profiles": {}},
        "disk": {"free_bytes": free_bytes},
        "listeners": _collect_listeners(api_port, expected_api_pid),
    }


def collect_supply_chain_evidence() -> dict[str, object]:
    """Run the existing OSV audit and return its machine-readable projection."""
    try:
        from hermes_cli.security_audit import _discover_components, run_audit
        from hermes_constants import get_hermes_home

        home = Path(get_hermes_home())
        components = _discover_components(hermes_home=home)
        findings = run_audit(hermes_home=home, components=components)
    except (OSError, RuntimeError, ValueError):
        return {"status": "unavailable", "total_components_scanned": 0, "findings": []}
    return {
        "status": "ok",
        "total_components_scanned": len(components),
        "findings": [
            {
                "package": finding.component.name,
                "version": finding.component.version,
                "source": finding.component.source,
                "vuln_id": finding.vuln.osv_id,
                "severity": finding.vuln.severity,
                "fixed_versions": finding.vuln.fixed_versions[:8],
            }
            for finding in findings
        ],
    }


def _overall(checks: list[dict[str, object]]) -> str:
    failed = [
        str(check["severity"])
        for check in checks
        if check.get("status") == "fail"
    ]
    worst = max((_SEVERITY_RANK.get(severity, 0) for severity in failed), default=-1)
    if worst >= _SEVERITY_RANK["critical"]:
        return "critical"
    if worst >= _SEVERITY_RANK["high"]:
        return "high_risk"
    if worst >= 0 or any(check.get("status") in {"review", "unavailable", "warn"} for check in checks):
        return "attention"
    return "pass"


def build_posture_report(
    *,
    config: Mapping[str, Any],
    security_status: Mapping[str, Any],
    host_evidence: Mapping[str, Any],
    supply_chain: Mapping[str, Any],
    generated_at: str,
) -> dict[str, object]:
    """Build a bounded, secret-free security posture projection."""
    supply_projection, supply_check = _supply_chain_projection(supply_chain)
    checks = [
        *_configuration_checks(config),
        *_runtime_checks(security_status, host_evidence),
        supply_check,
    ]
    counts: dict[str, int] = {}
    for check in checks:
        status = str(check["status"])
        counts[status] = counts.get(status, 0) + 1
    return {
        "schema": "hermes-security-posture-v1",
        "generated_at": generated_at,
        "overall": _overall(checks),
        "counts": counts,
        "checks": checks,
        "host": _host_projection(host_evidence),
        "supply_chain": supply_projection,
    }


def run_posture_audit(
    *,
    config: Mapping[str, Any],
    security_status: Mapping[str, Any],
    host_collector: Callable[[Mapping[str, Any]], Mapping[str, Any]] = collect_host_evidence,
    supply_chain_collector: Callable[[], Mapping[str, Any]] = collect_supply_chain_evidence,
    include_supply_chain: bool = True,
    generated_at: str | None = None,
) -> dict[str, object]:
    """Collect local evidence and build a profile-scoped posture report."""
    try:
        host_evidence = host_collector(config)
    except (OSError, RuntimeError, ValueError):
        host_evidence = {"platform": sys.platform}
    if include_supply_chain:
        try:
            supply_chain = supply_chain_collector()
        except (OSError, RuntimeError, ValueError):
            supply_chain = {"status": "unavailable", "findings": []}
    else:
        supply_chain = {"status": "unavailable", "findings": []}
    timestamp = generated_at or dt.datetime.now(dt.timezone.utc).isoformat()
    return build_posture_report(
        config=config,
        security_status=security_status,
        host_evidence=host_evidence,
        supply_chain=supply_chain,
        generated_at=timestamp,
    )


def _write_utf8_atomic(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(f"{path.suffix}.tmp")
    temporary.write_text(content, encoding="utf-8")
    temporary.replace(path)


def _bounded_json(value: object, limit: int = 500) -> str:
    try:
        rendered = json.dumps(value, ensure_ascii=False, sort_keys=True)
    except (TypeError, ValueError):
        rendered = '"unavailable"'
    return rendered if len(rendered) <= limit else f"{rendered[: limit - 1]}…"


def write_posture_report(
    report: Mapping[str, Any],
    output_dir: Path,
    *,
    run_id: str | None = None,
) -> dict[str, Path]:
    """Persist one posture run as JSON evidence and a bounded Markdown view."""
    identifier = run_id or dt.datetime.now().astimezone().strftime("%Y%m%d-%H%M%S")
    evidence_path = output_dir / f"blue-team-{identifier}.json"
    report_path = output_dir / f"blue-team-{identifier}.md"
    _write_utf8_atomic(
        evidence_path,
        json.dumps(report, ensure_ascii=False, indent=2, default=str) + "\n",
    )

    lines = [
        "# Hermes Windows Blue-Team Exercise",
        "",
        f"- Run: `{identifier}`",
        f"- Evidence time: `{report.get('generated_at', 'unknown')}`",
        f"- Bounded posture: `{report.get('overall', 'unknown')}`",
        "- Scope: local machine only; read-only checks; no exploitation or automatic remediation",
        "",
        "## Checks",
    ]
    raw_checks = report.get("checks")
    checks = raw_checks if isinstance(raw_checks, list) else []
    if not checks:
        lines.append("- No checks were returned.")
    for item in checks:
        if not isinstance(item, Mapping):
            continue
        severity = str(item.get("severity", "info")).upper()[:16]
        status = str(item.get("status", "unknown")).upper()[:16]
        check_id = str(item.get("id", "unknown"))[:120]
        observed = _bounded_json(item.get("observed"))
        lines.append(f"- **{severity} / {status}** `{check_id}` — observed: `{observed}`")
    lines.extend(
        [
            "",
            "## Evidence",
            f"- Machine-readable evidence: `{evidence_path}`",
        ]
    )
    _write_utf8_atomic(report_path, "\n".join(lines) + "\n")
    return {"evidence": evidence_path, "report": report_path}
