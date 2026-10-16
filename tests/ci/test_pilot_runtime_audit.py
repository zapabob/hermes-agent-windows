"""The nested experiment must remain audited without initializing CUDA."""

from __future__ import annotations

import importlib.util
import json
import shutil
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[2]
PILOT = "rsi/experiments/hakua-epistemic-r3-qlora-pilot"


@pytest.fixture
def checker():
    spec = importlib.util.spec_from_file_location("pilot_audit", ROOT / "scripts/ci/check_pilot_runtime.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def project(tmp_path):
    destination = tmp_path / "pilot"
    destination.mkdir()
    source = ROOT / PILOT
    for name in ["pyproject.toml", "uv.lock", "secure-runtime.json", "frozen_inputs.json"]:
        shutil.copy2(source / name, destination / name)
    for name in json.loads((source / "frozen_inputs.json").read_text(encoding="utf-8")):
        shutil.copy2(source / name, destination / name)
    shutil.copytree(source / "vendor", destination / "vendor")
    return destination


def test_all_distributable_lock_entries_are_audited(checker, project):
    requirements, evidence = checker.inspect_project(project)
    assert "torch==2.13.0" in requirements
    assert "accelerate==1.15.0" in requirements
    assert not any("hermes.1" in line or "+cu130" in line for line in requirements)
    assert evidence["audited_packages"] == len(requirements) == 76
    assert evidence["private_source_owners_verified"] == 4
    assert evidence["frozen_files_verified"] == 8


@pytest.mark.parametrize("name", ["uv.lock", "pyproject.toml", "secure-runtime.json", "wheel", "frozen"])
def test_drift_and_unknown_local_versions_fail_closed(checker, project, name):
    if name == "wheel":
        wheel = next((project / "vendor").glob("*.whl"))
        wheel.write_bytes(wheel.read_bytes() + b"changed")
    elif name == "frozen":
        (project / "pilot_data.py").write_text("pass\n", encoding="utf-8")
    else:
        target = project / name
        target.write_text(target.read_text(encoding="utf-8").replace("1.15.0+hermes.1", "1.15.0+unknown.1"), encoding="utf-8")
    with pytest.raises(ValueError):
        checker.inspect_project(project)


def test_private_owner_must_match_wheel(checker, project):
    path = project / "secure-runtime.json"
    contract = json.loads(path.read_text(encoding="utf-8"))
    owner = next(owner for owner in contract["owners"] if owner["distribution"] == "accelerate")
    owner["sha256"] = "0" * 64
    path.write_text(json.dumps(contract), encoding="utf-8")
    with pytest.raises(ValueError, match="owner"):
        checker.inspect_project(project)


def test_torch_artifact_must_match_contract(checker, project):
    path = project / "secure-runtime.json"
    contract = json.loads(path.read_text(encoding="utf-8"))
    contract["artifacts"]["torch"]["sha256"] = "0" * 64
    path.write_text(json.dumps(contract), encoding="utf-8")
    with pytest.raises(ValueError, match="Torch artifact"):
        checker.inspect_project(project)


def test_nested_lock_reaches_integrity_and_advisory_ci():
    osv = yaml.safe_load((ROOT / ".github/workflows/osv-scanner.yml").read_text(encoding="utf-8"))
    assert "--lockfile=" + PILOT + "/uv.lock" in osv["jobs"]["scan"]["with"]["scan-args"]
    lock = yaml.safe_load((ROOT / ".github/workflows/uv-lockfile-check.yml").read_text(encoding="utf-8"))
    lock_commands = "\n".join(step.get("run", "") for step in lock["jobs"]["check"]["steps"])
    assert "uv lock --check --project " + PILOT in lock_commands
    workflow = yaml.safe_load((ROOT / ".github/workflows/fork-cicd.yml").read_text(encoding="utf-8"))
    job = workflow["jobs"]["security-locks"]
    steps = job["steps"]
    checker_step = next(step for step in steps if "scripts/ci/check_pilot_runtime.py" in step.get("run", ""))
    assert not checker_step.get("continue-on-error", False)
    assert "pip-audit --strict" in checker_step["run"]
    assert "--no-deps --disable-pip" in checker_step["run"]


def test_private_checkpoint_regression_runs_in_dedicated_cpu_environment():
    workflow = yaml.safe_load((ROOT / ".github/workflows/fork-cicd.yml").read_text(encoding="utf-8"))
    job = workflow["jobs"]["pilot-checkpoint-api"]
    commands = "\n".join(step.get("run", "") for step in job["steps"])
    assert job["runs-on"] == "windows-latest"
    assert job["env"]["CUDA_VISIBLE_DEVICES"] == "-1"
    assert "torch==2.13.0+cpu" in commands and "torch.version.cuda is None" in commands
    assert "test_accelerate_checkpoint_boundary.py" in commands
    assert "m.version('accelerate') == '1.15.0+hermes.1'" in commands
    assert "uv sync" not in commands
