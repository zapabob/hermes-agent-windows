from __future__ import annotations

import datetime as dt
import json
import logging
import os
import shutil
import subprocess
import sys
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

logging.basicConfig(level=logging.INFO, format="%(message)s")
LOG = logging.getLogger("hermes-blue-team")

ROOT = Path(r"C:\Users\downl\Documents\New project\hermes-agent")
OUTPUT = ROOT / "output" / "reports"


def run(command: list[str], timeout: int = 60) -> dict[str, Any]:
    try:
        result = subprocess.run(
            command,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
            check=False,
        )
        return {
            "ok": result.returncode == 0,
            "exit_code": result.returncode,
            "stdout": result.stdout.strip(),
            "stderr": result.stderr.strip(),
        }
    except (OSError, subprocess.TimeoutExpired) as exc:
        return {"ok": False, "exit_code": None, "stdout": "", "stderr": str(exc)}


def http_check(url: str) -> dict[str, Any]:
    try:
        with urllib.request.urlopen(url, timeout=5) as response:
            return {"ok": response.status == 200, "status": response.status}
    except (urllib.error.URLError, TimeoutError) as exc:
        return {"ok": False, "status": None, "error": str(exc)}


def config_value(key: str) -> str | None:
    result = run(["hermes", "config", "get", key], timeout=30)
    return result["stdout"] if result["ok"] else None


def config_enabled(key: str) -> bool:
    """Return whether a Hermes config value is explicitly truthy."""
    raw = config_value(key)
    return str(raw or "").strip().strip("'\"").lower() in {"true", "1", "yes", "on"}


def configuration_findings() -> list[dict[str, str]]:
    """Evaluate runtime settings that expand an agent's local attack surface."""
    findings: list[dict[str, str]] = []
    if config_enabled("browser.allow_private_urls"):
        findings.append(
            {
                "severity": "high",
                "control": "ssrf",
                "finding": "Browser private-URL access is globally enabled; injected content can reach local services.",
            }
        )
    if config_enabled("security.allow_private_urls"):
        findings.append(
            {
                "severity": "high",
                "control": "ssrf",
                "finding": "Tool private-URL access is globally enabled; use a bounded local route instead.",
            }
        )
    if config_enabled("browser.use_real_profile"):
        findings.append(
            {
                "severity": "high",
                "control": "browser-isolation",
                "finding": "Browser automation uses the real profile, exposing authenticated sessions to web content.",
            }
        )

    unattended = str(config_value("approvals.unattended_mode") or "deny").strip().strip("'\"").lower()
    if unattended != "deny":
        findings.append(
            {
                "severity": "critical",
                "control": "approvals",
                "finding": "Unattended approvals are not fail-closed (deny).",
            }
        )

    api_host = str(config_value("gateway.api_server.host") or "127.0.0.1").strip().strip("'\"").lower()
    if api_host not in {"127.0.0.1", "localhost", "::1"}:
        findings.append(
            {
                "severity": "high",
                "control": "api-exposure",
                "finding": f"Hermes API server is configured for a non-loopback host ({api_host}).",
            }
        )
    return findings


def parse_listeners(raw: str) -> list[dict[str, Any]]:
    listeners: list[dict[str, Any]] = []
    for line in raw.splitlines():
        fields = line.split()
        if len(fields) < 5 or fields[0].upper() != "TCP" or fields[3].upper() != "LISTENING":
            continue
        local = fields[1]
        address, _, port = local.rpartition(":")
        address = address.strip("[]")
        listeners.append(
            {
                "address": address,
                "port": int(port) if port.isdigit() else port,
                "pid": fields[4],
                "exposure": "loopback" if address in {"127.0.0.1", "::1"} else "network",
            }
        )
    return listeners


