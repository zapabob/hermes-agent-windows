"""Verify the frozen pilot's lock/private wheel and emit all public advisory queries.

This checks packaging and source identity without installing or importing Torch.
The two exact local version projections are advisory queries, not patch proof;
the wheel integrity and public checkpoint API regressions supply separate proof.
"""

from __future__ import annotations

import argparse
import base64
import csv
import hashlib
import io
import json
import re
import tomllib
import zipfile
from email.parser import BytesParser
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PILOT = ROOT / "rsi/experiments/hakua-epistemic-r3-qlora-pilot"
PUBLIC_BASES = {
    ("torch", "2.13.0+cu130"): "2.13.0",
    ("accelerate", "1.15.0+hermes.1"): "1.15.0",
}
FROZEN_FILES = {
    "train.jsonl", "frozen_eval.jsonl", "frozen_eval_manifest.json", "historical_roots.json",
    "protocol.json", "pilot_data.py", "frozen_evaluator.py", "pilot_train.py",
}


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def require(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(message)


def inspect_wheel(project: Path, contract: dict, package: dict) -> int:
    artifact = contract["artifacts"]["accelerate"]
    path = project / artifact["path"]
    require(path.resolve().is_relative_to(project.resolve()), "private wheel must be local")
    require(package["source"] == {"path": artifact["path"]}, "private wheel source mismatch")
    require(package["wheels"] == [{"filename": path.name, "hash": "sha256:" + artifact["sha256"]}],
            "private wheel lock hash mismatch")
    require(digest(path.read_bytes()) == artifact["sha256"], "private wheel hash mismatch")
    with zipfile.ZipFile(path) as wheel:
        names = wheel.namelist()
        require(len(names) == len(set(names)), "duplicate private wheel entries")
        records = [name for name in names if name.endswith(".dist-info/RECORD")]
        require(len(records) == 1, "private wheel RECORD missing or ambiguous")
        rows = list(csv.reader(io.StringIO(wheel.read(records[0]).decode("utf-8"))))
        require(all(len(row) == 3 for row in rows), "invalid private wheel RECORD")
        require({row[0] for row in rows} == set(names) and len(rows) == len(names),
                "private wheel RECORD coverage mismatch")
        for name, checksum, size in rows:
            if name == records[0]:
                require(not checksum and not size, "invalid RECORD self-entry")
                continue
            content = wheel.read(name)
            expected = "sha256=" + base64.urlsafe_b64encode(hashlib.sha256(content).digest()).decode("ascii").rstrip("=")
            require(checksum == expected and size == str(len(content)), "private wheel RECORD content mismatch")
        metadata_name = records[0].removesuffix("RECORD") + "METADATA"
        metadata = BytesParser().parsebytes(wheel.read(metadata_name))
        require(metadata["Name"] == "accelerate" and metadata["Version"] == package["version"],
                "private wheel metadata mismatch")
        licenses = [name for name in names if name.endswith(".dist-info/licenses/LICENSE")]
        require(len(licenses) == 1 and wheel.read(licenses[0]) == (project / "vendor/LICENSE.accelerate").read_bytes(),
                "private wheel license mismatch")
        owners = [owner for owner in contract["owners"] if owner["distribution"] == "accelerate"]
        require(bool(owners), "private source owners missing")
        for owner in owners:
            require(owner["path"] in names and digest(wheel.read(owner["path"])) == owner["sha256"],
                    "private source owner mismatch")
    return len(owners)


def inspect_project(project: Path) -> tuple[list[str], dict]:
    lock = tomllib.loads((project / "uv.lock").read_text(encoding="utf-8"))
    manifest = tomllib.loads((project / "pyproject.toml").read_text(encoding="utf-8"))
    contract = json.loads((project / "secure-runtime.json").read_text(encoding="utf-8"))
    packages = lock["package"]
    virtual = [package for package in packages if "virtual" in package["source"]]
    require(len(virtual) == 1 and virtual[0]["name"] == manifest["project"]["name"], "unexpected virtual project")
    distributions = [package for package in packages if package not in virtual]
    pairs = {(package["name"], package["version"]) for package in distributions}
    requirements = set()
    for package in distributions:
        name, version = package["name"], package["version"]
        require(bool(re.fullmatch(r"[a-z0-9][a-z0-9_.-]*", name)), "invalid package name")
        require(bool(re.fullmatch(r"[0-9][a-zA-Z0-9_.!+-]*", version)), "invalid package version")
        pair = name, version
        require("+" not in version or pair in PUBLIC_BASES, "unknown local package version")
        if "registry" not in package["source"]:
            require(pair == ("accelerate", "1.15.0+hermes.1"), "unaudited local source")
        requirements.add(name + "==" + PUBLIC_BASES.get(pair, version))
    required = dict(contract["distributions"])
    for values in contract.get("platform_distributions", {}).values():
        required.update(values)
    require(set(required.items()) <= pairs, "runtime contract is inconsistent with lock")
    for dependency in manifest["project"]["dependencies"]:
        match = re.fullmatch(r"([a-z0-9][a-z0-9-]*)==([^\s]+)", dependency)
        require(match is not None and tuple(match.groups()) in pairs, "manifest pin is inconsistent with lock")
    private = [package for package in distributions if package["name"] == "accelerate"]
    require(len(private) == 1 and private[0]["version"] == "1.15.0+hermes.1", "private patch identity mismatch")
    torch = [package for package in distributions if package["name"] == "torch"]
    artifact = contract["artifacts"]["torch"]
    require(len(torch) == 1 and torch[0]["source"] == {"registry": "https://download.pytorch.org/whl/cu130"},
            "Torch index identity mismatch")
    require(any(wheel.get("url") == artifact["url"] and wheel.get("hash") == "sha256:" + artifact["sha256"]
                for wheel in torch[0]["wheels"]), "Torch artifact identity mismatch")
    owners = inspect_wheel(project, contract, private[0])
    frozen_path = project / "frozen_inputs.json"
    require(digest(frozen_path.read_bytes()) == contract["frozen_manifest_sha256"], "frozen manifest hash mismatch")
    frozen = json.loads(frozen_path.read_text(encoding="utf-8"))
    require(set(frozen) == FROZEN_FILES, "frozen file set mismatch")
    for name, checksum in frozen.items():
        path = project / name
        require(path.resolve().is_relative_to(project.resolve()) and digest(path.read_bytes()) == checksum,
                "frozen input hash mismatch")
    return sorted(requirements), {
        "audited_packages": len(requirements), "distributable_lock_entries": len(distributions),
        "private_source_owners_verified": owners, "frozen_files_verified": len(frozen),
        "public_version_projections": {name + "==" + version: base for (name, version), base in PUBLIC_BASES.items()},
        "advisory_projection_is_source_patch_proof": False,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project", type=Path, default=PILOT)
    parser.add_argument("--requirements", type=Path, required=True)
    args = parser.parse_args()
    requirements, evidence = inspect_project(args.project)
    with args.requirements.open("x", encoding="utf-8", newline="\n") as output:
        output.write("\n".join(requirements) + "\n")
    print(json.dumps(evidence, sort_keys=True))


if __name__ == "__main__":
    main()
