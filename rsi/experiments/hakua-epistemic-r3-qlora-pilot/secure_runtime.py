"""Verify a dedicated installed runtime before importing the frozen experiment.

The historical eight-file experiment and its results remain unchanged. Checks do
not import dependencies or initialize CUDA. Training requires an explicit flag.
"""

from __future__ import annotations

import argparse
import datetime
import hashlib
import importlib.machinery
import importlib.metadata
import importlib.util
import json
import os
import re
import runpy
import secrets
import subprocess
import sys
from pathlib import Path

FROZEN_FILES = frozenset({
    "train.jsonl", "frozen_eval.jsonl", "frozen_eval_manifest.json", "historical_roots.json",
    "protocol.json", "pilot_data.py", "frozen_evaluator.py", "pilot_train.py",
})
ROOT = Path(__file__).resolve().parent
OS_ENVIRONMENT = frozenset({
    "SYSTEMROOT", "WINDIR", "PATH", "PATHEXT", "COMSPEC", "USERPROFILE", "APPDATA",
    "LOCALAPPDATA", "PROGRAMDATA", "HOMEDRIVE", "HOMEPATH", "TEMP", "TMP",
    "PROCESSOR_ARCHITECTURE", "PROCESSOR_ARCHITEW6432", "NUMBER_OF_PROCESSORS",
})


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def canonical_name(name: str) -> str:
    return re.sub(r"[-_.]+", "-", name).lower()


def environment_paths(root: Path) -> tuple[Path, Path]:
    if os.name == "nt":
        return root / "Lib/site-packages", root / "Scripts/python.exe"
    version = f"{sys.version_info.major}.{sys.version_info.minor}"
    config = root / "pyvenv.cfg"
    if config.is_file():
        match = re.search(r"(?im)^version(?:_info)?\s*=\s*(\d+\.\d+)", config.read_text(encoding="utf-8"))
        if match:
            version = match.group(1)
    return root / f"lib/python{version}/site-packages", root / "bin/python"


def validate_inputs(experiment: Path, contract: dict) -> dict[str, str]:
    manifest = experiment / "frozen_inputs.json"
    if sha256(manifest) != contract["frozen_manifest_sha256"]:
        raise ValueError("frozen manifest identity mismatch")
    expected = json.loads(manifest.read_text(encoding="utf-8"))
    if set(expected) != FROZEN_FILES:
        raise ValueError("frozen input set mismatch")
    for name, digest in expected.items():
        path = experiment / name
        if not path.resolve().is_relative_to(experiment.resolve()) or sha256(path) != digest:
            raise ValueError(f"frozen input identity mismatch: {name}")
    return expected


def validate_environment(root: Path, contract: dict) -> dict:
    root = root.resolve()
    site, python = environment_paths(root)
    config = root / "pyvenv.cfg"
    if not config.is_file() or not python.is_file() or not site.is_dir():
        raise ValueError("a dedicated installed virtual environment is required")
    settings = {}
    for line in config.read_text(encoding="utf-8").splitlines():
        if "=" in line:
            key, value = line.split("=", 1)
            settings[key.strip().lower()] = value.strip().lower()
    if settings.get("include-system-site-packages") != "false":
        raise ValueError("system-site-packages must be disabled")
    if not site.resolve().is_relative_to(root):
        raise ValueError("site-packages owner is outside the environment")
    distributions = {}
    for distribution in importlib.metadata.distributions(path=[str(site)]):
        name = distribution.metadata.get("Name")
        if not name:
            raise ValueError("distribution metadata name is missing")
        key = canonical_name(name)
        if key in distributions:
            raise ValueError(f"duplicate distribution metadata: {key}")
        distributions[key] = distribution
    versions = {}
    required = dict(contract["distributions"])
    required.update(contract.get("platform_distributions", {}).get(sys.platform, {}))
    for name, version in required.items():
        distribution = distributions.get(name)
        if distribution is None or distribution.version != version:
            raise ValueError(f"distribution version mismatch: {name}")
        metadata = [path for path in distribution.files or ()
                    if len(path.parts) == 2 and path.parent.name.endswith(".dist-info") and path.name == "METADATA"]
        if len(metadata) != 1 or not distribution.locate_file(metadata[0]).resolve().is_relative_to(root):
            raise ValueError(f"distribution metadata owner mismatch: {name}")
        versions[name] = distribution.version
    for owner in contract["owners"]:
        relative = Path(owner["path"])
        if relative.is_absolute() or ".." in relative.parts:
            raise ValueError("invalid runtime owner path")
        distribution = distributions.get(owner["distribution"])
        files = {path.as_posix() for path in distribution.files or ()} if distribution else set()
        path = site / relative
        if owner["path"] not in files or not path.resolve().is_relative_to(root) or not path.is_file():
            raise ValueError(f"runtime owner is not installed locally: {owner['path']}")
        if sha256(path) != owner["sha256"]:
            raise ValueError(f"runtime owner hash mismatch: {owner['path']}")
    return {"environment": str(root), "distributions": versions, "owners_verified": len(contract["owners"])}


