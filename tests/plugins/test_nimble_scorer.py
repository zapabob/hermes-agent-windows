"""Tests for the nimble-scorer plugin.

Pure-logic tests cover schema validation, the restricted softmax, and prompt
construction. A separate opt-in class exercises the live llama.cpp server and
is skipped unless NIMBLE_TEST_LIVE=1.
"""

from __future__ import annotations

import math
import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from plugins.nimble_scorer import core  # noqa: E402


# ---------------------------------------------------------------------------
# Schema validation
# ---------------------------------------------------------------------------

def test_valid_enum_and_boolean_schema():
    schema = {
        "urgency": {"type": "enum", "description": "How urgent?",
                    "choices": ["low", "high"]},
        "is_actionable": {"type": "boolean", "description": "Is it a task?"},
    }
    assert core.validate_schema(schema) is schema


def test_empty_schema_rejected():
    with pytest.raises(core.NimbleError):
        core.validate_schema({})


@pytest.mark.parametrize("field", [
    {"type": "number", "description": "x", "choices": ["a"]},   # bad type
    {"type": "enum", "description": "", "choices": ["a"]},      # empty description
    {"type": "enum", "description": "x"},                      # missing choices
    {"type": "enum", "description": "x", "choices": []},       # no choices
    {"type": "enum", "description": "x", "choices": ["a", "a"]},  # duplicate
    {"type": "enum", "description": "x", "choices": ["a", ""]},   # blank choice
    {"type": "enum", "description": "x", "choices": ["a"], "weight": 2},  # extra key
])
def test_malformed_fields_rejected(field):
    with pytest.raises(core.NimbleError):
        core.validate_schema({"f": field})


def test_too_many_enum_choices_rejected():
    choices = [f"c{i}" for i in range(core.MAX_CHOICES + 1)]
    with pytest.raises(core.NimbleError):
        core.validate_schema({"f": {"type": "enum", "description": "x", "choices": choices}})


def test_boolean_choices_must_be_false_true():
    with pytest.raises(core.NimbleError):
        core.validate_schema({"f": {"type": "boolean", "description": "x",
                                    "choices": [True, True]}})


def test_choice_descriptions_must_reference_real_choices():
    with pytest.raises(core.NimbleError):
        core.validate_schema({"f": {"type": "enum", "description": "x",
                                    "choices": ["a", "b"],
                                    "choice_descriptions": {"zzz": "nope"}}})


# ---------------------------------------------------------------------------
# choices_for / choice_key
# ---------------------------------------------------------------------------

def test_boolean_defaults_and_choice_key():
    assert core.choices_for({"type": "boolean"}) == [False, True]
    assert core.choice_key(True) == "true"
    assert core.choice_key("High") == "High"


# ---------------------------------------------------------------------------
# Restricted softmax
# ---------------------------------------------------------------------------

def test_softmax_is_normalized_and_order_preserving():
    probs = core.restricted_softmax([-4.5, -6.2, -0.02])
    assert math.isclose(sum(probs), 1.0, rel_tol=1e-9)
    assert probs[2] > probs[0] > probs[1]


def test_softmax_is_shift_invariant():
    a = core.restricted_softmax([-1.0, -2.0])
    b = core.restricted_softmax([99.0, 98.0])
    assert a == pytest.approx(b)


def test_softmax_uniform_when_equal():
    probs = core.restricted_softmax([-3.0, -3.0, -3.0])
    assert all(math.isclose(p, 1 / 3) for p in probs)


# ---------------------------------------------------------------------------
# Prompt construction
# ---------------------------------------------------------------------------

def test_field_block_includes_codes_and_descriptions():
    block = core.build_field_block("severity", {
        "type": "enum", "description": "How bad?",
        "choices": ["low", "high"],
        "choice_descriptions": {"low": "cosmetic"},
    })
    assert [c["code"] for c in block["choices"]] == ["A", "B"]
    assert block["choices"][0]["value"] == "low"
    assert block["choices"][0]["description"] == "cosmetic"
    # A choice with no description must not gain an empty key.
    assert "description" not in block["choices"][1]


def test_safe_json_escapes_angle_brackets_and_rejects_nan():
    assert "\\u003c" in core.safe_json({"a": "<script>"})
    with pytest.raises(core.NimbleError):
        core.safe_json({"a": float("nan")})


def test_safe_json_preserves_unicode():
    """ensure_ascii=False keeps Japanese context readable instead of \\u-escaped."""
    assert "日本語" in core.safe_json({"context": "日本語のテキスト"})


def test_expected_score_for_ordered_numeric_scale():
    assert core._expected_score([1, 2, 3], [0.5, 0.25, 0.25]) == pytest.approx(1.75)


def test_expected_score_none_for_unordered_labels():
    assert core._expected_score(["low", "high"], [0.5, 0.5]) is None


def test_score_rejects_blank_context():
    with pytest.raises(core.NimbleError):
        core.score("   ", {"f": {"type": "boolean", "description": "x"}})


# ---------------------------------------------------------------------------
# Live server (opt-in)
# ---------------------------------------------------------------------------

BASE_URL = os.environ.get("NIMBLE_TEST_BASE_URL", "http://127.0.0.1:8080")


@pytest.mark.skipif(os.environ.get("NIMBLE_TEST_LIVE") != "1",
                    reason="set NIMBLE_TEST_LIVE=1 to test against a live llama-server")
class TestLive:
    def test_status_reports_model(self):
        info = core.status(base_url=BASE_URL)
        assert info["ok"], info
        assert info["model_alias"]

    def test_single_token_contract_and_correct_decision(self):
        result = core.score(
            "URGENT: the production server is down and users cannot log in. "
            "Please restart it immediately.",
            {
                "urgency": {"type": "enum", "description": "How urgent is the request?",
                            "choices": ["low", "medium", "high"]},
                "is_actionable": {"type": "boolean",
                                  "description": "Does the text ask for a task?"},
            },
            base_url=BASE_URL,
        )
        assert result["output"]["urgency"] == "high"
        assert result["output"]["is_actionable"] is True
        for field in result["fields"].values():
            assert math.isclose(sum(field["probabilities"].values()), 1.0, abs_tol=1e-3)
            assert len(set(field["candidate_token_ids"])) == len(field["candidate_token_ids"])

    def test_decision_flips_with_meaning(self):
        """A control case guards against a scorer that always picks the same code."""
        result = core.score(
            "No rush at all, just sharing this for your records whenever you have time.",
            {"urgency": {"type": "enum", "description": "How urgent is the request?",
                         "choices": ["low", "medium", "high"]}},
            base_url=BASE_URL,
        )
        assert result["output"]["urgency"] == "low"
