"""Regression checks for frozen identity and actual pilot decision semantics."""
import json
from pathlib import Path
import pytest
from pydantic import ValidationError
from pilot_data import check_frozen, compare, prompt_hash, read_items, sha_file, summarize, verify_disjoint

ROOT = Path(__file__).resolve().parent

def test_actual_train_eval_are_disjoint_under_executed_contract():
    report = verify_disjoint(read_items(ROOT / "train.jsonl"), read_items(ROOT / "frozen_eval.jsonl"))
    assert report["train_count"] > 0 and report["eval_count"] > 0
    assert report["id_overlap"] == report["normalized_prompt_hash_overlap"] == 0

def test_renamed_eval_content_cannot_enter_train():
    evaluation = read_items(ROOT / "frozen_eval.jsonl")
    copied = dict(evaluation[0], id="renamed-holdout", source_type="synthetic_derived", root_id="fake-root")
    with pytest.raises(ValueError, match="content/hash overlap"):
        verify_disjoint([copied], evaluation)

def test_unresolved_root_cannot_be_falsely_omitted_from_derived_example():
    item = read_items(ROOT / "train.jsonl")[0]
    with pytest.raises(ValidationError):
        verify_disjoint([dict(item, root_id=None)], read_items(ROOT / "frozen_eval.jsonl"))

def test_absent_decision_is_error_not_zero_accuracy():
    evaluation = read_items(ROOT / "frozen_eval.jsonl")
    with pytest.raises(ValueError, match="missing evaluation decisions"):
        summarize(evaluation, [])

def test_empty_decision_is_error_not_negative_result():
    evaluation = read_items(ROOT / "frozen_eval.jsonl")[:1]
    with pytest.raises(ValueError, match="missing, not a score of zero"):
        summarize(evaluation, [{"id": evaluation[0]["id"], "choice": ""}])

def test_duplicate_decision_does_not_inflate_denominator():
    evaluation = read_items(ROOT / "frozen_eval.jsonl")[:1]
    row = {"id": evaluation[0]["id"], "choice": evaluation[0]["gold"]}
    with pytest.raises(ValueError, match="Duplicate or missing"):
        summarize(evaluation, [row, row])

def test_frozen_identity_rejects_changed_and_missing_target(tmp_path):
    path = tmp_path / "rubric.json"
    path.write_text("one", encoding="utf-8")
    expected = {str(path): sha_file(path)}
    check_frozen(expected)
    path.write_text("two", encoding="utf-8")
    with pytest.raises(ValueError, match="Frozen file changed"):
        check_frozen(expected)
    path.unlink()
    with pytest.raises(ValueError, match="Frozen file changed"):
        check_frozen(expected)

def test_frozen_item_registry_has_executable_canonicalization():
    manifest = json.loads((ROOT / "frozen_eval_manifest.json").read_text(encoding="utf-8"))
    items = read_items(ROOT / "frozen_eval.jsonl")
    assert {x["id"]: prompt_hash(x) for x in items} == manifest["item_content_hashes"]
    assert sha_file(ROOT / "frozen_eval.jsonl") == manifest["eval_sha256"]

def test_parent_child_discordance_is_measured_not_assumed():
    item = read_items(ROOT / "frozen_eval.jsonl")[0]
    wrong = next(label for label in "ABCD" if label != item["gold"])
    parent = [{"id": item["id"], "choice": wrong}]
    child = [{"id": item["id"], "choice": item["gold"]}]
    report = compare([item], parent, child)[item["family"]]
    assert report["parent_wrong_child_right"] == 1
    assert report["parent_right_child_wrong"] == 0
    assert report["delta"] == 1
