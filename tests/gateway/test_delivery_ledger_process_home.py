"""A served profile's reply is ledgered where the boot sweep looks for it.

A multiplexed gateway connects each served profile's adapter inside that
profile's home override, and every final reply that bot sends is recorded from
that context. The boot sweep runs in the launch context. The ledger is one
shared store (rows are told apart by ``(platform, adapter_profile)``), so a row
recorded under the override must be visible to the sweep outside it.

Every other ledger test replaces ``_db_path``; these leave it alone, since the
path is what is under test.
"""

from __future__ import annotations

import pytest

import hermes_constants
from gateway import delivery_ledger as dl


@pytest.fixture(params=["hermes-home-env", "platform-default"])
def launch_home(request, tmp_path, monkeypatch):
    root = tmp_path / "root"
    (root / "profiles" / "research").mkdir(parents=True)
    if request.param == "hermes-home-env":
        monkeypatch.setenv("HERMES_HOME", str(root))
    else:
        # A default gateway run in the foreground has no HERMES_HOME at all.
        monkeypatch.delenv("HERMES_HOME", raising=False)
        monkeypatch.setattr(hermes_constants, "_get_platform_default_hermes_home", lambda: root)
    return root


def _record_under_profile(profile_home) -> None:
    token = hermes_constants.set_hermes_home_override(profile_home)
    try:
        dl.record_obligation(
            obligation_id="ob-1",
            session_key="agent:research:slack:channel:C1",
            platform="slack",
            chat_id="C1",
            thread_id=None,
            content="the final answer",
            adapter_profile="research",
        )
    finally:
        hermes_constants.reset_hermes_home_override(token)


def test_row_recorded_under_profile_scope_lands_in_launch_store(launch_home):
    profile_home = launch_home / "profiles" / "research"
    _record_under_profile(profile_home)

    assert (launch_home / "state.db").exists()
    assert not (profile_home / "state.db").exists()


def test_boot_sweep_claims_a_row_recorded_under_a_served_profile_scope(launch_home):
    _record_under_profile(launch_home / "profiles" / "research")
    # The recording gateway died between finalize and platform acknowledgement.
    conn = dl._connect()
    try:
        conn.execute("UPDATE delivery_obligations SET owner_pid=999999999, owner_started_at=1")
        conn.commit()
    finally:
        conn.close()

    claimed = dl.sweep_recoverable(deliverable_targets={("slack", "research")})

    assert [(row["obligation_id"], row["profile"]) for row in claimed] == [("ob-1", "research")]
