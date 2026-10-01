"""F10d real profile resolution and composed discovery through public owners."""
import pytest

from hermes_cli import profiles
from hermes_state import SessionDB
from tests.hermes_state.test_search_temporal_native import (
    LOWER, UPPER, agent, deny_network, ids, public, seed,
)


@pytest.fixture
def profile_dbs(tmp_path, monkeypatch):
    root = tmp_path / "日本語 profile root"
    root.mkdir()
    monkeypatch.setenv("HERMES_HOME", str(root))
    current = SessionDB(root / "state.db")
    target_home = root / "profiles" / "owned-target"
    target_home.mkdir(parents=True)
    assert profiles.get_profile_dir("owned-target") == target_home
    assert profiles.profile_exists("owned-target")
    target = SessionDB(target_home / "state.db")
    seed(current, "default-marker", LOWER + 1)
    seed(target, "target-marker", LOWER + 2)
    seed(target, "excluded-target", LOWER + 3)
    seed(target, "out-of-window-target", UPPER + 1)
    yield current, target
    target.close()
    current.close()


@pytest.mark.parametrize("route", ["registry", "invoke", "sequential"])
def test_profile_time_or_exclusion_composition(profile_dbs, agent, route):
    current, target = profile_dbs
    args = dict(query="modpack absenttoken", after="2026-06-01",
                before="2026-07-01", sort="newest", limit=1,
                exclude_session_ids=["excluded-target"], detail="full")
    default = public(current, agent, route, **args)
    assert default["success"] is True, default
    assert ids(default) == {"default-marker"}
    named = public(current, agent, route, profile="owned-target", **args)
    assert named["success"] is True, named
    assert ids(named) == {"target-marker"}
    assert "default-marker" not in str(named)
    # Read-only profile discovery leaves both databases and their rows intact.
    assert target.get_session("excluded-target") is not None
    assert current.get_session("default-marker") is not None


@pytest.mark.parametrize("route", ["registry", "invoke", "sequential"])
def test_named_profile_exact_match_precedes_or(profile_dbs, agent, route):
    current, target = profile_dbs
    seed(target, "exact-target", LOWER + 10, text="modpack absenttoken exact evidence")
    result = public(current, agent, route, profile="owned-target",
                    query="modpack absenttoken", after="2026-06-01",
                    before="2026-07-01", exclude_session_ids=["excluded-target"])
    assert result["success"] is True, result
    assert ids(result) == {"exact-target"}


@pytest.mark.parametrize("profile", ["owned-missing", "../owned-target"])
@pytest.mark.parametrize("route", ["registry", "invoke", "sequential"])
def test_invalid_profile_never_falls_back_to_current(profile_dbs, agent, profile, route):
    current, _ = profile_dbs
    result = public(current, agent, route, profile=profile, query="modpack")
    assert result["success"] is False, result
    assert "default-marker" not in str(result)


def test_invalid_bound_and_empty_window_remain_safe(profile_dbs, agent):
    current, _ = profile_dbs
    bad = public(current, agent, profile="owned-target", query="modpack", after="not-a-date")
    assert bad["success"] is False, bad
    empty = public(current, agent, profile="owned-target", query="modpack",
                   after="2026-07-01", before="2026-06-01")
    assert empty["success"] is True, empty
    assert ids(empty) == set()
