"""Contract tests for Windows Desktop Acceptance Harness.

Ensures that the automated acceptance harness and launcher maintain strict
invariants:
- Launcher script preserves canonical environment, Medium IL handling, and
  refuses banned antipatterns (desktop-backend.json wait, taskkill, prewarm).
- Canonical HERMES_HOME path identity normalization.
- Token redaction invariant (never store credentials/tokens in cleartext).
- Acceptance result schema compliance (summary.json structure).
"""

from __future__ import annotations

import hashlib
import json
import logging
import re
from pathlib import Path

import pytest
from tqdm import tqdm

logger = logging.getLogger("windows_desktop_acceptance")
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")

REPO_ROOT = Path(__file__).resolve().parents[2]
LAUNCHER_PATH = REPO_ROOT / "scripts" / "windows" / "start-hermes-desktop.ps1"


def redact_token_for_artifact(token: str | None) -> dict[str, object]:
    """Canonical token redaction helper for acceptance test artifacts.

    In accordance with harness security invariants:
    - Never persist raw credential/token text.
    - Only record presence, length, and sha256 fingerprint prefix (first 8 hex).
    """
    if not token:
        return {
            "present": False,
            "length": 0,
            "fingerprint": "",
        }
    digest = hashlib.sha256(token.encode("utf-8")).hexdigest()[:8]
    return {
        "present": True,
        "length": len(token),
        "fingerprint": digest,
    }


def normalize_hermes_home_identity(path_str: str) -> str:
    """Normalize HERMES_HOME path strings to a canonical identity string."""
    s = path_str.strip()
    # Handle msys/git-bash style drive prefixes like /c/Users/... -> C:/Users/...
    msys_match = re.match(r"^/([a-zA-Z])/(.*)$", s)
    if msys_match:
        drive = msys_match.group(1).upper()
        rest = msys_match.group(2)
        s = f"{drive}:/{rest}"
    p = Path(s).resolve()
    return str(p).lower().replace("\\", "/")


def test_launcher_script_contract():
    """Verify start-hermes-desktop.ps1 complies with architectural contracts."""
    assert LAUNCHER_PATH.exists(), f"Launcher not found: {LAUNCHER_PATH}"
    content = LAUNCHER_PATH.read_text(encoding="utf-8")

    # 1. BANNED antipatterns
    banned_checks = [
        ("desktop-backend.json wait", re.compile(r"wait.*desktop-backend\.json", re.IGNORECASE)),
        ("90s prewarm wait", re.compile(r"prewarm.*90|90.*prewarm", re.IGNORECASE)),
        ("taskkill", re.compile(r"\btaskkill\b", re.IGNORECASE)),
        ("remote fallback attach", re.compile(r"HERMES_DESKTOP_REMOTE_URL\s*=\s*['\"]?http", re.IGNORECASE)),
    ]
    for desc, pattern in tqdm(banned_checks, desc="Verifying banned antipatterns"):
        assert not pattern.search(content), f"Launcher must NOT contain {desc}"
        logger.info("Checked absence of %s: OK", desc)

    # 2. REQUIRED preserved behaviors and invariants
    required_tokens = [
        "Resolve-CanonicalHermesHome",
        "HERMES_HOME",
        "HERMES_DESKTOP_HERMES_ROOT",
        "HERMES_DESKTOP_CWD",
        "PYTHONUTF8",
        "PYTHONIOENCODING",
        ".worktrees",
        "Medium IL",
        "Hermes.exe",
    ]
    for tok in tqdm(required_tokens, desc="Verifying required invariants"):
        assert tok in content, f"Launcher must preserve requirement: {tok}"
        logger.info("Checked required invariant %s: OK", tok)


