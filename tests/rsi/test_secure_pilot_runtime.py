"""Exercise the frozen-input and installed-runtime launch boundary without GPU use."""

from __future__ import annotations

import hashlib
import importlib.util
import json
import py_compile
import shutil
import subprocess
import sys
import venv
from pathlib import Path

import pytest

SOURCE = Path(__file__).resolve().parents[2] / "rsi/experiments/hakua-epistemic-r3-qlora-pilot/secure_runtime.py"


@pytest.fixture
def runtime():
    spec = importlib.util.spec_from_file_location("secure_pilot_runtime", SOURCE)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


@pytest.fixture
def inputs(tmp_path):
    experiment = tmp_path / "experiment"
    experiment.mkdir()
    names = {
        "train.jsonl", "frozen_eval.jsonl", "frozen_eval_manifest.json", "historical_roots.json",
        "protocol.json", "pilot_data.py", "frozen_evaluator.py", "pilot_train.py",
    }
    for name in names:
        (experiment / name).write_text("{}\n", encoding="utf-8")
    manifest = experiment / "frozen_inputs.json"
    manifest.write_text(json.dumps({name: digest(experiment / name) for name in sorted(names)}), encoding="utf-8")
    return experiment, {"frozen_manifest_sha256": digest(manifest)}


@pytest.fixture
def environment(tmp_path, runtime):
    root = tmp_path / "environment"
    site, python = runtime.environment_paths(root)
    site.mkdir(parents=True)
    python.parent.mkdir(parents=True, exist_ok=True)
    python.write_bytes(b"fixture interpreter; never executed")
    (root / "pyvenv.cfg").write_text("include-system-site-packages = false\n", encoding="utf-8")
    owner = site / "sample_runtime/__init__.py"
    owner.parent.mkdir()
    owner.write_text("raise RuntimeError('preflight imported dependency')\n", encoding="utf-8")
    metadata = site / "sample_runtime-1.0.0.dist-info"
    metadata.mkdir()
    (metadata / "METADATA").write_text("Metadata-Version: 2.1\nName: sample-runtime\nVersion: 1.0.0\n", encoding="utf-8")
    (metadata / "RECORD").write_text("sample_runtime/__init__.py,,\nsample_runtime-1.0.0.dist-info/METADATA,,\n", encoding="utf-8")
    contract = {
        "distributions": {"sample-runtime": "1.0.0"},
        "owners": [{"distribution": "sample-runtime", "path": "sample_runtime/__init__.py", "sha256": digest(owner)}],
    }
    return root, contract, site


def test_preflight_checks_without_importing_dependency(runtime, environment):
    root, contract, _ = environment
    result = runtime.validate_environment(root, contract)
    assert result["distributions"] == contract["distributions"]


def test_same_version_with_changed_owner_is_rejected(runtime, environment):
    root, contract, site = environment
    (site / "sample_runtime/__init__.py").write_text("pass\n", encoding="utf-8")
    with pytest.raises(ValueError, match="owner"):
        runtime.validate_environment(root, contract)


def test_same_owner_with_changed_version_is_rejected(runtime, environment):
    root, contract, site = environment
    metadata = site / "sample_runtime-1.0.0.dist-info/METADATA"
    metadata.write_text(metadata.read_text(encoding="utf-8").replace("Version: 1.0.0", "Version: 2.0.0"), encoding="utf-8")
    with pytest.raises(ValueError, match="version"):
        runtime.validate_environment(root, contract)


def test_vendored_metadata_is_not_mistaken_for_distribution_metadata(runtime, environment):
    root, contract, site = environment
    relative = "sample_runtime/_vendor/another-0.1.dist-info/METADATA"
    metadata = site / relative
    metadata.parent.mkdir(parents=True)
    metadata.write_text("Name: another\nVersion: 0.1\n", encoding="utf-8")
    record = site / "sample_runtime-1.0.0.dist-info/RECORD"
    record.write_text(record.read_text(encoding="utf-8") + relative + ",,\n", encoding="utf-8")
    assert runtime.validate_environment(root, contract)["distributions"] == contract["distributions"]


