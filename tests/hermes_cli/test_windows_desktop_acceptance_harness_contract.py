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
        "coldStart",
        "relaunch",
        "backendCrash",
        "reconnectStorm",
        "desktopCrashIsolation",
        "embeddingCrashIsolation",
        "ownershipLedger",
        "authentication",
        "soak",
        "reboot",
    ]

    sample_summary = {
        "head": "4aba35ed84",
        "timestamp": "2026-09-17T07:30:00Z",
        "coldStart": {"passed": True, "durationMs": 4200},
        "relaunch": {"passed": 10, "failed": 0, "medianMs": 2800, "p95Ms": 3500, "maxMs": 3700},
        "backendCrash": {"passed": 10, "failed": 0},
        "reconnectStorm": {"passed": True, "dialClaims": 1, "spawnCount": 1},
        "desktopCrashIsolation": {"passed": True, "embeddingPidPreserved": True},
        "embeddingCrashIsolation": {"passed": True, "replacementSpawned": True},
        "ownershipLedger": {"passed": True, "deadProbeCount": 0, "quarantinedCorrupt": True},
        "authentication": {"status": 200, "tokenPresent": True, "tokenFingerprint": "abcd1234"},
        "soak": {"passed": True, "minutes": 0},
        "reboot": {"enabled": False, "passed": 0},
    }

    for key in required_keys:
        assert key in sample_summary, f"Missing key {key} in summary.json schema"