def validate_run_id(value: str) -> str:
    if not re.fullmatch(r"secure1-[A-Za-z0-9][A-Za-z0-9_-]{0,55}", value):
        raise ValueError("run ID must start with secure1- and contain only ASCII letters, digits, _ or -")
    return value


def validate_model(experiment: Path, contract: dict) -> dict[str, str]:
    checkpoint = experiment / "base_checkpoint"
    expected = contract["base_checkpoint_files"]
    if not expected or not checkpoint.is_dir():
        raise ValueError("the recorded local base checkpoint is required")
    if {path.name for path in checkpoint.iterdir() if path.is_file()} != set(expected):
        raise ValueError("base checkpoint file set mismatch")
    for name, digest in expected.items():
        path = checkpoint / name
        if Path(name).name != name or not path.resolve().is_relative_to(checkpoint.resolve()) or sha256(path) != digest:
            raise ValueError(f"base checkpoint identity mismatch: {name}")
    return expected


def child_environment(environment: Path) -> dict[str, str]:
    values = {key: value for key, value in os.environ.items() if key.upper() in OS_ENVIRONMENT}
    values.update({
        "HF_HOME": str(environment.parent / "secure-pilot-hf"), "HF_HUB_OFFLINE": "1",
        "TRANSFORMERS_OFFLINE": "1", "HF_HUB_DISABLE_TELEMETRY": "1", "TOKENIZERS_PARALLELISM": "false",
    })
    return values


def child_command(environment: Path, experiment: Path, run_id: str | None) -> list[str]:
    _, python = environment_paths(environment)
    command = [str(python), "-I", "-S", "-B", "-X", "utf8", str(Path(__file__).resolve()),
               "--environment", str(environment), "--experiment", str(experiment), "--_child"]
    if run_id is not None:
        command.extend(["--execute", "--run-id", run_id])
    return command


class SourceOnlyLoader(importlib.machinery.SourceFileLoader):
    """Compile the source we validated; -B alone still permits cached bytecode."""

    def get_code(self, fullname):
        path = self.get_filename(fullname)
        return self.source_to_code(self.get_data(path), path)


class VerifiedSourceFinder:
    """Bind frozen modules by file and ignore bytecode for installed Python code."""

    def __init__(self, experiment: Path, site: Path):
        self.experiment = experiment
        self.site = site.resolve()

    def find_spec(self, fullname, path=None, target=None):
        if fullname in {"pilot_data", "frozen_evaluator"}:
            source = self.experiment / (fullname + ".py")
            return importlib.util.spec_from_file_location(
                fullname, source, loader=SourceOnlyLoader(fullname, str(source)))
        spec = importlib.machinery.PathFinder.find_spec(fullname, path, target)
        if spec is None:
            return None
        if isinstance(spec.loader, importlib.machinery.SourceFileLoader):
            spec.loader = SourceOnlyLoader(fullname, spec.loader.path)
        elif isinstance(spec.loader, importlib.machinery.SourcelessFileLoader):
            if Path(spec.origin).resolve().is_relative_to(self.site):
                raise ImportError("bytecode-only runtime modules are not qualified")
        return spec


