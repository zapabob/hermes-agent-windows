"""Standalone Stage-1 compiler: quoted audit records, never training targets."""

from __future__ import annotations

import argparse
from collections import Counter
import copy
import hashlib
import json
import re
import sys
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator
from jsonschema.exceptions import SchemaError

ROOT = Path(__file__).resolve().parent
DEFAULT_SCHEMA = ROOT / "candidate.schema.json"
SCHEMA_SHA256 = "d68362022937269ef0340537641406e56580a369cada5871ad7ec29fa237f7f5"


def canonical_json(value: Any) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )


def sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


ARTIFACT = "hakua-epistemic-v0-candidate-r2"
PARENT_SHA256 = "5ab281294b79a33565e6f1b0705995a542cb0972b9847aa42278692c3af368aa"
REJECT_CODES = (
    "REJECT_MISSING_PROVENANCE",
    "REJECT_PERMISSION_CLAIM",
    "REJECT_HOLDOUT_ORIGIN",
    "REJECT_SUPERSEDED_UNSTABLE",
    "REJECT_DUPLICATE",
    "REJECT_CONTRADICTORY_UNRESOLVED",
    "REJECT_SCHEMA_VIOLATION",
)
AUTHORITY_RANK = {"external_verified": 0, "internal_inspection": 1, "self_reported": 2}
PROVENANCE_FIELDS = ("experience_id", "source_memory_id", "source_revision_id")


def rejection_code(value: Any, validator: Draft202012Validator) -> str | None:
    if not isinstance(value, dict):
        return "REJECT_SCHEMA_VIOLATION"
    for name in PROVENANCE_FIELDS:
        if (
            value.get(name) is None
            or value.get(name) == ""
            or (isinstance(value.get(name), str) and not value[name].strip())
        ):
            return "REJECT_MISSING_PROVENANCE"
    if value.get("action_permission") != "none" or value.get("content_role") != "quoted_data":
        return "REJECT_PERMISSION_CLAIM"
    if not isinstance(value.get("source_revision_id"), str) and type(value.get("source_revision_id")) is not int:
        return "REJECT_SCHEMA_VIOLATION"
    if list(validator.iter_errors(value)):
        return "REJECT_SCHEMA_VIOLATION"
    if value["claim_strength_after"] == "unverified":
        return "REJECT_SUPERSEDED_UNSTABLE"
    return None


def load_validator(schema_path: str | Path | None = None) -> Draft202012Validator:
    schema = load_snapshot(Path(schema_path or DEFAULT_SCHEMA))
    Draft202012Validator.check_schema(schema)
    if sha256_text(canonical_json(schema)) != SCHEMA_SHA256:
        raise ValueError("Unknown or changed schema contract")
    return Draft202012Validator(schema)


def input_errors(snapshot: Any) -> list[str]:
    try:
        canonical_json(snapshot)
    except (ValueError, TypeError, RecursionError) as exc:
        return ["Snapshot is not finite JSON: " + str(exc)]
    if not isinstance(snapshot, dict):
        return ["Snapshot must be an object"]
    if not isinstance(snapshot.get("snapshot_id"), str) or not snapshot["snapshot_id"].strip():
        return ["Snapshot requires a nonempty snapshot_id"]
    if not isinstance(snapshot.get("candidates"), list):
        return ["Snapshot candidates must be a list"]
    registry = snapshot.get("holdout_registry")
    if not isinstance(registry, list) or any(not isinstance(x, str) or not x.strip() for x in registry):
        return ["Snapshot requires holdout_registry: a list of nonempty IDs"]
    return []


def record_key(value: Any) -> tuple[str, str | int] | None:
    if not isinstance(value, dict):
        return None
    parts = (value.get("source_memory_id"), value.get("source_revision_id"))
    memory, revision = parts
    revision_ok = isinstance(revision, str) and bool(revision.strip()) or type(revision) is int and revision > 0
    return parts if isinstance(memory, str) and memory.strip() and revision_ok else None


def conflict_keys(records: list[Any]) -> set[tuple[str, str | int]]:
    claims, flagged = {}, set()
    for value in records:
        key = record_key(value)
        if key is None:
            continue
        if value.get("contradictory_unresolved") is True:
            flagged.add(key)
        if isinstance(value.get("revised_claim"), str):
            claims.setdefault(key, set()).add(value["revised_claim"])
    return flagged | {key for key, values in claims.items() if len(values) > 1}