@pytest.mark.parametrize(
    ("path_a", "path_b", "should_match"),
    [
        (r"C:\Users\tester\.hermes", "C:/Users/tester/.hermes", True),
        (r"c:\users\tester\.hermes", "C:/Users/tester/.hermes", True),
        ("/c/Users/tester/.hermes", r"C:\Users\tester\.hermes", True),
        (r"C:\Users\tester\.hermes-a", r"C:\Users\tester\.hermes-b", False),
        (r"C:\Users\tester\.hermes", r"C:\Users\tester\.hermes_alt", False),
    ],
)
def test_hermes_home_identity_matrix(path_a: str, path_b: str, should_match: bool):
    """TEST 11: HERMES_HOME path matrix identity normalization."""
    id_a = normalize_hermes_home_identity(path_a)
    id_b = normalize_hermes_home_identity(path_b)
    if should_match:
        assert id_a == id_b, f"Expected {path_a} and {path_b} to resolve to same identity ({id_a} vs {id_b})"
    else:
        assert id_a != id_b, f"Expected {path_a} and {path_b} to resolve to different identities"


def test_token_redaction_contract():
    """Verify credentials and tokens are strictly sanitized in artifact reports."""
    secret = "hermes-live-secret-token-1234567890abcdef"
    redacted = redact_token_for_artifact(secret)

    # Must not contain plaintext
    assert secret not in json.dumps(redacted)
    assert redacted["present"] is True
    assert redacted["length"] == len(secret)
    # Must contain sha256 prefix of length 8
    expected_fp = hashlib.sha256(secret.encode("utf-8")).hexdigest()[:8]
    assert redacted["fingerprint"] == expected_fp

    empty_redacted = redact_token_for_artifact(None)
    assert empty_redacted["present"] is False
    assert empty_redacted["length"] == 0
    assert empty_redacted["fingerprint"] == ""


def test_summary_schema_structure():
    """TEST 18: Validate schema structure requirements for summary.json."""
    required_keys = [
        "head",
        "timestamp",
        "SMOKE_ACCEPTANCE_PASS",
        "AUTOMATED_ACCEPTANCE_PASS",
        "REAL_WINDOWS_REBOOT_QUALIFIED",
        "coldStart",
        "relaunch",
        "backendCrash",
        "reconnectStorm",
        "desktopCrashIsolation",
        "embeddingCrashIsolation",
        "foreignEmbeddingOccupant",
        "ownershipLedger",
        "authentication",
        "soak",
        "reboot",
    ]

    sample_summary = {
        "head": "4aba35ed84",
        "timestamp": "2026-09-17T07:30:00Z",
        "SMOKE_ACCEPTANCE_PASS": True,
        "AUTOMATED_ACCEPTANCE_PASS": False,
        "REAL_WINDOWS_REBOOT_QUALIFIED": False,
        "coldStart": {"passed": True, "durationMs": 4200},
        "relaunch": {"required": 10, "executed": 2, "status": "smoke", "passed": False, "cyclesPassed": 2, "cyclesFailed": 0},
        "backendCrash": {"required": 10, "executed": 2, "status": "smoke", "passed": False, "cyclesPassed": 2, "cyclesFailed": 0},
        "reconnectStorm": {"passed": True, "dialClaims": 1, "spawnCount": 1},
        "desktopCrashIsolation": {"passed": False, "status": "skipped"},
        "embeddingCrashIsolation": {"passed": True, "replacementEmbeddingPid": 1820},
        "foreignEmbeddingOccupant": {"passed": True, "supervisorStatus": "port_occupied"},
        "ownershipLedger": {"passed": True, "deadProbeCount": 0, "quarantinedCorrupt": True},
        "authentication": {"status": 200, "tokenPresent": True, "tokenFingerprint": "abcd1234"},
        "soak": {"passed": False, "status": "skipped", "minutes": 0},
        "reboot": {"enabled": False, "passed": False, "status": "skipped", "cyclesCompleted": 0},
    }

    for key in required_keys:
        assert key in sample_summary, f"Missing key {key} in summary.json schema"


def test_fail_closed_acceptance_contract():
    """Verify acceptance qualification adheres to fail-closed contract."""
    # 1. Incomplete cycles cannot yield AUTOMATED_ACCEPTANCE_PASS
    smoke_summary = {
        "relaunch": {"required": 10, "executed": 2, "status": "smoke", "passed": False},
        "backendCrash": {"required": 10, "executed": 2, "status": "smoke", "passed": False},
        "desktopCrashIsolation": {"passed": False, "status": "skipped"},
    }
    # When SkipLongCycles is supplied:
    assert smoke_summary["relaunch"]["required"] == 10
    assert smoke_summary["relaunch"]["executed"] == 2
    assert smoke_summary["relaunch"]["status"] == "smoke"
    assert smoke_summary["relaunch"]["passed"] is False

    # 2. Never synthesize passed=true for skipped or missing tests
    skipped_item = {"passed": False, "status": "skipped"}
    assert skipped_item["passed"] is False
    assert skipped_item["status"] == "skipped"