def test_borrowed_runtime_cannot_be_satisfied_by_pth(runtime, environment, tmp_path):
    root, contract, site = environment
    outside = tmp_path / "borrowed"
    outside.mkdir()
    (site / "borrowed.pth").write_text(str(outside), encoding="utf-8")
    (site / "sample_runtime-1.0.0.dist-info/METADATA").rename(outside / "METADATA")
    with pytest.raises(ValueError):
        runtime.validate_environment(root, contract)


def test_system_site_packages_are_rejected(runtime, environment):
    root, contract, _ = environment
    (root / "pyvenv.cfg").write_text("include-system-site-packages = true\n", encoding="utf-8")
    with pytest.raises(ValueError, match="system-site"):
        runtime.validate_environment(root, contract)


def test_duplicate_metadata_is_rejected(runtime, environment):
    root, contract, site = environment
    extra = site / "sample_runtime-0.9.0.dist-info"
    extra.mkdir()
    (extra / "METADATA").write_text("Name: sample_runtime\nVersion: 0.9.0\n", encoding="utf-8")
    with pytest.raises(ValueError, match="duplicate"):
        runtime.validate_environment(root, contract)


def test_record_cannot_claim_owner_from_outside_environment(runtime, environment):
    root, contract, site = environment
    contract["owners"][0]["path"] = "../outside.py"
    with pytest.raises(ValueError, match="owner"):
        runtime.validate_environment(root, contract)


def test_exact_frozen_input_contract_passes(runtime, inputs):
    experiment, contract = inputs
    assert set(runtime.validate_inputs(experiment, contract)) == set(runtime.FROZEN_FILES)


@pytest.mark.parametrize("name", [
    "train.jsonl", "frozen_eval.jsonl", "frozen_eval_manifest.json", "historical_roots.json",
    "protocol.json", "pilot_data.py", "frozen_evaluator.py", "pilot_train.py",
])
def test_each_frozen_input_change_is_rejected(runtime, inputs, name):
    experiment, contract = inputs
    (experiment / name).write_text("changed\n", encoding="utf-8")
    with pytest.raises(ValueError, match="frozen"):
        runtime.validate_inputs(experiment, contract)


def test_changing_manifest_and_input_together_is_rejected(runtime, inputs):
    experiment, contract = inputs
    path = experiment / "train.jsonl"
    path.write_text("changed\n", encoding="utf-8")
    manifest = experiment / "frozen_inputs.json"
    data = json.loads(manifest.read_text(encoding="utf-8"))
    data[path.name] = digest(path)
    manifest.write_text(json.dumps(data), encoding="utf-8")
    with pytest.raises(ValueError, match="manifest"):
        runtime.validate_inputs(experiment, contract)


@pytest.mark.parametrize("value", ["../escape", "CON", "secure1-con.", "secure1-a\x00", "old-run", "secure1-a/b", "secure1-"])
def test_run_identifier_rejects_path_and_historical_aliases(runtime, value):
    with pytest.raises(ValueError):
        runtime.validate_run_id(value)


def test_run_identifier_accepts_distinct_secure_revision(runtime):
    assert runtime.validate_run_id("secure1-qualification_001") == "secure1-qualification_001"


def test_model_identity_is_checked_before_execution(runtime, inputs):
    experiment, contract = inputs
    checkpoint = experiment / "base_checkpoint"
    checkpoint.mkdir()
    model = checkpoint / "model.safetensors"
    model.write_bytes(b"benign fixture, not an actual model")
    contract["base_checkpoint_files"] = {model.name: digest(model)}
    assert runtime.validate_model(experiment, contract) == contract["base_checkpoint_files"]
    model.write_bytes(b"changed fixture")
    with pytest.raises(ValueError, match="checkpoint"):
        runtime.validate_model(experiment, contract)


