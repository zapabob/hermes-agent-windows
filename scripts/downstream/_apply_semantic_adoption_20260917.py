"""One-shot worktree materializer; removed before the feature PR is merged."""
from __future__ import annotations

import ast
from pathlib import Path
import subprocess
import sys

root = Path(sys.argv[1]).resolve()
relative = "hermes_cli/plugin_dev.py"
blob = subprocess.check_output(
    ["git", "-C", str(root), "rev-parse", "HEAD:" + relative], text=True
).strip()
if blob != "ae470285b009ddac989e0dac08c627f8e6088b03":
    raise SystemExit("Refusing to patch an unreviewed Plugin Doctor source blob")
path = root / relative
source = path.read_text(encoding="utf-8")
anchor = "def doctor_plugin(target: str | os.PathLike[str] | None = None) -> DoctorReport:\n"
helper = '''def _check_security_scan(report: DoctorReport, plugin_path: Path) -> bool:
    """Use the install-time scanner before executing candidate registration.

    Validation never grants installation approval. Caution remains a warning
    for the reviewer; the installer's explicit-consent policy is unchanged.
    This static check is not a sandbox for candidate Python code.
    """
    try:
        from tools.plugin_guard import scan_plugin

        result = scan_plugin(plugin_path)
        verdict = result.verdict
        if verdict not in ("safe", "caution", "dangerous"):
            report.error("Plugin security scan returned an unrecognized verdict")
            return False
        # Report rule ids and source locations, never raw source snippets or
        # scanner exception text that might contain credential material.
        flagged = [
            finding for finding in getattr(result, "findings", ())
            if finding.severity in ("critical", "high")
        ]
        summary = ", ".join(sorted({
            f"{finding.pattern_id} ({Path(finding.file).name}:{finding.line})"
            for finding in flagged
        })) or "no high-severity findings"
    except Exception as exc:
        report.error(f"Plugin security scan failed ({type(exc).__name__})")
        return False

    if verdict == "dangerous":
        report.error(f"Plugin security scan blocked registration: {summary}")
        return False
    if verdict == "caution":
        report.warning(
            f"Plugin security scan caution: {summary}. "
            "Validation does not grant installation approval."
        )
    return True


'''
needle = "    report = DoctorReport(path)\n    try:\n        with _doctor_runtime(path) as host:\n"
replacement = "    report = DoctorReport(path)\n    if not _check_security_scan(report, path):\n        return report\n    try:\n        with _doctor_runtime(path) as host:\n"
if source.count(anchor) != 1 or source.count(needle) != 1:
    raise SystemExit("Patch anchors do not identify exactly one live Doctor entry point")
changed = source.replace(anchor, helper + anchor).replace(needle, replacement)
ast.parse(changed)
with path.open("w", encoding="utf-8", newline="\n") as handle:
    handle.write(changed)
print("Applied only the shared scanner gate to " + relative)