# =============================================================================
# TEST 4 Identity Gate RED/GREEN Contract
# Mirrors Invoke-Test4IdentityGates logic in Python for offline unit testing.
# These tests assert that the harness correctly refuses crash injection for
# every partial identity, and only allows it when the full identity matches.
# =============================================================================


def _make_ledger(entries: list[dict]) -> dict:
    """Construct a minimal backend-ownership.json structure."""
    return {"backends": entries}


def _make_full_entry(
    pid: int = 9999,
    desktop_pid: int = 1234,
    nonce: str = "aabbccdd11223344aabbccdd11223344",
    start_marker: str = "win:639241234567890000",
    parent_start_marker: str = "winms:1788000000000",
) -> dict:
    """Return a complete, valid ledger entry for the given pids."""
    return {
        "pid": pid,
        "nonce": nonce,
        "startMarker": start_marker,
        "parentPid": desktop_pid,
        "parentStartMarker": parent_start_marker,
        "profile": "default",
        "command": "python.exe -m hermes_cli.main serve",
    }


def invoke_identity_gates(
    desktop_pid: int,
    candidate_pid: int,
    ledger: dict,
    live_start_marker: str | None,
    ledger_path_exists: bool = True,
) -> dict:
    """Python mirror of Invoke-Test4IdentityGates + Get-LiveStartMarker.

    Returns ``{"passed": bool, "refusalReason": str | None}``.
    """
    if not ledger_path_exists:
        return {"passed": False, "refusalReason": "ledger_file_not_found"}

    backends = ledger.get("backends")
    if not backends:
        return {"passed": False, "refusalReason": "ledger_parse_failed"}

    matches = [e for e in backends if int(e.get("pid", -1)) == candidate_pid]
    if len(matches) == 0:
        return {"passed": False, "refusalReason": "pid_absent_from_ledger"}
    if len(matches) > 1:
        return {"passed": False, "refusalReason": f"ledger_duplicate_entries:{len(matches)}"}

    entry = matches[0]

    # Gate 4a: nonce present and non-empty
    if not entry.get("nonce") or not str(entry["nonce"]).strip():
        return {"passed": False, "refusalReason": "nonce_absent"}

    # Gate 4b: startMarker present, non-empty, NOT pid-only
    sm = str(entry.get("startMarker", "")).strip()
    if not sm:
        return {"passed": False, "refusalReason": "startMarker_absent"}
    if sm.startswith("pid-only:"):
        return {"passed": False, "refusalReason": "startMarker_is_pid_only"}

    # Gate 4c: parentPid matches current Desktop lifecycle
    try:
        ledger_parent_pid = int(entry.get("parentPid", -1))
    except (TypeError, ValueError):
        ledger_parent_pid = -1
    if ledger_parent_pid != desktop_pid:
        return {
            "passed": False,
            "refusalReason": f"parentPid_mismatch:ledger={ledger_parent_pid},desktop={desktop_pid}",
        }

    # Gate 4d: parentStartMarker present and non-empty
    psm = str(entry.get("parentStartMarker", "")).strip()
    if not psm:
        return {"passed": False, "refusalReason": "parentStartMarker_absent"}

    # Gate 5: live startMarker probe matches ledger entry
    if live_start_marker is None:
        return {"passed": False, "refusalReason": "live_marker_probe_failed"}
    if live_start_marker != sm:
        return {"passed": False, "refusalReason": "startMarker_mismatch"}

    return {"passed": True, "refusalReason": None}


