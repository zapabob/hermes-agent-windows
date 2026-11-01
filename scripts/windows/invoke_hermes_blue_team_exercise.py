from __future__ import annotations

import json
import logging
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from downstream.security.posture import collect_host_evidence, run_posture_audit, write_posture_report
from downstream.security.service import SecurityService
from gateway.status import get_running_pid
from hermes_cli.config import load_config

logging.basicConfig(level=logging.INFO, format="%(message)s")
LOG = logging.getLogger("hermes-blue-team")

OUTPUT = ROOT / "output" / "reports"


def main() -> int:
    config = load_config()
    report = run_posture_audit(
        config=config,
        security_status=SecurityService(read_only=True).status(),
        host_collector=lambda effective_config: collect_host_evidence(
            effective_config,
            expected_api_pid=get_running_pid(),
        ),
    )
    written = write_posture_report(report, OUTPUT)
    blocking = [
        check
        for check in report["checks"]
        if check["status"] == "fail" and check["severity"] in {"critical", "high"}
    ]
    result = {
        "ok": not blocking,
        "overall": report["overall"],
        "report": str(written["report"]),
        "evidence": str(written["evidence"]),
        "high_or_critical": len(blocking),
        "failed_controls": [check["id"] for check in blocking],
    }
    LOG.info(json.dumps(result, ensure_ascii=False))
    return 0 if not blocking else 1


if __name__ == "__main__":
    sys.exit(main())