def compile_dataset(snapshot: Any, schema_path: str | Path | None = None) -> dict[str, Any]:
    result = {
        "accepted": [],
        "rejected": [],
        "input_errors": input_errors(snapshot),
        "schema_errors": [],
    }
    try:
        validator = load_validator(schema_path)
    except (OSError, ValueError, TypeError, SchemaError, RecursionError) as exc:
        result["schema_errors"] = [str(exc)]
        return finalize(snapshot, result)
    if result["input_errors"]:
        return finalize(snapshot, result)
    conflicts = conflict_keys(snapshot["candidates"])
    for value in snapshot["candidates"]:
        code = rejection_code(value, validator)
        if record_key(value) in conflicts:
            code = "REJECT_CONTRADICTORY_UNRESOLVED"
        if code is None and (
            value["holdout_origin"]
            or value["experience_id"] in snapshot["holdout_registry"]
            or value["source_memory_id"] in snapshot["holdout_registry"]
        ):
            code = "REJECT_HOLDOUT_ORIGIN"
        if code:
            result["rejected"].append(
                {
                    "candidate_id": (value.get("candidate_id") if isinstance(value, dict) else None),
                    "reason_code": code,
                }
            )
        else:
            result["accepted"].append(copy.deepcopy(value))
    winners = {}
    for value in sorted(
        result["accepted"],
        key=lambda x: (
            AUTHORITY_RANK[x["source_authority"]],
            x["claim_strength_after"],
            canonical_json(x).encode("utf-8"),
        ),
    ):
        key = record_key(value)
        if key in winners:
            result["rejected"].append(
                {
                    "candidate_id": value["candidate_id"],
                    "reason_code": "REJECT_DUPLICATE",
                }
            )
        else:
            winners[key] = value
    result["accepted"] = [winners[key] for key in sorted(winners, key=lambda x: canonical_json(x).encode("utf-8"))]
    result["rejected"].sort(key=lambda x: canonical_json(x).encode("utf-8"))
    return finalize(snapshot, result)


def dataset_body(records: list[Any]) -> str:
    return "".join(canonical_json(value) + "\n" for value in records)


def finalize(snapshot: Any, result: dict[str, Any]) -> dict[str, Any]:
    result["train_body"] = dataset_body(result["accepted"])
    result["dataset_sha256"] = sha256_text(result["train_body"])
    try:
        snapshot_sha = sha256_text(canonical_json(snapshot))
    except (ValueError, TypeError, RecursionError):
        snapshot_sha = None
    manifest = {
        "artifact": ARTIFACT,
        "artifact_revision": 2,
        "stage": 1,
        "parent_artifact_sha256": PARENT_SHA256,
        "parent_audit_verdict": "NEEDS_REVISION",
        "independent_artifact_audit": "PENDING",
        "human_approval": "PENDING",
        "activation_status": "STOP_AND_REPORT",
        "training_status": "NOT_STARTED",
        "snapshot_id": (snapshot.get("snapshot_id") if isinstance(snapshot, dict) else None),
        "source_snapshot_sha256": snapshot_sha,
        "schema_sha256": SCHEMA_SHA256,
        "compiler_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "canonicalization_version": "canon-1.0.0",
        "schema_version": "hakua-rsi/r2/candidate.schema.json",
        "dataset_sha256": result["dataset_sha256"],
        "example_count": len(result["accepted"]),
        "rejected_count": len(result["rejected"]),
        "reject_reason_histogram": dict(sorted(Counter(x["reason_code"] for x in result["rejected"]).items())),
        "provenance_chain_fields": list(PROVENANCE_FIELDS),
        "dataset_role": "quoted_audit_data_not_assistant_targets",
    }
    manifest["manifest_body_sha256"] = sha256_text(canonical_json(manifest))
    result["dataset_manifest"] = manifest
    return result


