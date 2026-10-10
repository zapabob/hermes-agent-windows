"""Actual RPC cancellation admission and token barriers on owned peers."""

import json
import threading

import pytest

from tests.fakes.mcp_oauth_issuer import serve_issuer
from tests.fakes.mcp_oauth_gateway import deliver, finish, homes as homes, registry_effect, rpc, running_flow


def token_path(root):
    return root / "profiles" / "work" / "mcp-tokens" / "reports.json"


def test_cancel_before_callback_exits_actual_resources_then_fresh_flow_succeeds(homes):
    with serve_issuer() as owner:
        with running_flow(owner, homes) as (flow, rec, worker, listener, port, _):
            cancelled = rpc("cancel", session_id=flow["session_id"])
            assert cancelled["ok"] and cancelled["cancelled"] is True
            finish(rec, worker, listener, port)
            result = rpc("poll", session_id=flow["session_id"])
            assert result["status"] == "error" and "Cancelled" in result["error_message"]
            assert rpc("cancel", session_id=flow["session_id"])["cancelled"] is True
            assert owner.operations("token_request") == []
            assert not token_path(homes).exists()
        with running_flow(owner, homes) as (flow, rec, worker, listener, port, _):
            deliver(owner, flow, "match")
            finish(rec, worker, listener, port)
            assert rpc("poll", session_id=flow["session_id"])["status"] == "approved"
            registry_effect(owner, homes / "profiles" / "work", "fresh-after-cancel")
            assert len(owner.operations("token_redemption")) == 1
            assert owner.operations("sentinel")[-1]["nonce"] == "fresh-after-cancel"


def test_foreign_cancel_leaves_real_owner_worker_and_listener_usable(homes):
    with serve_issuer() as owner:
        with running_flow(owner, homes) as (flow, rec, worker, listener, port, _):
            denied = rpc("cancel", profile="other", session_id=flow["session_id"])
            assert denied["ok"] is False
            assert worker.is_alive() and listener.is_alive()
            assert not rec["flow"]._callback_ready.is_set()
            deliver(owner, flow, "match")
            finish(rec, worker, listener, port)
            assert rpc("poll", session_id=flow["session_id"])["status"] == "approved"
            registry_effect(owner, homes / "profiles" / "work", "owner-after-foreign-cancel")
            assert len(owner.operations("token_redemption")) == 1


@pytest.mark.parametrize("barrier", ["token-response", "token-persisted"])
def test_cancel_after_callback_admission_preserves_real_success(homes, monkeypatch, barrier):
    from tools.mcp_oauth import HermesTokenStorage

    persisted = threading.Event()
    release = threading.Event()
    original = HermesTokenStorage.set_tokens

    async def persisted_barrier(storage, tokens):
        await original(storage, tokens)
        persisted.set()
        assert release.wait(8), "Owned persistence barrier timed out"

    if barrier == "token-persisted":
        monkeypatch.setattr(HermesTokenStorage, "set_tokens", persisted_barrier)
    with serve_issuer() as owner:
        if barrier == "token-response":
            owner.token_release.clear()
        with running_flow(owner, homes) as (flow, rec, worker, listener, port, _):
            try:
                deliver(owner, flow, "match")
                if barrier == "token-response":
                    assert owner.token_started.wait(5)
                    assert owner.operations("token_redemption") == []
                    assert not token_path(homes).exists()
                else:
                    assert persisted.wait(5)
                    assert json.loads(token_path(homes).read_text(encoding="utf-8"))["access_token"] == owner.token
                    assert len(owner.operations("token_redemption")) == 1
                cancelled = rpc("cancel", session_id=flow["session_id"])
                assert cancelled["ok"] and cancelled["cancelled"] is False
                assert cancelled["status"] != "error"
                assert worker.is_alive()
                assert not rec["flow"]._worker_done.is_set()
            finally:
                owner.token_release.set()
                release.set()
            finish(rec, worker, listener, port)
            assert rpc("poll", session_id=flow["session_id"])["status"] == "approved"
            assert rpc("cancel", session_id=flow["session_id"])["cancelled"] is False
            assert json.loads(token_path(homes).read_text(encoding="utf-8"))["access_token"] == owner.token
            assert len(owner.operations("token_redemption")) == 1
            registry_effect(owner, homes / "profiles" / "work", "admitted-" + barrier)
            assert len(owner.operations("sentinel")) == 1
