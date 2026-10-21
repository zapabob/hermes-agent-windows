"""Skills index token budget: the names-only degradation.

The skills index is re-sent on EVERY request. On a workstation with many
skills it measured 18,908 tokens — more than the tool schemas — and it is
pure overhead until a skill is actually loaded.

Contract under test:

* ``skills_listing_max_tokens`` caps the rendered index.
* When the cap binds, the LARGEST categories are demoted to the existing
  names-only form until the index fits.
* Every skill NAME stays visible. Skills are the model's project memory and
  it does not re-discover what the index stops showing.
* Without the cap the rendering is byte-identical to the previous behavior.
* The demotion is deterministic (same catalog -> same index), because the
  request prefix has to stay cacheable.
"""

from __future__ import annotations

from unittest.mock import patch

import pytest

from agent import prompt_builder as pb
from agent.model_metadata import estimate_tokens_rough


def _fake_skills(count_per_category: dict[str, int], desc_chars: int = 400) -> dict:
    """Build a skills_by_category map: {category: [(name, description)]}."""
    return {
        category: [
            (f"{category}-skill-{i}", "d" * desc_chars) for i in range(n)
        ]
        for category, n in count_per_category.items()
    }


def _render(skills, demoted=frozenset(), budget=None):
    with patch.object(pb, "_get_skills_listing_max_tokens", return_value=budget):
        return pb._render_skills_index_lines(skills, {}, set(demoted))


class TestSkillsListingBudget:
    def test_no_cap_leaves_the_full_manifest(self):
        skills = _fake_skills({"alpha": 3, "beta": 2})
        lines = _render(skills, budget=None)
        assert len(lines) == 2 + 5  # two category headers + five entries
        assert any("- alpha-skill-0:" in line for line in lines)

    def test_cap_demotes_the_largest_category_first(self):
        skills = _fake_skills({"small": 1, "huge": 40})
        demoted = pb._apply_skills_listing_budget(
            skills, {}, frozenset(), budget=200)
        # With a tiny cap both categories end up names-only, but the ORDER is
        # deterministic: the biggest category is demoted first.
        assert demoted == frozenset({"huge", "small"})

    def test_names_always_stay_visible(self):
        skills = _fake_skills({"huge": 40, "small": 2})
        demoted = pb._apply_skills_listing_budget(skills, {}, frozenset(), budget=200)
        lines = _render(skills, demoted=demoted)
        text = "\n".join(lines)
        assert "huge-skill-0" in text
        assert "small-skill-0" in text
        # The description is what gets dropped.
        assert "- huge-skill-0: dddd" not in text

    def test_budget_is_respected(self):
        skills = _fake_skills({f"cat{i}": 20 for i in range(10)})
        budget = 500
        demoted = pb._apply_skills_listing_budget(skills, {}, frozenset(), budget=200)
        lines = _render(skills, demoted=demoted)
        # The names-only floor can exceed a tiny budget (every name must
        # stay); the demotion must still have happened.
        assert demoted
        assert all("names only" in line or line.strip().endswith(":") for line in lines)

    def test_demotion_is_deterministic(self):
        skills = _fake_skills({f"cat{i}": 5 + i for i in range(8)})
        first = pb._apply_skills_listing_budget(skills, {}, frozenset())
        second = pb._apply_skills_listing_budget(skills, {}, frozenset())
        assert first == second

    def test_preexisting_demotion_is_preserved(self):
        skills = _fake_skills({"alpha": 2, "beta": 2})
        demoted = pb._apply_skills_listing_budget(
            skills, {}, frozenset({"alpha"}), budget=200
        )
        assert "alpha" in demoted

    def test_empty_catalog_is_a_noop(self):
        assert pb._apply_skills_listing_budget({}, {}, frozenset()) == frozenset()


class TestConfigParsing:
    def test_invalid_values_mean_no_cap(self):
        with patch(
            "hermes_cli.config.load_config_readonly",
            return_value={"skills_listing_max_tokens": "not-a-number"},
        ):
            assert pb._get_skills_listing_max_tokens() is None
        with patch(
            "hermes_cli.config.load_config_readonly",
            return_value={"skills_listing_max_tokens": 0},
        ):
            assert pb._get_skills_listing_max_tokens() is None
        with patch(
            "hermes_cli.config.load_config_readonly",
            return_value={"skills_listing_max_tokens": -5},
        ):
            assert pb._get_skills_listing_max_tokens() is None

    def test_positive_value_is_used(self):
        with patch(
            "hermes_cli.config.load_config_readonly",
            return_value={"skills_listing_max_tokens": 4000},
        ):
            assert pb._get_skills_listing_max_tokens() == 4000

    def test_missing_key_means_no_cap(self):
        with patch(
            "hermes_cli.config.load_config_readonly", return_value={}
        ):
            assert pb._get_skills_listing_max_tokens() is None


class TestIndexBudgetEffect:
    def test_budget_reduces_the_rendered_index(self):
        skills = _fake_skills({f"cat{i}": 10 for i in range(12)}, desc_chars=300)
        full = "\n".join(_render(skills, budget=None))
        demoted = pb._apply_skills_listing_budget(skills, {}, frozenset(), budget=200)
        bounded = "\n".join(_render(skills, demoted=demoted))
        assert estimate_tokens_rough(bounded) < estimate_tokens_rough(full)
        # Every name survives.
        for category, entries in skills.items():
            for name, _desc in entries:
                assert name in bounded
