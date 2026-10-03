"""Standalone regression tests; all records here are synthetic fixtures."""
import hashlib
import copy
import itertools
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

import compiler

ROOT = Path(__file__).resolve().parent


def candidate(**updates):
    value = {
        "candidate_id": "fixture-candidate-a", "experience_id": "fixture-experience-a",
        "source_memory_id": "fixture-memory-a", "source_revision_id": "fixture-revision-a",
        "snapshot_id": "fixture-snapshot", "previous_claim": "An unsupported assertion.",
        "claim_strength_before": "asserted", "new_evidence": "Synthetic counterexample.",
        "revised_claim": "The claim needs qualification.", "claim_strength_after": "hedged",
        "revision_reason": "A counterexample narrows the claim.",
        "superseded_lineage": "fixture-initial->fixture-revision-a",
        "desired_behavior": "Qualify claims according to evidence.", "evidence_kind": "counterexample",
        "source_authority": "self_reported", "content_role": "quoted_data",
        "action_permission": "none", "adapter": "hakua-epistemic",
        "holdout_origin": False, "contradictory_unresolved": False,
        "evidence_refs": ["evidence/fixture.json"], "source_record_status": "unresolved",
    }
    value.update(updates)
    return value


def snapshot(*records):
    return {"snapshot_id": "fixture-snapshot", "holdout_registry": [],
            "candidates": list(records) if records else [candidate()]}