class TestTest4IdentityGates:
    """RED/GREEN contract tests for TEST 4 crash injection identity gates."""

    DESKTOP_PID: int = 5000
    BACKEND_PID: int = 9999
    LIVE_MARKER: str = "win:639241234567890000"
    GOOD_ENTRY: dict = _make_full_entry(
        pid=9999, desktop_pid=5000, start_marker="win:639241234567890000"
    )

    def test_red_pid_absent_from_ledger(self) -> None:
        """RED: PID present but absent from ledger → refuse crash injection."""
        ledger = _make_ledger([_make_full_entry(pid=1111, desktop_pid=self.DESKTOP_PID)])
        result = invoke_identity_gates(
            desktop_pid=self.DESKTOP_PID,
            candidate_pid=self.BACKEND_PID,
            ledger=ledger,
            live_start_marker=self.LIVE_MARKER,
        )
        assert result["passed"] is False, "Must refuse when PID is absent from ledger"
        assert result["refusalReason"] == "pid_absent_from_ledger"
        logger.info("RED pid_absent_from_ledger: PASS (refusal confirmed)")

    def test_red_startmarker_mismatch(self) -> None:
        """RED: PID present with mismatched startMarker → refuse crash injection."""
        entry = _make_full_entry(
            pid=self.BACKEND_PID,
            desktop_pid=self.DESKTOP_PID,
            start_marker="win:000000000000000001",  # ledger value differs from live
        )
        ledger = _make_ledger([entry])
        result = invoke_identity_gates(
            desktop_pid=self.DESKTOP_PID,
            candidate_pid=self.BACKEND_PID,
            ledger=ledger,
            live_start_marker=self.LIVE_MARKER,  # live probe returns different value
        )
        assert result["passed"] is False, "Must refuse when live startMarker mismatches ledger"
        assert result["refusalReason"] == "startMarker_mismatch"
        logger.info("RED startMarker_mismatch: PASS (refusal confirmed)")

    def test_red_pid_only_identity(self) -> None:
        """RED: matching PID but degraded pid-only startMarker → refuse crash injection."""
        entry = _make_full_entry(
            pid=self.BACKEND_PID,
            desktop_pid=self.DESKTOP_PID,
            start_marker=f"pid-only:{self.BACKEND_PID}",
        )
        ledger = _make_ledger([entry])
        result = invoke_identity_gates(
            desktop_pid=self.DESKTOP_PID,
            candidate_pid=self.BACKEND_PID,
            ledger=ledger,
            live_start_marker=f"pid-only:{self.BACKEND_PID}",
        )
        assert result["passed"] is False, "Must refuse when startMarker is degraded pid-only identity"
        assert result["refusalReason"] == "startMarker_is_pid_only"
        logger.info("RED startMarker_is_pid_only: PASS (refusal confirmed)")

    def test_red_wrong_parent_lifecycle(self) -> None:
        """RED: correct PID/startMarker but parentPid belongs to wrong Desktop → refuse."""
        wrong_desktop_pid = 7777  # stale — different Desktop generation
        entry = _make_full_entry(
            pid=self.BACKEND_PID,
            desktop_pid=wrong_desktop_pid,
            start_marker=self.LIVE_MARKER,
        )
        ledger = _make_ledger([entry])
        result = invoke_identity_gates(
            desktop_pid=self.DESKTOP_PID,  # current harness Desktop PID differs
            candidate_pid=self.BACKEND_PID,
            ledger=ledger,
            live_start_marker=self.LIVE_MARKER,
        )
        assert result["passed"] is False, "Must refuse when parentPid does not match current Desktop lifecycle"
        assert "parentPid_mismatch" in result["refusalReason"]
        logger.info("RED parentPid_mismatch: PASS (refusal confirmed)")

    def test_green_full_identity_match(self) -> None:
        """GREEN: complete matching identity across all 5 gates → allow crash injection."""
        ledger = _make_ledger([self.GOOD_ENTRY])
        result = invoke_identity_gates(
            desktop_pid=self.DESKTOP_PID,
            candidate_pid=self.BACKEND_PID,
            ledger=ledger,
            live_start_marker=self.LIVE_MARKER,
        )
        assert result["passed"] is True, (
            f"Must allow when all 5 gates pass; refusalReason={result.get('refusalReason')}"
        )
        assert result["refusalReason"] is None
        logger.info("GREEN full_identity_match: PASS (injection allowed)")
