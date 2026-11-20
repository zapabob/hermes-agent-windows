"""Prompt cache hit rate in the CLI status bar.

Only providers that report cache-read tokens get an indicator. The formula is
shared by the plain-text and prompt-toolkit paths so they cannot drift.
"""

from cli import HermesCLI


def test_no_indicator_without_cache_data():
    cli = HermesCLI.__new__(HermesCLI)
    assert cli._cache_hit_rate({"session_cache_read_tokens": 0, "session_prompt_tokens": 1000}) is None
    assert cli._cache_hit_rate({"session_cache_read_tokens": 50, "session_prompt_tokens": 0}) is None
    assert cli._cache_hit_rate({}) is None


def test_hit_rate_and_adaptive_precision():
    cli = HermesCLI.__new__(HermesCLI)
    snapshot = {"session_cache_read_tokens": 320, "session_prompt_tokens": 1000}
    pct, label = cli._cache_hit_rate(snapshot)
    assert pct == 32.0
    assert label == "◎32.0%"
    assert cli._cache_hit_rate(snapshot, precision=0)[1] == "◎32%"


def test_style_thresholds_are_inverted_from_context_usage():
    cli = HermesCLI.__new__(HermesCLI)
    assert cli._cache_hit_rate_style(75) == "class:status-bar-good"
    assert cli._cache_hit_rate_style(50) == "class:status-bar-warn"
    assert cli._cache_hit_rate_style(20) == "class:status-bar-bad"