REQUIRED_CHECKS = (
    "schema_integrity",
    "input_filtering",
    "accepted_output_schema",
    "structural_provenance",
    "source_provenance",
    "permission_boundary",
    "holdout_registry",
    "holdout_exclusion",
    "contradiction_exclusion",
    "duplicate_exclusion",
    "output_integrity",
    "nonempty_dataset",
    "determinism",
    "required_check_coverage",
    "independent_artifact_audit",
    "human_approval",
    "activation",
)
GATE_CHECKS = {"independent_artifact_audit", "human_approval", "activation"}


def check(status: str, details: Any) -> dict[str, Any]:
    return {"status": status, "details": details}


def complete_checks(checks: dict[str, Any]) -> dict[str, Any]:
    output = copy.deepcopy(checks)
    missing = []
    for name in REQUIRED_CHECKS:
        if name == "required_check_coverage":
            continue
        entry = output.get(name)
        if (
            not isinstance(entry, dict)
            or entry.get("status") not in {"PASS", "FAIL", "SKIP", "ERROR"}
            or not entry.get("details")
        ):
            missing.append(name)
            output[name] = check("ERROR", ["Required check missing or malformed"])
    output["required_check_coverage"] = check(
        "ERROR" if missing else "PASS",
        {"missing_or_malformed": missing, "required": list(REQUIRED_CHECKS)},
    )
    return output