class CompilerTests(unittest.TestCase):
    def test_valid_candidate_compiles_with_shipped_22_field_schema(self):
        value = candidate()
        result = compiler.compile_dataset(snapshot(value))
        self.assertEqual([value], result["accepted"])
        from jsonschema import Draft202012Validator
        schema = json.loads((ROOT / "candidate.schema.json").read_text(encoding="utf-8"))
        Draft202012Validator.check_schema(schema)
        self.assertEqual(22, len(schema["required"]))
        self.assertEqual([], list(Draft202012Validator(schema).iter_errors(result["accepted"][0])))

    def test_legacy_provenance_permission_and_unstable_rejection(self):
        cases = [
            ({"experience_id": " "}, "REJECT_MISSING_PROVENANCE"),
            ({"source_memory_id": None}, "REJECT_MISSING_PROVENANCE"),
            ({"source_revision_id": ""}, "REJECT_MISSING_PROVENANCE"),
            ({"action_permission": "execute"}, "REJECT_PERMISSION_CLAIM"),
            ({"content_role": "system"}, "REJECT_PERMISSION_CLAIM"),
            ({"claim_strength_after": "unverified"}, "REJECT_SUPERSEDED_UNSTABLE"),
        ]
        for changes, code in cases:
            with self.subTest(changes=changes):
                result = compiler.compile_dataset(snapshot(candidate(**changes)))
                self.assertEqual([], result["accepted"])
                self.assertEqual(code, result["rejected"][0]["reason_code"])

    def test_malformed_snapshot_and_nonobject_records_fail_closed(self):
        for value in [None, [], {}, {"candidates": {}}, snapshot(candidate(new_evidence=float("nan")))]:
            with self.subTest(value=value):
                try:
                    result = compiler.compile_dataset(value)
                except Exception as exc:
                    self.fail("Malformed input must return explicit errors: " + repr(exc))
                self.assertEqual([], result["accepted"])
                self.assertTrue(result["input_errors"])
        for value in [None, [], 7, "raw instruction"]:
            with self.subTest(record=value):
                try:
                    result = compiler.compile_dataset(snapshot(value))
                except Exception as exc:
                    self.fail("Nonobject candidate must be rejected: " + repr(exc))
                self.assertEqual("REJECT_SCHEMA_VIOLATION", result["rejected"][0]["reason_code"])

    def test_unknown_broken_or_weakened_schema_fail_closed(self):
        original = json.loads((ROOT / "candidate.schema.json").read_text(encoding="utf-8"))
        weakened = copy.deepcopy(original)
        weakened["required"].remove("holdout_origin")
        wrong_type = copy.deepcopy(original)
        wrong_type["properties"]["holdout_origin"]["type"] = "string"
        wrong_const = copy.deepcopy(original)
        wrong_const["properties"]["action_permission"]["const"] = "execute"
        extra = copy.deepcopy(original)
        extra["additionalProperties"] = True
        for schema in [{}, {"type": "nonexistent"}, weakened, wrong_type, wrong_const, extra]:
            with tempfile.TemporaryDirectory() as directory, self.subTest(schema=schema):
                path = Path(directory) / "schema.json"
                path.write_text(json.dumps(schema), encoding="utf-8")
                try:
                    result = compiler.compile_dataset(snapshot(), path)
                except Exception as exc:
                    self.fail("Schema failure must be explicit: " + repr(exc))
                self.assertEqual([], result["accepted"])
                self.assertTrue(result["schema_errors"])
        for name in ["missing.json", "broken.json"]:
            with tempfile.TemporaryDirectory() as directory:
                path = Path(directory) / name
                if name == "broken.json":
                    path.write_text("{", encoding="utf-8")
                try:
                    result = compiler.compile_dataset(snapshot(), path)
                except Exception as exc:
                    self.fail("Missing/broken schema must fail closed: " + repr(exc))
                self.assertTrue(result["schema_errors"])

    def test_schema_negative_mutations_use_actual_types_and_all_required_fields(self):
        base = candidate()
        for name in base:
            value = copy.deepcopy(base)
            del value[name]
            self.assertEqual([], compiler.compile_dataset(snapshot(value))["accepted"], name)
        for changes in [
            {"holdout_origin": "false"}, {"contradictory_unresolved": 0},
            {"evidence_refs": "evidence/file.json"}, {"source_record_status": "trusted"},
            {"source_memory_id": 42}, {"source_revision_id": True}, {"candidate_id": " "},
            {"adapter": "other"}, {"extra": "not allowed"}, {"previous_claim": 5},
            {"evidence_refs": ["../outside.json"]}, {"evidence_refs": ["C:/secret"]},
            {"evidence_refs": []}, {"evidence_refs": ["https://example.test"]},
        ]:
            with self.subTest(changes=changes):
                self.assertEqual([], compiler.compile_dataset(snapshot(candidate(**changes)))["accepted"])

    def test_holdout_flag_and_registry_membership_reject(self):
        for flag, registry in [(True, []), (False, ["fixture-experience-a"]),
                               (False, ["fixture-memory-a"])]:
            source = snapshot(candidate(holdout_origin=flag))
            source["holdout_registry"] = registry
            result = compiler.compile_dataset(source)
            self.assertEqual([], result["accepted"])
            self.assertEqual("REJECT_HOLDOUT_ORIGIN", result["rejected"][0]["reason_code"])

    def test_missing_or_invalid_holdout_registry_is_an_error(self):
        for registry in [None, "fixture-experience-a", [None], [" "]]:
            source = snapshot()
            if registry is None:
                del source["holdout_registry"]
            else:
                source["holdout_registry"] = registry
            result = compiler.compile_dataset(source)
            self.assertEqual([], result["accepted"])
            self.assertTrue(result["input_errors"])

    def test_flagged_unresolved_contradiction_rejects(self):
        result = compiler.compile_dataset(snapshot(candidate(contradictory_unresolved=True)))
        self.assertEqual([], result["accepted"])
        self.assertEqual("REJECT_CONTRADICTORY_UNRESOLVED", result["rejected"][0]["reason_code"])

    def test_conflicting_revised_claims_reject_every_member_before_dedup(self):
        records = [candidate(), candidate(candidate_id="fixture-candidate-b", revised_claim="Opposite claim.",
                                          source_authority="external_verified")]
        for order in itertools.permutations(records):
            result = compiler.compile_dataset(snapshot(*order))
            self.assertEqual([], result["accepted"])
            self.assertEqual(["REJECT_CONTRADICTORY_UNRESOLVED"] * 2,
                             [x["reason_code"] for x in result["rejected"]])
        invalid = candidate(candidate_id="fixture-candidate-b", revised_claim="Opposite claim.", extra="invalid")
        self.assertEqual([], compiler.compile_dataset(snapshot(candidate(), invalid))["accepted"])

    def test_duplicate_winner_is_canonical_bytes_and_revision_is_part_of_key(self):
        records = [candidate(candidate_id="fixture-candidate-z"), candidate(),
                   candidate(candidate_id="fixture-candidate-revision-b", source_revision_id="fixture-revision-b"),
                   candidate(candidate_id="fixture-candidate-memory-b", source_memory_id="fixture-memory-b")]
        bodies, hashes = set(), set()
        for order in itertools.permutations(records):
            result = compiler.compile_dataset(snapshot(*order))
            self.assertEqual(3, len(result["accepted"]))
            self.assertEqual(["REJECT_DUPLICATE"], [x["reason_code"] for x in result["rejected"]])
            self.assertIn("fixture-candidate-a", [x["candidate_id"] for x in result["accepted"]])
            bodies.add(result["train_body"])
            hashes.add(result["dataset_sha256"])
        self.assertEqual(1, len(bodies))
        self.assertEqual(1, len(hashes))
        same = compiler.compile_dataset(snapshot(candidate(), candidate()))
        self.assertEqual(1, len(same["accepted"]))
        self.assertEqual(1, len(same["rejected"]))

    def test_manifest_preserves_revision_and_unapproved_gates(self):
        manifest = compiler.compile_dataset(snapshot()).get("dataset_manifest", {})
        self.assertEqual("hakua-epistemic-v0-candidate-r2", manifest.get("artifact"))
        self.assertEqual(2, manifest.get("artifact_revision"))
        self.assertEqual("5ab281294b79a33565e6f1b0705995a542cb0972b9847aa42278692c3af368aa", manifest.get("parent_sha256"))
        self.assertEqual("NEEDS_REVISION", manifest.get("parent_audit_verdict"))
        self.assertEqual("PENDING", manifest.get("independent_artifact_audit"))
        self.assertEqual("PENDING", manifest.get("human_approval"))
        self.assertEqual("STOP_AND_REPORT", manifest.get("activation_status"))

    def test_shipped_negative_fixtures_exercise_all_seven_reject_codes(self):
        self.assertTrue((ROOT / "fixtures.json").is_file(), "Runnable synthetic negative fixtures must ship")
        fixtures = json.loads((ROOT / "fixtures.json").read_text(encoding="utf-8"))
        self.assertTrue(fixtures["synthetic_only"])
        observed = set()
        for case in fixtures["cases"]:
            with self.subTest(name=case["name"]):
                result = compiler.compile_dataset(case["snapshot"])
                codes = [x["reason_code"] for x in result["rejected"]]
                self.assertEqual(case["expected_reject_codes"], codes)
                self.assertEqual(case["expected_accepted"], len(result["accepted"]))
                observed.update(codes)
        self.assertEqual(set(compiler.REJECT_CODES), observed)

    def test_report_has_complete_executed_checks_and_separates_filtering_from_schema(self):
        report_fn = getattr(compiler, "verification_report", lambda *a, **kw: {})
        source = snapshot(candidate(), candidate(candidate_id="fixture-invalid", evidence_refs="bad"))
        report = report_fn(source, compiler.compile_dataset(source))
        required = {"schema_integrity", "input_filtering", "accepted_output_schema", "structural_provenance",
                    "source_provenance", "permission_boundary", "holdout_registry", "holdout_exclusion",
                    "contradiction_exclusion", "duplicate_exclusion", "output_integrity", "nonempty_dataset",
                    "determinism", "required_check_coverage", "independent_artifact_audit", "human_approval", "activation"}
        self.assertEqual(required, set(report.get("checks", {})))
        self.assertEqual("PASS", report["checks"]["input_filtering"]["status"])
        self.assertEqual("PASS", report["checks"]["accepted_output_schema"]["status"])
        self.assertEqual("PASS", report["schema_result"])
        self.assertFalse(report["holdout_contamination"])
        self.assertEqual("PASS", report["duplicate_conflict_check"])
        self.assertEqual("ERROR", report["source_provenance_result"])
        self.assertEqual("NEEDS_REVISION", report["verification_result"])
        for entry in report["checks"].values():
            self.assertIn(entry["status"], {"PASS", "FAIL", "SKIP", "ERROR"})
            self.assertTrue(entry["details"])
        self.assertEqual("PENDING", report["independent_artifact_audit"])
        self.assertEqual("PENDING", report["human_approval"])

    def test_empty_or_unavailable_checks_cannot_claim_all_pass(self):
        report_fn = getattr(compiler, "verification_report", lambda *a, **kw: {})
        source = snapshot()
        del source["holdout_registry"]
        report = report_fn(source, compiler.compile_dataset(source))
        self.assertEqual("ERROR", report.get("checks", {}).get("holdout_registry", {}).get("status"))
        self.assertIsNone(report["holdout_contamination"])
        self.assertIsNone(report["duplicate_conflict_check"])
        source = snapshot()
        source["candidates"] = []
        report = report_fn(source, compiler.compile_dataset(source))
        self.assertEqual("FAIL", report["checks"]["nonempty_dataset"]["status"])
        self.assertIsNone(report["schema_result"])
        self.assertEqual("NEEDS_REVISION", report["verification_result"])

    def test_missing_required_check_is_error_not_pass(self):
        coverage_fn = getattr(compiler, "complete_checks", lambda checks: checks)
        checks = coverage_fn({})
        self.assertEqual("ERROR", checks.get("required_check_coverage", {}).get("status"))
        self.assertEqual("ERROR", checks["holdout_exclusion"]["status"])

    def test_report_recompiles_twice_compares_real_bodies_and_hashes(self):
        from unittest.mock import patch
        source = snapshot()
        result = compiler.compile_dataset(source)
        with patch.object(compiler, "compile_dataset", wraps=compiler.compile_dataset) as wrapped:
            report = compiler.verification_report(source, result)
        self.assertEqual("PASS", report["determinism_check"])
        self.assertEqual(2, wrapped.call_count)
        details = report["checks"]["determinism"]["details"]
        self.assertEqual(2, details["compilation_runs"])
        self.assertTrue(details["bodies_equal"])
        self.assertEqual([result["dataset_sha256"]] * 2, details["dataset_hashes"])
        self.assertEqual("PASS", report["checks"]["output_integrity"]["status"])

    def test_postcompile_accepted_body_hash_or_manifest_tampering_cannot_pass(self):
        source = snapshot()
        original = compiler.compile_dataset(source)
        changes = [
            lambda r: r["accepted"][0].update({"revised_claim": "A tampered but schema-valid claim."}),
            lambda r: r["accepted"][0].update({"holdout_origin": True}),
            lambda r: r["accepted"][0].update({"contradictory_unresolved": True}),
            lambda r: r["accepted"][0].update({"previous_claim": 17}),
            lambda r: r.update({"train_body": "forged\n"}),
            lambda r: r.update({"dataset_sha256": "0" * 64}),
            lambda r: r["dataset_manifest"].update({"human_approval": "APPROVED"}),
            lambda r: r["accepted"].append(copy.deepcopy(r["accepted"][0])),
        ]
        for mutate in changes:
            value = copy.deepcopy(original)
            mutate(value)
            report = compiler.verification_report(source, value)
            self.assertEqual("FAIL", report["checks"]["output_integrity"]["status"])
            self.assertEqual("NEEDS_REVISION", report["verification_result"])
        value = copy.deepcopy(original)
        value["accepted"][0]["new_evidence"] = []
        self.assertEqual("FAIL", compiler.verification_report(source, value)["schema_result"])
        value = copy.deepcopy(original)
        value["accepted"][0]["holdout_origin"] = True
        self.assertTrue(compiler.verification_report(source, value)["holdout_contamination"])
        value = copy.deepcopy(original)
        value["accepted"][0]["contradictory_unresolved"] = True
        self.assertEqual("FAIL", compiler.verification_report(source, value)["duplicate_conflict_check"])

    def test_source_provenance_requires_primary_records_file_hashes_and_resolution(self):
        value = candidate(source_record_status="resolved")
        source = snapshot(value)
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "evidence").mkdir()
            memory = {"source_memory_id": value["source_memory_id"], "experience_id": value["experience_id"],
                      "previous_claim": value["previous_claim"]}
            revision = {"source_memory_id": value["source_memory_id"], "source_revision_id": value["source_revision_id"],
                        "new_evidence": value["new_evidence"], "revised_claim": value["revised_claim"]}
            files = {"evidence/memory.json": memory, "evidence/revision.json": revision,
                     "evidence/fixture.json": {"synthetic_test_evidence": True}}
            for ref, data in files.items():
                (root / ref).write_text(json.dumps(data), encoding="utf-8")
            entry = {"experience_id": value["experience_id"], "source_memory_id": value["source_memory_id"],
                     "source_revision_id": value["source_revision_id"], "status": "resolved",
                     "memory_record_ref": "evidence/memory.json", "revision_record_ref": "evidence/revision.json",
                     "evidence_refs": value["evidence_refs"],
                     "file_sha256": {ref: hashlib.sha256((root / ref).read_bytes()).hexdigest() for ref in files}}
            resolution = root / "source_provenance.json"
            resolution.write_text(json.dumps({"records": [entry]}), encoding="utf-8")
            result = compiler.compile_dataset(source)
            report = compiler.verification_report(source, result, evidence_root=root)
            self.assertEqual("PASS", report["source_provenance_result"])
            self.assertEqual("PASS", report["engineering_result"])
            self.assertEqual("PENDING_INDEPENDENT_AUDIT", report["verification_result"])
            (root / "evidence/fixture.json").write_text("changed", encoding="utf-8")
            self.assertEqual("FAIL", compiler.verification_report(source, result, evidence_root=root)["source_provenance_result"])
            (root / "evidence/fixture.json").unlink()
            self.assertEqual("ERROR", compiler.verification_report(source, result, evidence_root=root)["source_provenance_result"])
            unresolved = snapshot(candidate())
            self.assertEqual("ERROR", compiler.verification_report(unresolved, compiler.compile_dataset(unresolved), evidence_root=root)["source_provenance_result"])

    def test_source_record_status_resolved_alone_does_not_prove_provenance(self):
        source = snapshot(candidate(source_record_status="resolved"))
        with tempfile.TemporaryDirectory() as directory:
            report = compiler.verification_report(source, compiler.compile_dataset(source), evidence_root=Path(directory))
            self.assertEqual("ERROR", report["source_provenance_result"])
            self.assertEqual("NEEDS_REVISION", report["verification_result"])

    def test_default_cli_and_explicit_paths_work_from_copied_standalone_bundle(self):
        with tempfile.TemporaryDirectory() as directory:
            bundle = Path(directory) / "extracted bundle"
            bundle.mkdir()
            for name in ["compiler.py", "candidate.schema.json"]:
                shutil.copyfile(ROOT / name, bundle / name)
            (bundle / "source_snapshot.json").write_text(json.dumps(snapshot()), encoding="utf-8")
            run = subprocess.run([sys.executable, "-B", str(bundle / "compiler.py")], cwd=directory,
                                 capture_output=True, text=True, encoding="utf-8")
            self.assertEqual(0, run.returncode, run.stderr)
            self.assertTrue((bundle / "dataset/train.jsonl").is_file(), "Default command must actually emit output")
            summary = json.loads(run.stdout)
            self.assertEqual("NEEDS_REVISION", summary["verification_result"])
            report = json.loads((bundle / "dataset/verification_report.json").read_text(encoding="utf-8"))
            self.assertEqual("ERROR", report["source_provenance_result"])
            self.assertEqual("PASS", report["checks"]["output_integrity"]["status"])
            output = bundle / "explicit output"
            run = subprocess.run([sys.executable, "-B", str(bundle / "compiler.py"),
                                  "--source", str(bundle / "source_snapshot.json"), "--out", str(output),
                                  "--schema", str(bundle / "candidate.schema.json")], cwd=directory,
                                 capture_output=True, text=True, encoding="utf-8")
            self.assertEqual(0, run.returncode, run.stderr)
            self.assertEqual((bundle / "dataset/train.jsonl").read_bytes(), (output / "train.jsonl").read_bytes())
            manifest = json.loads((output / "dataset_manifest.json").read_text(encoding="utf-8"))
            self.assertEqual(hashlib.sha256((output / "train.jsonl").read_bytes()).hexdigest(), manifest["dataset_sha256"])
            run = subprocess.run([sys.executable, "-B", str(bundle / "compiler.py"), "--schema", str(bundle / "missing.json")],
                                 cwd=directory, capture_output=True, text=True, encoding="utf-8")
            self.assertNotEqual(0, run.returncode)
            self.assertEqual("NEEDS_REVISION", json.loads(run.stdout)["verification_result"])

    def test_strict_json_parser_rejects_duplicate_keys_and_nonfinite_numbers(self):
        loader = getattr(compiler, "load_snapshot", lambda path: json.loads(Path(path).read_text(encoding="utf-8")))
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "source.json"
            for raw in ['{"holdout_registry": ["held"], "holdout_registry": []}', '{"number": NaN}']:
                path.write_text(raw, encoding="utf-8")
                with self.assertRaises(ValueError):
                    loader(path)


if __name__ == "__main__":
    unittest.main()