def require_worker_receipt(args) -> dict:
    """Only the receipt-owning parent supplies this per-launch stdin capability."""
    token = sys.stdin.read(65).strip()
    if not re.fullmatch(r"[0-9a-f]{64}", token):
        raise ValueError("execution worker requires the receipt-owning parent")
    started = args.experiment / "runtime-receipts" / (args.run_id + ".started.json")
    record = json.loads(started.read_text(encoding="utf-8"))
    if record.get("worker_token_sha256") != hashlib.sha256(token.encode("ascii")).hexdigest():
        raise ValueError("execution worker receipt identity mismatch")
    return record


def inspect_or_execute(args, contract: dict) -> int:
    if not sys.flags.isolated or not sys.flags.no_site:
        raise ValueError("child bootstrap requires isolated mode with site initialization disabled")
    _, python = environment_paths(args.environment)
    if Path(sys.executable).absolute() != python.absolute():
        raise ValueError("selected interpreter identity mismatch")
    if list(sys.version_info[:2]) != contract["python"]:
        raise ValueError("selected Python version mismatch")
    evidence = validate_environment(args.environment, contract)
    evidence["frozen_inputs"] = validate_inputs(args.experiment, contract)
    evidence["python"] = sys.version.split()[0]
    evidence["runtime_revision"] = contract["runtime_revision"]
    if not args.execute:
        print(json.dumps(evidence, ensure_ascii=False))
        return 0
    validate_model(args.experiment, contract)
    # Append the verified site directly. Do not execute .pth or sitecustomize.
    site, _ = environment_paths(args.environment)
    finder_index = sys.meta_path.index(importlib.machinery.PathFinder)
    sys.meta_path.insert(finder_index, VerifiedSourceFinder(args.experiment, site))
    sys.path.append(str(site))
    import torch

    if not torch.cuda.is_available() or torch.version.cuda != contract["cuda"]:
        raise ValueError("the qualified CUDA backend is required; no CPU fallback")
    if torch.cuda.mem_get_info()[0] < 3000 * 1024 * 1024:
        raise ValueError("insufficient shared GPU headroom; existing services will not be stopped")
    sys.argv = [str(args.experiment / "pilot_train.py"), "--run-id", args.run_id]
    runpy.run_path(sys.argv[0], run_name="__main__")
    return 0


def write_exclusive(path: Path, value: dict) -> None:
    with path.open("x", encoding="utf-8", newline="\n") as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2, allow_nan=False)
        stream.write("\n")


def validate_result(args, contract: dict, record: dict, code: int) -> int:
    validate_inputs(args.experiment, contract)
    results = args.experiment / "runs" / args.run_id / "results.json"
    if code != 0 or not results.is_file():
        record["status"] = "FAILED_OR_MISSING_RESULT"
        return code or 1
    payload = json.loads(results.read_text(encoding="utf-8"))
    expected = {"run_id": args.run_id, "status": "COMPLETED_STOP_AND_REPORT", "merge": False,
                "activation": "STOP_AND_REPORT", "formal_level": "NOT_CERTIFIED",
                "formal_human_approval": "PENDING", "self_improvement_certified": False}
    if not isinstance(payload, dict) or any(
        type(payload.get(key)) is not type(value) or payload.get(key) != value for key, value in expected.items()
    ):
        raise ValueError("trainer result does not preserve the non-promotion contract")
    record["status"] = "COMPLETED_STOP_AND_REPORT"
    record["results_sha256"] = sha256(results)
    return 0


