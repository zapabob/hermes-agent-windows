from __future__ import annotations

from dataclasses import FrozenInstanceError
import json
from pathlib import Path
import subprocess
import sys
import tomllib

import pytest

from downstream import UPSTREAM_SNAPSHOT_SHA
from downstream.distribution import (
    distribution_version_lines,
    install_script_url,
    load_distribution,
    update_archive_url,
)


ROOT = Path(__file__).resolve().parents[2]


def test_distribution_metadata_is_the_downstream_product_authority() -> None:
    distribution = load_distribution()

    assert distribution.id == "hermes-agent-windows"
    assert distribution.display_name == "Hermes Agent Windows Workstation Edition"
    assert distribution.version == "0.21.1"
    assert distribution.version_source == "downstream"
    assert distribution.repository.slug == "zapabob/hermes-agent-windows"
    assert distribution.upstream.snapshot_sha == UPSTREAM_SNAPSHOT_SHA
    assert distribution.upstream.version == "0.21.0"
    assert distribution.upstream.release_commit_sha == (
        "29112bef099274229cadff79cdff7bf7b99c4b77"
    )
    assert distribution.platform.tier == 1
    assert distribution.platform.architectures == ("x64",)
    assert distribution.channels.default == "stable"
    assert distribution.channels.supported == ("stable", "preview")
    assert distribution.update.allow_upstream_sync is False


def test_distribution_metadata_accessors_are_read_only() -> None:
    distribution = load_distribution()

    with pytest.raises(FrozenInstanceError):
        setattr(distribution, "version", "changed")


def test_windows_patch_version_is_consistent_without_relabeling_upstream() -> None:
    distribution = load_distribution()
    pyproject = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    desktop = json.loads(
        (ROOT / "apps" / "desktop" / "package.json").read_text(encoding="utf-8")
    )
    package_lock = json.loads((ROOT / "package-lock.json").read_text(encoding="utf-8"))

    assert distribution.version_source == "downstream"
    assert distribution.upstream.version == "0.21.0"
    assert distribution.version == "0.21.1"
    assert pyproject["project"]["version"] == distribution.version
    assert desktop["version"] == distribution.version
    assert package_lock["packages"]["apps/desktop"]["version"] == distribution.version
    lock = tomllib.loads((ROOT / "uv.lock").read_text(encoding="utf-8"))
    assert next(package["version"] for package in lock["package"] if package["name"] == "hermes-agent") == distribution.version

    from hermes_cli import __release_date__, __version__

    assert __version__ == distribution.version
    assert __release_date__ == "2026.8.31"


def test_distribution_network_urls_never_target_upstream() -> None:
    script_url = install_script_url("a" * 40, "install.ps1")
    archive_url = update_archive_url("main")

    assert script_url == (
        "https://raw.githubusercontent.com/zapabob/hermes-agent-windows/"
        f"{'a' * 40}/scripts/install.ps1"
    )
    assert archive_url == (
        "https://github.com/zapabob/hermes-agent-windows/archive/refs/heads/main.zip"
    )
    assert "NousResearch" not in script_url
    assert "NousResearch" not in archive_url
    assert install_script_url("preview/windows", "install.ps1") == (
        "https://raw.githubusercontent.com/zapabob/hermes-agent-windows/"
        "preview/windows/scripts/install.ps1"
    )
    assert update_archive_url("preview/windows") == (
        "https://github.com/zapabob/hermes-agent-windows/"
        "archive/refs/heads/preview/windows.zip"
    )


def test_version_lines_identify_distribution_snapshot_and_checkout() -> None:
    lines = distribution_version_lines(downstream_sha="b" * 40)

    assert lines == (
        "Distribution: Hermes Agent Windows Workstation Edition 0.21.1",
        f"Frozen upstream: {UPSTREAM_SNAPSHOT_SHA[:12]}",
        "Downstream revision: bbbbbbbbbbbb",
        "Update channel: stable",
    )


@pytest.mark.parametrize("source, version, valid", [
    ("upstream", "0.21.0", True),
    ("upstream", "0.21.1", False),
    ("downstream", "0.21.1", True),
    ("unknown", "0.21.1", False),
    ("downstream", "not-semver", False),
])
def test_version_authority_preserves_upstream_contract(tmp_path, source, version, valid):
    payload = json.loads((ROOT / "downstream/distribution.json").read_text(encoding="utf-8"))
    payload.update(version_source=source, version=version)
    path = tmp_path / "distribution.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    if valid:
        loaded = load_distribution(path)
        assert loaded.version == version
        assert loaded.upstream.version == "0.21.0"
        assert loaded.upstream.snapshot_sha == UPSTREAM_SNAPSHOT_SHA
    else:
        with pytest.raises(ValueError):
            load_distribution(path)


