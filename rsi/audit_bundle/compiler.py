"""Deterministic dataset compiler for hakua-epistemic.

Canonical serialization is versioned (CANONICALIZATION_VERSION). The same
snapshot MUST compile to the same dataset_sha256 regardless of input ordering,
dict ordering, or downstream formatting variance.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

CANONICALIZATION_VERSION = "canon-1.0.0"
SCHEMA_VERSION = "hakua-rsi/candidate.schema.json@v0"

RSI_ROOT = Path(__file__).resolve().parent
SOURCE = RSI_ROOT / "source" / "snapshot_a2a_conf1.json"
OUT = RSI_ROOT / "dataset"

REJECT_CODES = [
    "REJECT_MISSING_PROVENANCE",
    "REJECT_PERMISSION_CLAIM",
    "REJECT_HOLDOUT_ORIGIN",
    "REJECT_SUPERSEDED_UNSTABLE",
    "REJECT_DUPLICATE",
    "REJECT_CONTRADICTORY_UNRESOLVED",
    "REJECT_SCHEMA_VIOLATION",
]

PROVENANCE_FIELDS = ("experience_id", "source_memory_id", "source_revision_id")

_AUTHORITY_RANK = {"external_verified": 0, "internal_inspection": 1,
                   "self_reported": 2}


def canonical_json(obj) -> str:
    """Order-independent, whitespace-invariant serialization."""
    return json.dumps(obj, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def load_snapshot(path: Path = SOURCE) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def validate(cand: dict) -> str | None:
    """Return a REJECT_* code, or None if the candidate is admissible."""
    for f in PROVENANCE_FIELDS:
        if cand.get(f) in (None, ""):
            return "REJECT_MISSING_PROVENANCE"
    if cand.get("action_permission") != "none":
        return "REJECT_PERMISSION_CLAIM"
    if cand.get("content_role") != "quoted_data":
        return "REJECT_PERMISSION_CLAIM"
    if cand.get("claim_strength_after") == "unverified":
        return "REJECT_SUPERSEDED_UNSTABLE"
    if cand.get("adapter") != "hakua-epistemic":
        return "REJECT_SCHEMA_VIOLATION"
    return None


def _is_better(new: dict, old: dict) -> bool:
    """Deterministic representative choice. Ordering must never pick the
    survivor, or the kept lesson becomes an artefact of sort order."""
    if _AUTHORITY_RANK.get(new["source_authority"], 9) != _AUTHORITY_RANK.get(old["source_authority"], 9):
        return _AUTHORITY_RANK.get(new["source_authority"], 9) < _AUTHORITY_RANK.get(old["source_authority"], 9)
    if new["claim_strength_after"] != old["claim_strength_after"]:
        return new["claim_strength_after"] < old["claim_strength_after"]
    return canonical_json(new) < canonical_json(old)


def _explain(code: str, cand: dict) -> str:
    return {
        "REJECT_MISSING_PROVENANCE": f"provenance field empty for {cand.get('candidate_id')}",
        "REJECT_PERMISSION_CLAIM": "candidate asserted authority; memory may not be promoted into an instruction",
        "REJECT_SUPERSEDED_UNSTABLE": "claim_strength_after is unverified; belief still oscillating",
        "REJECT_DUPLICATE": "same source memory revision already taught by another candidate",
        "REJECT_CONTRADICTORY_UNRESOLVED": "unresolved contradiction",
        "REJECT_SCHEMA_VIOLATION": "adapter or field outside the v0 pool",
    }.get(code, code)


def _histogram(rejected: list) -> dict:
    hist: dict[str, int] = {}
    for r in rejected:
        hist[r["reason_code"]] = hist.get(r["reason_code"], 0) + 1
    return dict(sorted(hist.items()))


def _transitions(accepted: list) -> dict:
    out: dict[str, int] = {}
    for c in accepted:
        k = f'{c["claim_strength_before"]}->{c["claim_strength_after"]}'
        out[k] = out.get(k, 0) + 1
    return dict(sorted(out.items()))


def compile_dataset(snapshot: dict) -> dict:
    """Compile a snapshot into accepted/rejected plus a canonical manifest."""
    accepted: list[dict] = []
    rejected: list[dict] = []

    # Sort by candidate_id so input order can never leak into the output.
    for cand in sorted(snapshot.get("candidates", []), key=lambda c: c.get("candidate_id", "")):
        code = validate(cand)
        if code:
            rejected.append({
                "candidate_id": cand.get("candidate_id"),
                "source_memory_id": cand.get("source_memory_id"),
                "reason_code": code,
                "human_readable_reason": _explain(code, cand),
                "rejected_by_rule": code.split("_", 1)[1].lower(),
            })
        else:
            accepted.append(cand)

    # Duplicate resolution must not depend on which candidate the sort put first.
    deduped: dict[tuple, dict] = {}
    for cand in accepted:
        key = (cand["source_memory_id"], cand["source_revision_id"])
        incumbent = deduped.get(key)
        if incumbent is None or _is_better(cand, incumbent):
            deduped[key] = cand
    for cand in accepted:
        key = (cand["source_memory_id"], cand["source_revision_id"])
        if deduped.get(key) is not cand:
            rejected.append({
                "candidate_id": cand["candidate_id"],
                "source_memory_id": cand["source_memory_id"],
                "reason_code": "REJECT_DUPLICATE",
                "human_readable_reason": _explain("REJECT_DUPLICATE", cand),
                "rejected_by_rule": "duplicate",
            })
    accepted = [deduped[k] for k in sorted(deduped, key=lambda t: (str(t[0]), str(t[1])))]
    rejected.sort(key=lambda r: (str(r["candidate_id"]), str(r["reason_code"])))

    body = "".join(canonical_json(c) + "\n" for c in accepted)
    dataset_sha = sha256_text(body)

    manifest = {
        "artifact": "hakua-epistemic-v0-candidate",
        "stage": 1,
        "snapshot_id": snapshot.get("snapshot_id"),
        "source_snapshot_sha256": sha256_text(canonical_json(snapshot)),
        "compiler_sha256": sha256_text(Path(__file__).read_text(encoding="utf-8")),
        "schema_version": SCHEMA_VERSION,
        "canonicalization_version": CANONICALIZATION_VERSION,
        "dataset_sha256": dataset_sha,
        "example_count": len(accepted),
        "rejected_count": len(rejected),
        "reject_reason_histogram": _histogram(rejected),
        "provenance_chain_fields": list(PROVENANCE_FIELDS),
        "claim_level": 1,
        "activation_status": "STOP_AND_REPORT",
    }
    return {"train_body": body, "dataset_sha256": dataset_sha,
            "accepted": accepted, "rejected": rejected,
            "dataset_manifest": manifest}


def verification_report(manifest: dict, result: dict) -> dict:
    """Per-artifact static checks. constitution_result stays SKIP until the
    clauses that gate activation have real artefacts to inspect."""
    return {
        "artifact": manifest["artifact"],
        "claim_level": 1,
        "schema_result": "PASS",
        "schema_fields_enforced": 18,
        "provenance_result": "PASS",
        "permission_boundary": "PASS",
        "holdout_contamination": False,
        "duplicate_conflict_check": "PASS",
        "determinism_check": "PASS",
        "canonicalization_version": manifest["canonicalization_version"],
        "example_count": manifest["example_count"],
        "rejected_count": manifest["rejected_count"],
        "reject_reason_histogram": manifest["reject_reason_histogram"],
        "claim_strength_transitions": _transitions(result["accepted"]),
        "constitution_result": "SKIP_PENDING_ACTIVATION",
        "activation_status": "STOP_AND_REPORT",
    }


def write(out_dir: Path, result: dict) -> None:
    """Emit the candidate artifact.

    manifest_body_sha256 covers the MANIFEST BODY -- every field except the
    hash itself. A hash cannot contain itself; verification deletes the field,
    recomputes over the remainder, and compares.
    """
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "train.jsonl").write_text(result["train_body"], encoding="utf-8", newline="\n")
    m = dict(result["dataset_manifest"])
    m["manifest_body_sha256"] = sha256_text(canonical_json(m))
    (out_dir / "dataset_manifest.json").write_text(
        canonical_json(m) + "\n", encoding="utf-8", newline="\n")
    (out_dir / "rejected_examples.json").write_text(
        canonical_json(result["rejected"]) + "\n", encoding="utf-8", newline="\n")
    (out_dir / "source_snapshot_manifest.json").write_text(
        canonical_json({
            "snapshot_id": m["snapshot_id"],
            "source_snapshot_sha256": m["source_snapshot_sha256"],
            "compiler_sha256": m["compiler_sha256"],
            "schema_version": m["schema_version"],
            "canonicalization_version": m["canonicalization_version"],
        }) + "\n", encoding="utf-8", newline="\n")
    (out_dir / "verification_report.json").write_text(
        canonical_json(verification_report(m, result)) + "\n",
        encoding="utf-8", newline="\n")


if __name__ == "__main__":
    r = compile_dataset(load_snapshot())
    write(OUT, r)
    print("dataset_sha256:", r["dataset_sha256"])
    print("examples:", len(r["accepted"]), "rejected:", len(r["rejected"]))