def main() -> int:
    now = dt.datetime.now().astimezone()
    run_id = now.strftime("%Y%m%d-%H%M%S")
    OUTPUT.mkdir(parents=True, exist_ok=True)

    netstat = run(["netstat.exe", "-ano", "-p", "tcp"], timeout=30)
    listeners = parse_listeners(netstat["stdout"])
    defender = run(["sc.exe", "query", "WinDefend"], timeout=30)
    firewall = run(["netsh.exe", "advfirewall", "show", "allprofiles"], timeout=30)
    docker_exe = shutil.which("docker")
    if not docker_exe:
        candidate = Path(r"H:\Hermes\DockerDesktop\resources\bin\docker.exe")
        docker_exe = str(candidate) if candidate.exists() else "docker"
    docker_status = run([docker_exe, "desktop", "status"], timeout=30)
    docker_ps = run([docker_exe, "ps", "--format", "{{.Names}}|{{.Status}}|{{.Ports}}"], timeout=30)
    supply_chain_raw = run(["hermes", "security", "audit", "--json"], timeout=300)
    try:
        supply_chain: Any = json.loads(supply_chain_raw["stdout"]) if supply_chain_raw["stdout"] else None
    except json.JSONDecodeError:
        supply_chain = {"parse_error": True, "stderr": supply_chain_raw["stderr"]}

    c_usage = shutil.disk_usage("C:\\")
    h_usage = shutil.disk_usage("H:\\")
    startup_shortcut = (
        Path(os.environ.get("APPDATA", ""))
        / "Microsoft"
        / "Windows"
        / "Start Menu"
        / "Programs"
        / "Startup"
        / "ARTEX-Auto.lnk"
    )

    report: dict[str, Any] = {
        "schema": "hermes-blue-team-local-v1",
        "run_id": run_id,
        "timestamp": now.isoformat(),
        "scope": "local-machine-only",
        "constraints": [
            "no remote scanning",
            "no exploitation",
            "no persistence changes during exercise",
            "no credential output",
        ],
        "integration": {
            "hermes_gateway": http_check("http://127.0.0.1:8642/health"),
            "artex": http_check("http://127.0.0.1:8790/api/health"),
            "hikari_backend": http_check("http://127.0.0.1:8080/health"),
            "model_provider": config_value("model.provider"),
            "model_preset": config_value("model.default"),
            "approvals_mode": config_value("approvals.mode"),
            "startup_shortcut_present": startup_shortcut.exists(),
        },
        "configuration": {
            "browser_allow_private_urls": config_enabled("browser.allow_private_urls"),
            "tool_allow_private_urls": config_enabled("security.allow_private_urls"),
            "browser_use_real_profile": config_enabled("browser.use_real_profile"),
            "unattended_mode": config_value("approvals.unattended_mode"),
            "api_server_host": config_value("gateway.api_server.host") or "127.0.0.1",
        },
        "endpoint_protection": {
            "windefend_service_query": defender,
        },
        "firewall": firewall,
        "tcp_listeners": listeners,
        "docker": {"desktop": docker_status, "containers": docker_ps},
        "disk": {
            "C": {"total": c_usage.total, "used": c_usage.used, "free": c_usage.free},
            "H": {"total": h_usage.total, "used": h_usage.used, "free": h_usage.free},
        },
        "supply_chain": supply_chain,
    }

    findings: list[dict[str, str]] = configuration_findings()
    if not report["integration"]["hermes_gateway"]["ok"]:
        findings.append({"severity": "high", "control": "integration", "finding": "Hermes Gateway API is unavailable."})
    if not report["integration"]["hikari_backend"]["ok"]:
        findings.append({"severity": "high", "control": "model", "finding": "Hikari model backend is unavailable."})
    if not report["integration"]["artex"]["ok"]:
        findings.append({"severity": "high", "control": "integration", "finding": "ARTEX is unavailable."})
    if report["integration"]["model_provider"] != "moa":
        findings.append({"severity": "medium", "control": "model", "finding": "Hermes default provider is not MoA."})
    if report["integration"]["approvals_mode"] == "off":
        findings.append({"severity": "high", "control": "approvals", "finding": "Hermes dangerous-command approvals are disabled."})
    if not defender["ok"] or "RUNNING" not in defender["stdout"]:
        findings.append({"severity": "critical", "control": "endpoint", "finding": "Windows Defender service is not confirmed running."})
    if not firewall["ok"]:
        findings.append({"severity": "high", "control": "firewall", "finding": "Windows Firewall posture could not be read."})
    if not docker_status["ok"]:
        findings.append({"severity": "high", "control": "container-runtime", "finding": "Docker Desktop is unavailable."})
    if c_usage.free < 10 * 1024**3:
        findings.append({"severity": "high", "control": "capacity", "finding": "C: has less than 10 GiB free."})

    supply_findings = supply_chain.get("findings", []) if isinstance(supply_chain, dict) else []
    critical_supply = sum(str(item.get("severity", "")).upper() == "CRITICAL" for item in supply_findings)
    high_supply = sum(str(item.get("severity", "")).upper() == "HIGH" for item in supply_findings)
    if critical_supply:
        findings.append(
            {
                "severity": "critical",
                "control": "supply-chain",
                "finding": f"Hermes dependency audit reports {critical_supply} critical finding(s); review JSON evidence before updating.",
            }
        )
    elif high_supply:
        findings.append(
            {
                "severity": "high",
                "control": "supply-chain",
                "finding": f"Hermes dependency audit reports {high_supply} high finding(s); review JSON evidence before updating.",
            }
        )

    network_count = sum(item["exposure"] == "network" for item in listeners)
    if network_count:
        findings.append({"severity": "info", "control": "exposure", "finding": f"{network_count} TCP listeners are bound beyond loopback; review evidence."})

    report["findings"] = findings
    json_path = OUTPUT / f"blue-team-{run_id}.json"
    md_path = OUTPUT / f"blue-team-{run_id}.md"
    json_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    lines = [
        "# Hermes Local Blue-Team Exercise",
        "",
        f"- Run: `{run_id}`",
        f"- Time: `{now.isoformat()}`",
        "- Scope: local machine only; no remote scanning or exploitation",
        "",
        "## Integration",
        f"- Hermes Gateway: {report['integration']['hermes_gateway']['ok']}",
        f"- ARTEX: {report['integration']['artex']['ok']}",
        f"- Hikari backend: {report['integration']['hikari_backend']['ok']}",
        f"- Hermes provider/preset: {report['integration']['model_provider']} / {report['integration']['model_preset']}",
        f"- Startup shortcut: {report['integration']['startup_shortcut_present']}",
        "",
        "## Findings",
    ]
    if findings:
        lines.extend(f"- **{item['severity'].upper()}** [{item['control']}] {item['finding']}" for item in findings)
    else:
        lines.append("- No findings from the checks executed.")
    lines.extend(
        [
            "",
            "## Evidence",
            f"- Full machine-readable evidence: `{json_path}`",
            f"- TCP listeners observed: {len(listeners)}",
            f"- Network-bound listeners: {network_count}",
        ]
    )
    md_path.write_text("\n".join(lines) + "\n", encoding="utf-8")

    high_count = sum(item["severity"] in {"critical", "high"} for item in findings)
    LOG.info(
        json.dumps(
            {
                "ok": high_count == 0,
                "run_id": run_id,
                "report": str(md_path),
                "evidence": str(json_path),
                "high_or_critical": high_count,
                "findings": findings,
            },
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