def verification_report(
    snapshot: Any,
    result: Any,
    schema_path: str | Path | None = None,
    evidence_root: str | Path | None = None,
    source_provenance_path: str | Path | None = None,
) -> dict[str, Any]:
    """Execute checks against output; source evidence and approval are distinct gates."""
    checks = {}
    accepted = result.get("accepted") if isinstance(result, dict) else None
    records_ok = isinstance(accepted, list)
    records = accepted if records_ok else []
    errors = input_errors(snapshot)
    fresh = compile_dataset(snapshot, schema_path)
    try:
        validator = load_validator(schema_path)
        checks["schema_integrity"] = check(
            "PASS",
            {"schema_sha256": SCHEMA_SHA256, "validator": "Draft202012Validator"},
        )
    except (OSError, ValueError, TypeError, SchemaError, RecursionError) as exc:
        validator = None
        checks["schema_integrity"] = check("ERROR", [str(exc)])
    filtering = not errors and not fresh["schema_errors"] and isinstance(result, dict)
    if filtering:
        filtering = result.get("accepted") == fresh["accepted"] and result.get("rejected") == fresh["rejected"]
        checks["input_filtering"] = check(
            "PASS" if filtering else "FAIL",
            {"rejected_count": len(fresh["rejected"]), "recomputed_matches": filtering},
        )
    else:
        checks["input_filtering"] = check("ERROR", errors + fresh["schema_errors"] or ["Malformed result"])
    checks["nonempty_dataset"] = check("PASS" if records_ok and records else "FAIL", {"accepted_count": len(records)})
    if validator is None:
        checks["accepted_output_schema"] = check("ERROR", ["Schema unavailable"])
    elif not records_ok:
        checks["accepted_output_schema"] = check("FAIL", ["Accepted output must be a list"])
    elif not records:
        checks["accepted_output_schema"] = check("SKIP", ["No accepted records to validate"])
    else:
        violations = [
            {"index": i, "path": list(error.path), "message": error.message}
            for i, value in enumerate(records)
            for error in validator.iter_errors(value)
        ]
        violations.extend(
            {
                "index": i,
                "path": ["source_revision_id"],
                "message": "Revision ID must retain a string or integer literal",
            }
            for i, value in enumerate(records)
            if isinstance(value, dict)
            and not isinstance(value.get("source_revision_id"), str)
            and type(value.get("source_revision_id")) is not int
        )
        checks["accepted_output_schema"] = check(
            "FAIL" if violations else "PASS",
            {"validated_records": len(records), "violations": violations},
        )
    schema_ok = checks["accepted_output_schema"]["status"] == "PASS"
    source_records = snapshot.get("candidates", []) if isinstance(snapshot, dict) else []
    if schema_ok and not errors:
        linked = all(value in source_records and value["snapshot_id"] == snapshot["snapshot_id"] for value in records)
        checks["structural_provenance"] = check("PASS" if linked else "FAIL", {"exact_snapshot_linkage": linked})
        permissions_ok = all(
            value["action_permission"] == "none" and value["content_role"] == "quoted_data" for value in records
        )
        checks["permission_boundary"] = check("PASS" if permissions_ok else "FAIL", {"quoted_only": permissions_ok})
    else:
        for name in ["structural_provenance", "permission_boundary"]:
            checks[name] = check("ERROR", ["Output schema or snapshot unavailable"])
    registry = snapshot.get("holdout_registry") if isinstance(snapshot, dict) else None
    registry_ok = isinstance(registry, list) and all(isinstance(x, str) and x.strip() for x in registry)
    checks["holdout_registry"] = check("PASS" if registry_ok else "ERROR", {"registry_available": registry_ok})
    if schema_ok and registry_ok and not errors:
        contamination = any(
            value["holdout_origin"] or value["experience_id"] in registry or value["source_memory_id"] in registry
            for value in records
        )
        checks["holdout_exclusion"] = check("FAIL" if contamination else "PASS", {"contamination": contamination})
        conflicts = conflict_keys(source_records)
        unresolved = any(value["contradictory_unresolved"] or record_key(value) in conflicts for value in records)
        keys = [record_key(value) for value in records]
        checks["contradiction_exclusion"] = check(
            "FAIL" if unresolved else "PASS", {"unresolved_in_output": unresolved}
        )
        checks["duplicate_exclusion"] = check(
            "PASS" if len(set(keys)) == len(keys) else "FAIL",
            {"unique_keys": len(set(keys)), "records": len(keys)},
        )
    else:
        for name in [
            "holdout_exclusion",
            "contradiction_exclusion",
            "duplicate_exclusion",
        ]:
            checks[name] = check("ERROR", ["Output schema, snapshot or holdout registry unavailable"])
    checks["source_provenance"] = (
        source_provenance_check(records, Path(evidence_root or ROOT), source_provenance_path)
        if schema_ok
        else check("ERROR", ["Valid nonempty output required for source verification"])
    )
    try:
        body = dataset_body(records)
        body_sha = sha256_text(body)
        manifest = result.get("dataset_manifest", {}) if isinstance(result, dict) else {}
        manifest_body = {key: value for key, value in manifest.items() if key != "manifest_body_sha256"}
        integrity = records_ok and isinstance(result, dict) and result == fresh and body == result.get("train_body")
        integrity = integrity and body_sha == result.get("dataset_sha256") == manifest.get("dataset_sha256")
        integrity = integrity and manifest.get("manifest_body_sha256") == sha256_text(canonical_json(manifest_body))
        checks["output_integrity"] = check(
            "PASS" if integrity else "FAIL",
            {
                "recomputed_dataset_sha256": body_sha,
                "matches_recompiled_output": integrity,
            },
        )
    except (ValueError, TypeError, AttributeError, RecursionError) as exc:
        checks["output_integrity"] = check("FAIL", ["Malformed output: " + str(exc)])
    repeated = compile_dataset(copy.deepcopy(snapshot), schema_path)
    if errors or fresh["schema_errors"] or repeated["input_errors"] or repeated["schema_errors"]:
        checks["determinism"] = check("ERROR", ["Cannot verify determinism with invalid source or schema"])
    elif not fresh["accepted"]:
        checks["determinism"] = check("SKIP", ["Empty output cannot establish a useful determinism result"])
    else:
        bodies_equal = fresh["train_body"] == repeated["train_body"]
        hashes = [sha256_text(fresh["train_body"]), sha256_text(repeated["train_body"])]
        same = bodies_equal and hashes[0] == hashes[1] == fresh["dataset_sha256"] == repeated["dataset_sha256"]
        same = same and fresh["accepted"] == repeated["accepted"] and fresh["rejected"] == repeated["rejected"]
        checks["determinism"] = check(
            "PASS" if same else "FAIL",
            {
                "compilation_runs": 2,
                "bodies_equal": bodies_equal,
                "dataset_hashes": hashes,
            },
        )
    for name in GATE_CHECKS:
        checks[name] = check(
            "SKIP",
            ["PENDING independent artifact audit and explicit human approval; no activation"],
        )
    checks = complete_checks(checks)
    failed = any(entry["status"] in {"ERROR", "FAIL"} for name, entry in checks.items() if name not in GATE_CHECKS)
    pair = [checks[name]["status"] for name in ["contradiction_exclusion", "duplicate_exclusion"]]
    return {
        "artifact": ARTIFACT,
        "artifact_revision": 2,
        "checks": checks,
        "required_checks": list(REQUIRED_CHECKS),
        "schema_result": (
            checks["accepted_output_schema"]["status"]
            if checks["accepted_output_schema"]["status"] in {"PASS", "FAIL"}
            else None
        ),
        "source_provenance_result": checks["source_provenance"]["status"],
        "provenance_result": checks["structural_provenance"]["status"],
        "holdout_contamination": (
            checks["holdout_exclusion"]["details"].get("contamination")
            if isinstance(checks["holdout_exclusion"]["details"], dict)
            else None
        ),
        "duplicate_conflict_check": ("FAIL" if "FAIL" in pair else "PASS" if pair == ["PASS", "PASS"] else None),
        "determinism_check": checks["determinism"]["status"],
        "example_count": len(records),
        "rejected_count": len(fresh["rejected"]),
        "reject_reason_histogram": fresh["dataset_manifest"]["reject_reason_histogram"],
        "engineering_result": "NEEDS_REVISION" if failed else "PASS",
        "verification_result": ("NEEDS_REVISION" if failed else "PENDING_INDEPENDENT_AUDIT"),
        "independent_artifact_audit": "PENDING",
        "human_approval": "PENDING",
        "activation_status": "STOP_AND_REPORT",
        "training_status": "NOT_STARTED",
    }