@pytest.fixture
def executable_pilot(tmp_path_factory, runtime):
    """Real interpreter/process tests; torch and trainer are harmless stand-ins."""
    def create(mode="success"):
        # Keep the Windows venv executable below CreateProcess's path limit.
        # The case still exercises spaces and Japanese in the script path.
        tmp_path = tmp_path_factory.mktemp("exec")
        experiment = tmp_path / mode / "pilot 日本語"
        experiment.mkdir(parents=True)
        shutil.copy2(SOURCE, experiment / "secure_runtime.py")
        environment = tmp_path / mode / "dedicated environment"
        venv.EnvBuilder(with_pip=False).create(environment)
        site, _ = runtime.environment_paths(environment)
        site.mkdir(parents=True, exist_ok=True)
        imported = experiment / "dependency-imported"
        module = site / "torch/__init__.py"
        module.parent.mkdir()
        module.write_text(
            "from pathlib import Path\nfrom types import SimpleNamespace\n"
            f"with Path({str(imported)!r}).open('a', encoding='utf-8') as f: f.write('imported\\n')\n"
            "cuda=SimpleNamespace(is_available=lambda: True, mem_get_info=lambda: (4000*1024*1024, 8000*1024*1024))\n"
            "version=SimpleNamespace(cuda='13.0')\n", encoding="utf-8",
        )
        metadata = site / "torch-2.13.0+cu130.dist-info"
        metadata.mkdir()
        (metadata / "METADATA").write_text("Name: torch\nVersion: 2.13.0+cu130\n", encoding="utf-8")
        (metadata / "RECORD").write_text("torch/__init__.py,,\ntorch-2.13.0+cu130.dist-info/METADATA,,\n", encoding="utf-8")
        pth_marker = experiment / "pth-executed"
        (site / "untrusted.pth").write_text(
            f"import pathlib; pathlib.Path({str(pth_marker)!r}).write_text('executed')\n", encoding="utf-8",
        )
        for name in runtime.FROZEN_FILES:
            (experiment / name).write_text("{}\n", encoding="utf-8")
        trainer = (
            "import json,os,sys\nfrom pathlib import Path\n"
            "assert sys.argv[1] == '--run-id'\nassert 'FAKE_API_KEY' not in os.environ\n"
            "assert 'PYTHONPATH' not in os.environ\n"
            "root=Path(__file__).resolve().parent\nrun_id=sys.argv[2]\n"
            "out=root/'runs'/run_id\nout.mkdir(parents=True,exist_ok=False)\n"
            "(out/'argv.json').write_text(json.dumps(sys.argv),encoding='utf-8')\n"
        )
        if mode == "failure":
            trainer += "raise SystemExit(7)\n"
        elif mode == "missing":
            trainer += "raise SystemExit(0)\n"
        elif mode == "malformed":
            trainer += "(out/'results.json').write_text('[]',encoding='utf-8')\n"
        else:
            trainer += (
                "result={'run_id':run_id,'status':'COMPLETED_STOP_AND_REPORT','merge':False,"
                "'activation':'STOP_AND_REPORT','formal_level':'NOT_CERTIFIED',"
                "'formal_human_approval':'PENDING','self_improvement_certified':False}\n"
                "(out/'results.json').write_text(json.dumps(result),encoding='utf-8')\n"
            )
        (experiment / "pilot_train.py").write_text(trainer, encoding="utf-8")
        frozen = experiment / "frozen_inputs.json"
        frozen.write_text(json.dumps({name: digest(experiment / name) for name in runtime.FROZEN_FILES}), encoding="utf-8")
        checkpoint = experiment / "base_checkpoint"
        checkpoint.mkdir()
        (checkpoint / "model.safetensors").write_bytes(b"fixture only")
        contract = {
            "runtime_revision": "test-only-not-GPU-evidence", "python": list(sys.version_info[:2]), "cuda": "13.0",
            "distributions": {"torch": "2.13.0+cu130"},
            "owners": [{"distribution": "torch", "path": "torch/__init__.py", "sha256": digest(module)}],
            "frozen_manifest_sha256": digest(frozen),
            "base_checkpoint_files": {"model.safetensors": digest(checkpoint / "model.safetensors")},
        }
        (experiment / "secure-runtime.json").write_text(json.dumps(contract), encoding="utf-8")
        spec = importlib.util.spec_from_file_location("fixture_secure_pilot", experiment / "secure_runtime.py")
        launch = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(launch)
        return launch, environment, experiment, imported, pth_marker
    return create