def test_distribution_json_is_packaged_with_the_python_distribution() -> None:
    pyproject_text = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    pyproject = tomllib.loads(pyproject_text)

    assert "downstream" in pyproject["tool"]["setuptools"]["packages"]["find"]["include"]
    assert "downstream.*" in pyproject["tool"]["setuptools"]["packages"]["find"]["include"]
    assert "distribution.json" in pyproject["tool"]["setuptools"]["package-data"][
        "downstream"
    ]


def test_standalone_windows_installer_fails_closed_on_downstream_metadata() -> None:
    installer = (ROOT / "scripts" / "install.ps1").read_text(encoding="utf-8")

    assert (
        "https://raw.githubusercontent.com/zapabob/hermes-agent-windows/"
        "main/downstream/distribution.json"
    ) in installer
    assert "https://github.com/NousResearch/hermes-agent.git" not in installer


def test_desktop_packaging_has_downstream_identity_installer_and_portable_targets() -> (
    None
):
    package = json.loads(
        (ROOT / "apps" / "desktop" / "package.json").read_text(encoding="utf-8")
    )

    assert package["productName"] == "Hermes Agent Windows Workstation Edition"
    assert package["version"] == load_distribution().version
    assert package["build"]["appId"] == "io.github.zapabob.hermes-agent-windows"
    assert package["build"]["executableName"] == "Hermes"
    assert package["build"]["nsis"]["guid"] == ("48ae4bdc-0f8d-5252-af1e-bf7c0a8c3649")
    assert "nsis" in package["build"]["win"]["target"]
    assert "zip" in package["build"]["win"]["target"]
    assert package["scripts"]["dist:win:portable"].endswith("--win zip")


def test_windows_release_workflow_is_pinned_and_downstream_only() -> None:
    workflow = (ROOT / ".github" / "workflows" / "windows-release.yml").read_text(
        encoding="utf-8"
    )
    install_e2e = (ROOT / ".github" / "workflows" / "install-e2e.yml").read_text(
        encoding="utf-8"
    )
    install_e2e_run = (
        ROOT / ".github" / "workflows" / "install-e2e-run.yml"
    ).read_text(encoding="utf-8")

    assert (
        "actions/attest-build-provenance@977bb373ede98d70efdf65b84cb5f73e068dcc2a"
        in workflow
    )
    assert (
        "actions/upload-artifact@043fb46d1a93c77aae656e7c1c64a875d1fc6a0a" in workflow
    )
    assert "Test-HermesWindowsQualification.ps1" in workflow
    assert "--attestation-status generated" in workflow
    assert "gh release create" in workflow
    assert "Get-ChildItem -LiteralPath $bundle -File -Recurse" in workflow
    assert "NousResearch/hermes-agent.git" not in install_e2e
    assert "HERMES_DEV_SANDBOX_UPSTREAM: https://github.com/${{ github.repository }}.git" in (
        install_e2e_run
    )
    assert "8447bf369a0977b0dadf5c78896e194001dd1584" in install_e2e


def test_windows_demo_requires_exact_clean_candidate_and_dedicated_ports() -> None:
    demo = (ROOT / "scripts" / "demo" / "windows-demo.ps1").read_text(
        encoding="utf-8"
    )

    assert "DemoRoot already exists; choose a new dedicated directory" in demo
    assert "$installStamp.commit -ne $downstreamSha" in demo
    assert "$installStamp.dirty -ne $false" in demo
    assert "Dedicated demo ports are already in use" in demo
    assert 'downstream_identity = "failed"' in demo


@pytest.mark.skipif(sys.platform != "win32", reason="PowerShell installer contract")
def test_install_ps1_resolves_downstream_repository_from_distribution_json() -> None:
    result = subprocess.run(
        [
            "powershell.exe",
            "-NoProfile",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            str(ROOT / "scripts" / "install.ps1"),
            "-ShowResolvedPaths",
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=30,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout.strip().splitlines()[-1])
    assert payload["repository_https"] == (
        "https://github.com/zapabob/hermes-agent-windows.git"
    )
    assert payload["repository_archive_base"] == (
        "https://github.com/zapabob/hermes-agent-windows/archive"
    )