def resolve_ref(root: Path, ref: Any) -> Path:
    """Resolve only bundle-local regular files; never fetch URLs or escape root."""
    if not isinstance(ref, str) or not re.fullmatch(r"[A-Za-z0-9_.\-/]+", ref) or ref.startswith("/"):
        raise ValueError("Evidence reference must be a safe relative path")
    if any(part in {"", ".", ".."} for part in ref.split("/")):
        raise ValueError("Evidence reference contains traversal or empty segments")
    root = Path(root).resolve()
    path = (root / ref).resolve()
    if not path.is_relative_to(root):
        raise ValueError("Evidence reference escapes bundle root")
    if not path.is_file():
        raise FileNotFoundError("Missing evidence: " + ref)
    return path


def source_provenance_check(
    records: list[dict[str, Any]], root: Path, resolution_path: str | Path | None = None
) -> dict[str, Any]:
    if not records or any(value["source_record_status"] != "resolved" for value in records):
        return check("ERROR", ["Source memory/revision resolution is absent or unresolved"])
    path = Path(resolution_path) if resolution_path is not None else root / "source_provenance.json"
    try:
        resolution = load_snapshot(path)
        entries = resolution.get("records") if isinstance(resolution, dict) else None
        if not isinstance(entries, list) or not all(isinstance(entry, dict) for entry in entries):
            return check(
                "ERROR",
                ["Source provenance requires a records list of resolution entries"],
            )
    except (OSError, ValueError, TypeError) as exc:
        return check("ERROR", ["Source provenance unavailable: " + str(exc)])
    errors, failures, verified = [], [], []
    for value in records:
        matches = [entry for entry in entries if all(entry.get(name) == value[name] for name in PROVENANCE_FIELDS)]
        if len(matches) != 1 or matches[0].get("status") != "resolved":
            errors.append("No unique resolved source entry for " + value["candidate_id"])
            continue
        entry = matches[0]
        if entry.get("evidence_refs") != value["evidence_refs"]:
            failures.append("Evidence reference linkage mismatch for " + value["candidate_id"])
            continue
        hashes = entry.get("file_sha256")
        if not isinstance(hashes, dict):
            errors.append("File digest bindings missing for " + value["candidate_id"])
            continue
        refs = list(value["evidence_refs"]) + [
            entry.get("memory_record_ref"),
            entry.get("revision_record_ref"),
        ]
        paths = {}
        for ref in refs:
            try:
                evidence = resolve_ref(root, ref)
                expected = hashes.get(ref)
                if not isinstance(expected, str) or not re.fullmatch("[0-9a-f]{64}", expected):
                    errors.append("Missing or invalid file digest for " + str(ref))
                    continue
                actual = hashlib.sha256(evidence.read_bytes()).hexdigest()
                if expected != actual:
                    failures.append("Evidence digest mismatch for " + ref)
                paths[ref] = evidence
            except (OSError, ValueError, TypeError) as exc:
                errors.append(str(exc))
        try:
            memory_ref, revision_ref = entry.get("memory_record_ref"), entry.get("revision_record_ref")
            if memory_ref not in paths or revision_ref not in paths:
                continue
            memory = load_snapshot(paths[memory_ref])
            revision = load_snapshot(paths[revision_ref])
            memory_fields = ("experience_id", "source_memory_id", "previous_claim")
            revision_fields = (
                "source_memory_id",
                "source_revision_id",
                "new_evidence",
                "revised_claim",
            )
            linked = isinstance(memory, dict) and isinstance(revision, dict)
            linked = linked and all(memory.get(name) == value[name] for name in memory_fields)
            linked = linked and all(revision.get(name) == value[name] for name in revision_fields)
            if not linked:
                failures.append("Primary memory/revision contents do not match " + value["candidate_id"])
            else:
                verified.append(value["candidate_id"])
        except (OSError, ValueError, TypeError) as exc:
            errors.append("Primary records unavailable: " + str(exc))
    return check(
        "ERROR" if errors else "FAIL" if failures else "PASS",
        {
            "verified_candidates": verified,
            "errors": errors,
            "failures": failures,
            "scope": "Local export linkage and digests, not independent source authenticity or causal audit",
        },
    )


def unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    output = {}
    for key, value in pairs:
        if key in output:
            raise ValueError("Duplicate JSON key: " + key)
        output[key] = value
    return output


def reject_constant(value: str) -> None:
    raise ValueError("Nonfinite JSON constant: " + value)


def load_snapshot(path: str | Path = ROOT / "source_snapshot.json") -> Any:
    return json.loads(
        Path(path).read_text(encoding="utf-8"),
        object_pairs_hook=unique_object,
        parse_constant=reject_constant,
    )


def write(out_dir: str | Path, result: dict[str, Any], report: dict[str, Any]) -> None:
    """Write quoted Stage-1 data, not executable prompts or Stage-2 targets."""
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "train.jsonl").write_text(result["train_body"], encoding="utf-8", newline="\n")
    files = {
        "dataset_manifest.json": result["dataset_manifest"],
        "rejected_examples.json": result["rejected"],
        "verification_report.json": report,
        "source_snapshot_manifest.json": {
            name: result["dataset_manifest"][name]
            for name in [
                "snapshot_id",
                "source_snapshot_sha256",
                "compiler_sha256",
                "schema_sha256",
                "canonicalization_version",
            ]
        },
    }
    for name, value in files.items():
        (out_dir / name).write_text(canonical_json(value) + "\n", encoding="utf-8", newline="\n")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, default=ROOT / "source_snapshot.json")
    parser.add_argument("--out", type=Path, default=ROOT / "dataset")
    parser.add_argument("--schema", type=Path, default=DEFAULT_SCHEMA)
    parser.add_argument("--evidence-root", type=Path)
    parser.add_argument("--source-provenance", type=Path)
    args = parser.parse_args(argv)
    try:
        source = load_snapshot(args.source)
        result = compile_dataset(source, args.schema)
        report = verification_report(
            source,
            result,
            args.schema,
            args.evidence_root or args.source.resolve().parent,
            args.source_provenance,
        )
        write(args.out, result, report)
        summary = {
            "artifact": ARTIFACT,
            "dataset_sha256": result["dataset_sha256"],
            "example_count": len(result["accepted"]),
            "rejected_count": len(result["rejected"]),
            "verification_result": report["verification_result"],
            "out": str(args.out),
            "activation_status": "STOP_AND_REPORT",
        }
        sys.stdout.write(canonical_json(summary) + "\n")
        return 2 if report["engineering_result"] != "PASS" else 0
    except (OSError, ValueError, TypeError, RecursionError) as exc:
        sys.stdout.write(
            canonical_json(
                {
                    "status": "ERROR",
                    "verification_result": "NEEDS_REVISION",
                    "error": str(exc),
                    "activation_status": "STOP_AND_REPORT",
                }
            )
            + "\n"
        )
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