def test_real_check_ignores_pth_and_pythonpath_without_importing_torch(executable_pilot, monkeypatch):
    launch, environment, experiment, imported, pth_marker = executable_pilot()
    monkeypatch.setenv("PYTHONPATH", str(experiment))
    monkeypatch.setenv("FAKE_API_KEY", "sentinel-not-a-real-secret")
    assert launch.main(["--environment", str(environment)]) == 0
    assert not imported.exists() and not pth_marker.exists()
    assert not (experiment / "runs").exists()
    assert not (experiment / "runtime-receipts").exists()


def test_explicit_execution_runs_once_and_preserves_history(executable_pilot, monkeypatch):
    launch, environment, experiment, imported, pth_marker = executable_pilot()
    monkeypatch.setenv("FAKE_API_KEY", "sentinel-not-a-real-secret")
    args = ["--environment", str(environment), "--execute", "--run-id", "secure1-qualification_001"]
    assert launch.main(args) == 0
    assert imported.read_text(encoding="utf-8").splitlines() == ["imported"]
    assert not pth_marker.exists()
    finished = experiment / "runtime-receipts/secure1-qualification_001.finished.json"
    result = json.loads(finished.read_text(encoding="utf-8"))
    assert result["child_exit"] == result["launcher_exit"] == 0
    assert result["formal_promotion"] is False
    before = finished.read_bytes()
    with pytest.raises(ValueError, match="already exists"):
        launch.main(args)
    assert finished.read_bytes() == before
    assert imported.read_text(encoding="utf-8").splitlines() == ["imported"]


@pytest.mark.parametrize(("mode", "expected"), [("failure", 7), ("missing", 1), ("malformed", 1)])
def test_real_failure_and_missing_results_are_not_success(executable_pilot, mode, expected):
    launch, environment, experiment, _, _ = executable_pilot(mode)
    assert launch.main(["--environment", str(environment), "--execute", "--run-id", "secure1-failure"]) == expected
    receipt = json.loads((experiment / "runtime-receipts/secure1-failure.finished.json").read_text(encoding="utf-8"))
    assert receipt["launcher_exit"] == expected
    assert receipt["status"] != "COMPLETED_STOP_AND_REPORT"


def refresh_fixture_manifest(experiment):
    manifest = experiment / "frozen_inputs.json"
    entries = json.loads(manifest.read_text(encoding="utf-8"))
    manifest.write_text(json.dumps({name: digest(experiment / name) for name in entries}), encoding="utf-8")
    contract = experiment / "secure-runtime.json"
    values = json.loads(contract.read_text(encoding="utf-8"))
    values["frozen_manifest_sha256"] = digest(manifest)
    contract.write_text(json.dumps(values), encoding="utf-8")


def public_command(launch, environment, experiment, *extra):
    _, python = launch.environment_paths(environment)
    return [str(python), "-I", "-S", "-B", "-X", "utf8", str(experiment / "secure_runtime.py"),
            "--environment", str(environment), *extra]


def invoke_fixture(launch, environment, command, input_text=""):
    options = {"creationflags": subprocess.CREATE_NO_WINDOW} if sys.platform == "win32" else {}
    return subprocess.run(command, input=input_text, capture_output=True, text=True, encoding="utf-8",
                          env=launch.child_environment(environment), timeout=60, **options)


def test_documented_public_entry_is_isolated(executable_pilot):
    readme = (SOURCE.parent / "README_SECURE_RUNTIME.md").read_text(encoding="utf-8")
    commands = [line for line in readme.splitlines() if '"$pilotRoot\\secure_runtime.py"' in line]
    assert len(commands) == 2
    assert all("python -I -S -B " in line for line in commands)
    launch, environment, experiment, imported, pth = executable_pilot()
    result = invoke_fixture(launch, environment, public_command(launch, environment, experiment))
    assert result.returncode == 0, result.stderr
    assert not imported.exists() and not pth.exists()


def test_public_entry_refuses_nonisolated_bootstrap(executable_pilot):
    launch, environment, experiment, _, _ = executable_pilot()
    command = public_command(launch, environment, experiment)
    command.remove("-I")
    result = invoke_fixture(launch, environment, command)
    assert result.returncode != 0 and "isolated" in result.stderr


