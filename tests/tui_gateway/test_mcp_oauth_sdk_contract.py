"""Actual SDK issuer policy, token persistence and registry effects."""
import json
import pytest
from tests.fakes.mcp_oauth_issuer import serve_issuer
from tests.fakes.mcp_oauth_gateway import closed, deliver, finish, homes as homes, registry_effect, rpc, running_flow


@pytest.mark.parametrize("required,mode,allowed", [
    (True, "match", True), (True, "absent", False), (True, "mismatch", False),
    (False, "match", True), (False, "absent", True), (False, "mismatch", False),
    (False, "empty", False), (False, "slash", False),
])
def test_actual_sdk_issuer_policy_token_ledger_and_registry_effect(homes, required, mode, allowed, record_property):
    with serve_issuer(required) as owner:
        with running_flow(owner, homes) as (flow, rec, worker, listener, port, loops):
            deliver(owner, flow, mode)
            finish(rec, worker, listener, port)
            for loop, thread in loops:
                closed(loop)
                assert not thread.is_alive()
            result = rpc("poll", session_id=flow["session_id"])
            token_file = homes / "profiles" / "work" / "mcp-tokens" / "reports.json"
            assert not (homes / "profiles" / "other" / "mcp-tokens" / "reports.json").exists()
            if allowed:
                assert result["status"] == "approved", result
                assert len(owner.operations("token_redemption")) == 1
                assert json.loads(token_file.read_text(encoding="utf-8"))["access_token"] == owner.token
                registry_effect(owner, homes / "profiles" / "work", "owned-issuer-policy")
                assert len(owner.operations("sentinel")) == 1
            else:
                assert result["status"] == "error", result
                assert owner.operations("token_request") == []
                assert owner.operations("token_redemption") == []
                assert owner.operations("sentinel") == []
                assert not token_file.exists()
            assert all(row.get("authorization") is None for row in owner.operations("get"))
            record_property("owned_issuer_ledger", json.dumps(owner.ledger))
