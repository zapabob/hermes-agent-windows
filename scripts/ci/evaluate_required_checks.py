"""Fail the CI aggregate unless every supplied job succeeded or was skipped."""

from __future__ import annotations

from collections.abc import Mapping
import json
import logging
import os
from pathlib import Path

logger = logging.getLogger(__name__)


def evaluate_results(needs: object) -> dict[str, str]:
    """Project untrusted workflow metadata without retaining job outputs."""
    if not isinstance(needs, Mapping) or not needs:
        raise ValueError("Required-check results must be a nonempty mapping")
    results: dict[str, str] = {}
    for name, job in needs.items():
        if not isinstance(name, str) or not isinstance(job, Mapping):
            raise ValueError("Malformed required-check record")
        result = job.get("result")
        if not isinstance(result, str) or not result:
            raise ValueError(f"Missing required-check result: {name}")
        results[name] = result
    return results


def main() -> int:
    """Emit the existing needs-json output and preserve failed/cancelled gates."""
    try:
        results = evaluate_results(json.loads(os.environ.get("NEEDS", "")))
        output_path = os.environ.get("GITHUB_OUTPUT")
        if not output_path:
            raise ValueError("GITHUB_OUTPUT is required")
        with Path(output_path).open("a", encoding="utf-8") as output:
            output.write(f"needs-json={json.dumps(results, separators=(',', ':'))}\n")
    except (ValueError, OSError) as exc:
        logger.error("Cannot evaluate required checks: %s", exc)
        return 1

    for name, result in sorted(results.items()):
        logger.info("%s: %s", name, result)
    failed = sorted(
        name for name, result in results.items() if result not in {"success", "skipped"}
    )
    if failed:
        logger.error("%d required check(s) did not pass: %s", len(failed), ", ".join(failed))
        return 1
    logger.info("All required checks passed or were skipped")
    return 0


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    raise SystemExit(main())