def test_frozen_file_cannot_be_shadowed_by_adjacent_package(executable_pilot):
    launch, environment, experiment, _, _ = executable_pilot()
    evaluator = experiment / "frozen_evaluator.py"
    evaluator.write_text("VALUE = 'frozen'\n", encoding="utf-8")
    trainer = experiment / "pilot_train.py"
    trainer.write_text("from frozen_evaluator import VALUE\nassert VALUE == 'frozen'\n" + trainer.read_text(encoding="utf-8"), encoding="utf-8")
    refresh_fixture_manifest(experiment)
    shadow = experiment / "frozen_evaluator/__init__.py"
    shadow.parent.mkdir()
    shadow.write_text("raise RuntimeError('unverified package was imported')\n", encoding="utf-8")
    result = invoke_fixture(launch, environment, public_command(
        launch, environment, experiment, "--execute", "--run-id", "secure1-package"))
    assert result.returncode == 0, result.stderr
    assert json.loads((experiment / "runtime-receipts/secure1-package.finished.json").read_text(encoding="utf-8"))["launcher_exit"] == 0


@pytest.mark.parametrize("target", ["dependency", "frozen"])
def test_valid_existing_bytecode_cannot_replace_verified_source(executable_pilot, target):
    launch, environment, experiment, _, _ = executable_pilot()
    site, _ = launch.environment_paths(environment)
    if target == "dependency":
        source = site / "torch/__init__.py"
    else:
        source = experiment / "frozen_evaluator.py"
        source.write_text("VALUE = 'frozen'\n", encoding="utf-8")
        trainer = experiment / "pilot_train.py"
        trainer.write_text("from frozen_evaluator import VALUE\nassert VALUE == 'frozen'\n" + trainer.read_text(encoding="utf-8"), encoding="utf-8")
        refresh_fixture_manifest(experiment)
    original = source.read_bytes()
    source.write_text("raise RuntimeError('unverified bytecode was imported')\n", encoding="utf-8")
    py_compile.compile(str(source), doraise=True, invalidation_mode=py_compile.PycInvalidationMode.UNCHECKED_HASH)
    source.write_bytes(original)
    result = invoke_fixture(launch, environment, public_command(
        launch, environment, experiment, "--execute", "--run-id", "secure1-bytecode"))
    assert result.returncode == 0, result.stderr


@pytest.mark.parametrize("mode", ["missing", "malformed"])
def test_direct_internal_worker_cannot_bypass_result_finalization(executable_pilot, mode):
    launch, environment, experiment, imported, _ = executable_pilot(mode)
    result = invoke_fixture(launch, environment, public_command(
        launch, environment, experiment, "--_child", "--execute", "--run-id", "secure1-direct"))
    assert result.returncode != 0
    assert not imported.exists()
    assert not (experiment / "runs").exists()


def test_windows_only_dependency_is_declared_conditionally():
    contract = json.loads((SOURCE.parent / "secure-runtime.json").read_text(encoding="utf-8"))
    assert "colorama" not in contract["distributions"]
    assert contract["platform_distributions"]["win32"]["colorama"] == "0.4.6"


@pytest.mark.parametrize("mode", ["missing", "malformed"])
def test_worker_with_caller_created_receipt_still_finalizes_results(executable_pilot, mode):
    launch, environment, experiment, _, _ = executable_pilot(mode)
    token = "a" * 64
    receipts = experiment / "runtime-receipts"
    receipts.mkdir()
    (receipts / "secure1-supplied.started.json").write_text(json.dumps({
        "worker_token_sha256": hashlib.sha256(token.encode("ascii")).hexdigest(),
    }), encoding="utf-8")
    result = invoke_fixture(launch, environment, public_command(
        launch, environment, experiment, "--_child", "--execute", "--run-id", "secure1-supplied"), token)
    assert result.returncode != 0
    finished = json.loads((receipts / "secure1-supplied.finished.json").read_text(encoding="utf-8"))
    assert finished["launcher_exit"] != 0 and finished["formal_promotion"] is False
