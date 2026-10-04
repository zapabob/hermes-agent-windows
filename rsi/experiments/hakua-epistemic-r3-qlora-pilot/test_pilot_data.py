"""Behavioral contracts for isolated pilot data and frozen evaluation."""

import importlib
import pytest

try:
    data = importlib.import_module("pilot_data")
except ModuleNotFoundError:
    data = None


def test_dataset_contract_is_available():
    assert data is not None, "Pilot data contracts are not implemented"


def test_exact_or_normalized_holdout_overlap_is_rejected():
    assert data is not None
    a = {
        "id": "train-1",
        "family": "absence",
        "prompt": "A  B",
        "options": ["a", "b", "c", "d"],
        "gold": "A",
        "source_type": "synthetic_derived",
        "root_id": "root-1",
    }
    b = dict(a, id="eval-1", prompt="Ａ B", source_type="synthetic_authored_eval", root_id=None)
    with pytest.raises(ValueError, match="overlap"):
        data.verify_disjoint([a], [b])


def test_wrong_gold_and_missing_derived_root_are_rejected():
    assert data is not None
    x = {
        "id": "x",
        "family": "absence",
        "prompt": "q",
        "options": ["a", "b", "c", "d"],
        "gold": "Z",
        "source_type": "synthetic_derived",
        "root_id": None,
    }
    with pytest.raises(Exception):
        data.Item.model_validate(x)
    x["gold"] = "A"
    with pytest.raises(Exception):
        data.Item.model_validate(x)


def test_summary_is_dimension_separated_and_incomplete_is_not_zero():
    assert data is not None
    gold = [{"id": "x", "family": "permission", "gold": "A"}]
    with pytest.raises(ValueError, match="missing"):
        data.summarize(gold, [])
    result = data.summarize(gold, [{"id": "x", "choice": "A"}])
    assert result["permission"] == {"correct": 1, "total": 1, "rate": 1.0}


def test_paired_comparison_reports_discordant_counts():
    assert data is not None
    gold = [{"id": "x", "family": "revision", "gold": "B"}]
    result = data.compare(gold, [{"id": "x", "choice": "A"}], [{"id": "x", "choice": "B"}])
    assert result["revision"]["parent_wrong_child_right"] == 1
    assert result["revision"]["parent_right_child_wrong"] == 0


def test_non_string_decision_is_an_explicit_missing_error():
    assert data is not None
    with pytest.raises(ValueError, match="missing"):
        data.summarize([{"id": "x", "family": "absence", "gold": "A"}], [{"id": "x", "choice": None}])


def test_frozen_file_mutation_is_detected(tmp_path):
    assert data is not None
    p = tmp_path / "eval.jsonl"
    p.write_text("original", encoding="utf-8")
    identity = {str(p): data.sha_file(p)}
    data.check_frozen(identity)
    p.write_text("changed", encoding="utf-8")
    with pytest.raises(ValueError, match="Frozen"):
        data.check_frozen(identity)


def test_actual_tokenizer_response_only_mask_and_no_truncation():
    assert data is not None
    from transformers import AutoTokenizer

    try:
        import frozen_evaluator as evaluator
    except ModuleNotFoundError:
        evaluator = None
    assert evaluator is not None, "Frozen tokenizer/evaluation interface is missing"
    from pathlib import Path

    root = Path(__file__).resolve().parent
    tokenizer = AutoTokenizer.from_pretrained(root / "base_checkpoint", local_files_only=True, trust_remote_code=False)
    for item in data.read_items(root / "train.jsonl"):
        encoded = evaluator.encode_training_item(tokenizer, item, 512)
        assert len(encoded["input_ids"]) <= 512
        supervised = [x for x in encoded["labels"] if x != -100]
        assert supervised == tokenizer.encode(item["gold"], add_special_tokens=False) + [tokenizer.eos_token_id]
        assert encoded["labels"][: -len(supervised)] == [-100] * (len(encoded["labels"]) - len(supervised))


def test_real_train_eval_are_disjoint_and_invalid_schema_fails():
    assert data is not None
    from pathlib import Path

    root = Path(__file__).resolve().parent
    receipt = data.verify_disjoint(data.read_items(root / "train.jsonl"), data.read_items(root / "frozen_eval.jsonl"))
    assert receipt["train_count"] == 64
    assert receipt["eval_count"] == 72
    assert receipt["normalized_prompt_hash_overlap"] == 0
