from __future__ import annotations

import hashlib
import json

import pytest

from downstream import UPSTREAM_SNAPSHOT_SHA
from scripts.downstream.generate_release_manifest import generate_release_bundle


def _qualification(
    status: str = "passed", downstream_sha: str = "a" * 40
) -> dict[str, object]:
    return {
        "schema_version": 1,
        "status": status,
        "downstream_commit_sha": downstream_sha,
        "ci_qualified": True,
        "real_workstation_qualified": False,
        "gates": {
            "install_e2e": "passed",
            "portable_e2e": "passed",
            "upgrade_e2e": "passed",
            "windows_native_python": "passed",
            "windows_native_desktop": "passed",
            "watchdog_go": "passed",
            "upstream_api_compat": "passed",
            "windows_regression": "passed",
            "security_locks": "passed",
        },
    }


def test_release_bundle_contains_required_identity_hashes_and_truthful_signing(
    tmp_path,
) -> None:
    installer = tmp_path / "Hermes-Setup.exe"
    portable = tmp_path / "Hermes-portable.zip"
    installer.write_bytes(b"installer")
    portable.write_bytes(b"portable")
    output = tmp_path / "release"

    manifest = generate_release_bundle(
        installer=installer,
        portable=portable,
        qualification=_qualification(),
        output_dir=output,
        channel="stable",
        downstream_sha="a" * 40,
        installer_signed=False,
        build_timestamp_utc="2026-08-27T00:00:00Z",
        attestation_status="generated",
    )

    assert manifest["product_name"] == "Hermes Agent Windows Workstation Edition"
    assert manifest["distribution_id"] == "hermes-agent-windows"
    from pathlib import Path
    metadata = json.loads((Path(__file__).resolve().parents[2] / "downstream/distribution.json").read_text(encoding="utf-8"))
    assert manifest["downstream_version"] == metadata["version"]
    assert manifest["downstream_commit_sha"] == "a" * 40
    assert manifest["upstream_snapshot_sha"] == UPSTREAM_SNAPSHOT_SHA
    assert manifest["release_channel"] == "stable"
    assert manifest["architecture"] == "x64"
    assert manifest["installer_signed"] is False
    assert manifest["windows_qualification"] == {
        "status": "passed",
        "schema_version": 1,
        "ci_qualified": True,
        "real_workstation_qualified": False,
    }
    artifacts = {item["kind"]: item for item in manifest["artifacts"]}
    assert artifacts["installer"]["sha256"] == hashlib.sha256(b"installer").hexdigest()
    assert artifacts["portable"]["sha256"] == hashlib.sha256(b"portable").hexdigest()
    assert manifest["portable_artifact"] == artifacts["portable"]["name"]
    assert artifacts["installer"]["signed"] is False

    on_disk = json.loads((output / "release-manifest.json").read_text(encoding="utf-8"))
    assert on_disk == manifest
    sums_path = output / "SHA256SUMS.txt"
    sums_bytes = sums_path.read_bytes()
    assert b"\r" not in sums_bytes
    assert sums_bytes.endswith(b"\n")
    sums = sums_bytes.decode("utf-8")
    assert artifacts["installer"]["name"] in sums
    assert artifacts["portable"]["name"] in sums
    notes = (output / "RELEASE_NOTES.md").read_text(encoding="utf-8")
    assert "Unsigned" in notes
    assert str(tmp_path) not in json.dumps(manifest)


def test_stable_release_refuses_incomplete_qualification(tmp_path) -> None:
    installer = tmp_path / "setup.exe"
    portable = tmp_path / "portable.zip"
    installer.write_bytes(b"installer")
    portable.write_bytes(b"portable")
    qualification = _qualification(status="failed", downstream_sha="b" * 40)

    with pytest.raises(ValueError, match="stable release requires"):
        generate_release_bundle(
            installer=installer,
            portable=portable,
            qualification=qualification,
            output_dir=tmp_path / "release",
            channel="stable",
            downstream_sha="b" * 40,
            installer_signed=False,
            build_timestamp_utc="2026-08-27T00:00:00Z",
            attestation_status="generated",
        )


def test_stable_release_refuses_non_ci_or_wrong_sha_qualification(tmp_path) -> None:
    installer = tmp_path / "setup.exe"
    portable = tmp_path / "portable.zip"
    installer.write_bytes(b"installer")
    portable.write_bytes(b"portable")
    qualification = _qualification(downstream_sha="c" * 40)
    qualification["ci_qualified"] = False

    with pytest.raises(ValueError, match="exact_downstream_sha, ci_qualified"):
        generate_release_bundle(
            installer=installer,
            portable=portable,
            qualification=qualification,
            output_dir=tmp_path / "release",
            channel="stable",
            downstream_sha="d" * 40,
            installer_signed=False,
            build_timestamp_utc="2026-08-27T00:00:00Z",
            attestation_status="generated",
        )
