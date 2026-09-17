"""Fail-closed contract for TEST 4 parent Desktop process incarnation checks.

The crash-injection harness must not authorize a backend termination from a
matching numeric parent PID alone.  The recorded ``parentStartMarker`` is a
``winms:<unix-ms>`` marker produced from Electron's process creation time, so
the harness must re-measure and compare that marker both before the injection
and immediately before the destructive action.
"""

from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
HARNESS = REPO_ROOT / "scripts" / "windows" / "tests" / "Test-HermesDesktopLifecycle.ps1"


def test_test4_requires_live_parent_process_incarnation_match() -> None:
    content = HARNESS.read_text(encoding="utf-8")

    assert "function Get-LiveParentStartMarker" in content
    assert 'return "winms:$milliseconds"' in content
    assert "parentStartMarker_mismatch" in content
    assert "Get-LiveParentStartMarker -TargetPid $dPid" in content
    assert "$liveParentMarkerPre" in content
    assert "$liveParentMarkerFinal" in content


def test_test4_revalidates_backend_and_parent_immediately_before_stop() -> None:
    content = HARNESS.read_text(encoding="utf-8")
    stop_index = content.index("Stop-Process -Id $oldBackendPid")
    final_backend_index = content.index("$liveMarkerFinal = Get-LiveStartMarker -TargetPid $oldBackendPid")
    final_parent_index = content.index("$liveParentMarkerFinal = Get-LiveParentStartMarker -TargetPid $dPid")

    assert final_backend_index < stop_index
    assert final_parent_index < stop_index
    assert "toctou_parent_guard_triggered" in content
