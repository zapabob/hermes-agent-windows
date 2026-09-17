"""Fail-closed contract for TEST 4 parent Desktop process incarnation checks.

The crash-injection harness must not authorize a backend termination from a
matching numeric parent PID alone. The recorded ``parentStartMarker`` is a
``winms:<unix-ms>`` marker produced from Electron's process creation time, so
the harness must re-measure and compare that marker both before the injection
and immediately before the destructive action.
"""

import re
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
HARNESS = REPO_ROOT / "scripts" / "windows" / "tests" / "Test-HermesDesktopLifecycle.ps1"
PARENT_IDENTITY = REPO_ROOT / "apps" / "desktop" / "electron" / "parent-process-identity.ts"


def test_test4_requires_live_parent_process_incarnation_match() -> None:
    content = HARNESS.read_text(encoding="utf-8")

    assert "function Get-LiveParentStartMarker" in content
    assert 'return "winms:$milliseconds"' in content
    assert "parentStartMarker_mismatch" in content
    assert "Get-LiveParentStartMarker -TargetPid $dPid" in content
    assert "$liveParentMarkerPre" in content
    assert "$liveParentMarkerFinal" in content


def test_test4_parent_marker_matches_production_winms_semantics() -> None:
    harness = HARNESS.read_text(encoding="utf-8")
    production = PARENT_IDENTITY.read_text(encoding="utf-8")

    assert "ToUnixTimeMilliseconds()" in harness
    assert 'return "winms:$milliseconds"' in harness
    assert "return `winms:${milliseconds}`" in production
    assert "Electron reports milliseconds since the Unix epoch" in production


def test_matching_parent_pid_alone_is_not_sufficient() -> None:
    content = HARNESS.read_text(encoding="utf-8")

    # The ledger parent PID check must be followed by a distinct process-incarnation
    # comparison before the crash injection can reach Stop-Process.
    pid_gate = content.index("$ledgerParentPid -ne $DesktopPid")
    parent_probe = content.index("$liveParentMarkerPre = Get-LiveParentStartMarker -TargetPid $dPid")
    parent_compare = content.index("$liveParentMarkerPre -ne $ledgerParentStartMarker")
    stop_index = content.index("Stop-Process -Id $oldBackendPid")

    assert pid_gate < parent_probe < parent_compare < stop_index
    assert 'Status ("Cycle {0}: parentStartMarker_mismatch" -f $c)' in content


def test_test4_revalidates_backend_and_parent_immediately_before_stop() -> None:
    content = HARNESS.read_text(encoding="utf-8")
    stop_index = content.index("Stop-Process -Id $oldBackendPid")
    final_backend_index = content.index("$liveMarkerFinal = Get-LiveStartMarker -TargetPid $oldBackendPid")
    final_parent_index = content.index("$liveParentMarkerFinal = Get-LiveParentStartMarker -TargetPid $dPid")

    assert final_backend_index < stop_index
    assert final_parent_index < stop_index
    assert "toctou_guard_triggered" in content
    assert "toctou_parent_guard_triggered" in content


def test_test4_final_backend_probe_follows_parent_probe() -> None:
    """Recheck the destructive target last, without dropping its parent gate."""
    text = HARNESS.read_text(encoding="utf-8")
    parent = text.index("$liveParentMarkerFinal = Get-LiveParentStartMarker")
    backend = text.index("$liveMarkerFinal = Get-LiveStartMarker")
    stop = text.index("Stop-Process -Id $oldBackendPid")
    assert parent < backend < stop


def test_test4_has_no_log_io_after_final_backend_gate() -> None:
    """Refusal logs stay inside gates; successful termination adds no log I/O."""
    text = HARNESS.read_text(encoding="utf-8")
    gate = re.search(
        r"\$liveMarkerFinal = Get-LiveStartMarker.*?continue\s*\}\s*",
        text,
        re.DOTALL,
    )
    assert gate, "could not locate final backend revalidation gate"
    stop = text.find("Stop-Process -Id $oldBackendPid", gate.end())
    assert stop > gate.end()
    between = text[gate.end():stop]
    assert not re.search(r"(?m)^\s*Write-(?:Step|Warning|TqdmProgress)\b", between)