def recorded_worker(args, contract: dict) -> int:
    record = require_worker_receipt(args)
    finished = args.experiment / "runtime-receipts" / (args.run_id + ".finished.json")
    if finished.exists():
        raise ValueError("worker result already exists")
    record.update({"run_id": args.run_id, "runtime_revision": contract["runtime_revision"],
                   "formal_promotion": False, "launcher_sha256": sha256(Path(__file__))})
    code = 1
    try:
        try:
            code = inspect_or_execute(args, contract)
        except SystemExit as exit_signal:
            code = exit_signal.code if type(exit_signal.code) is int else (0 if exit_signal.code is None else 1)
        record["child_exit"] = code
        code = validate_result(args, contract, record, code)
    except Exception as error:
        record.update(status="FAILED", error_type=type(error).__name__)
        code = 1
    finally:
        record["launcher_exit"] = code
        write_exclusive(finished, record)
    return code


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--environment", type=Path, required=True)
    parser.add_argument("--experiment", type=Path, default=ROOT)
    parser.add_argument("--execute", action="store_true", help="explicitly start a new, separately recorded training run")
    parser.add_argument("--run-id")
    parser.add_argument("--_child", action="store_true", help=argparse.SUPPRESS)
    args = parser.parse_args(argv)
    args.environment = args.environment.resolve()
    args.experiment = args.experiment.resolve()
    if bool(args.run_id) != args.execute:
        parser.error("--execute and --run-id must be supplied together")
    if args.run_id:
        validate_run_id(args.run_id)
    contract_path = ROOT / "secure-runtime.json"
    contract = json.loads(contract_path.read_text(encoding="utf-8"))
    if args._child:
        return recorded_worker(args, contract) if args.execute else inspect_or_execute(args, contract)
    validate_environment(args.environment, contract)
    frozen = validate_inputs(args.experiment, contract)
    options = {"creationflags": subprocess.CREATE_NO_WINDOW} if os.name == "nt" else {}
    command = child_command(args.environment, args.experiment, None)
    result = subprocess.run(command, env=child_environment(args.environment), stdin=subprocess.DEVNULL,
                            capture_output=True, text=True, encoding="utf-8", timeout=60, **options)
    if result.returncode:
        sys.stderr.write(result.stderr)
        return result.returncode
    if not args.execute:
        sys.stdout.write(result.stdout)
        return 0
    run = args.experiment / "runs" / args.run_id
    if run.exists() or (run.parent.is_dir() and any(p.name.casefold() == args.run_id.casefold() for p in run.parent.iterdir())):
        raise ValueError("run ID already exists; historical results cannot be overwritten")
    records = args.experiment / "runtime-receipts"
    records.mkdir(exist_ok=True)
    token = secrets.token_hex(32)
    record = {"runtime_revision": contract["runtime_revision"], "run_id": args.run_id,
              "observed_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
              "preflight": json.loads(result.stdout), "frozen_inputs": frozen,
              "launcher_sha256": sha256(Path(__file__)), "contract_sha256": sha256(contract_path),
              "historical_protocol_is_runtime_baseline": False, "formal_promotion": False,
              "worker_token_sha256": hashlib.sha256(token.encode("ascii")).hexdigest()}
    write_exclusive(records / (args.run_id + ".started.json"), record)
    command = child_command(args.environment, args.experiment, args.run_id)
    code = 1
    try:
        completed = subprocess.run(command, env=child_environment(args.environment), input=token,
                                   text=True, encoding="utf-8", **options)
        code = completed.returncode
        record["child_exit"] = code
        code = validate_result(args, contract, record, code)
    except (OSError, ValueError) as error:
        record["status"] = "FAILED"
        record["error_type"] = type(error).__name__
        code = 1
    finally:
        record["launcher_exit"] = code
        finished = records / (args.run_id + ".finished.json")
        if not finished.exists():
            write_exclusive(finished, record)
        write_exclusive(records / (args.run_id + ".supervisor.json"), record)
    return code


if __name__ == "__main__":
    if not sys.flags.isolated or not sys.flags.no_site or not sys.dont_write_bytecode:
        raise SystemExit("public bootstrap requires python -I -S -B (isolated, no site initialization)")
    raise SystemExit(main())
