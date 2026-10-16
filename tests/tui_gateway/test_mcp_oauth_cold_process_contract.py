"""Actual new-process persisted token use and foreign peer/profile isolation."""

import json
from urllib.error import HTTPError
from urllib.request import Request, urlopen

import pytest

from tests.fakes.mcp_oauth_issuer import serve_issuer
from tests.fakes.mcp_oauth_gateway import deliver, finish, homes as homes, rpc, running_flow, scoped


from tests.fakes.mcp_oauth_cold_process import cold


def test_cold_process_uses_only_owner_token_and_foreign_peer_has_no_token_or_effect(homes, record_property):
    from hermes_cli.mcp_config import _replace_mcp_servers

    with serve_issuer() as owner, serve_issuer() as foreign:
        with running_flow(owner, homes) as (flow, rec, worker, listener, port, _):
            deliver(owner, flow, "match")
            finish(rec, worker, listener, port)
            assert rpc("poll", session_id=flow["session_id"])["status"] == "approved"
        before = len(owner.operations("token_redemption"))
        owned = cold(homes / "profiles" / "work", "cold-owner", True, homes.parent)
        assert len(owner.operations("token_redemption")) == before == 1
        assert [row["nonce"] for row in owner.operations("sentinel")] == ["cold-owner"]
        with scoped(homes / "profiles" / "other"):
            ok, issues = _replace_mcp_servers({"reports": {"url": foreign.mcp_url, "transport": "http", "auth": "oauth", "oauth": {"cimd": False}, "timeout": 5}})
            assert ok and not issues
        anonymous = Request(foreign.mcp_url, data=json.dumps({"jsonrpc": "2.0", "id": 1, "method": "tools/list", "params": {}}).encode("utf-8"), headers={"Content-Type": "application/json"})
        with pytest.raises(HTTPError) as denied:
            urlopen(anonymous, timeout=3)
        assert denied.value.code == 401
        denied.value.close()
        before_foreign = list(foreign.ledger)
        before_owner = list(owner.ledger)
        denied_child = cold(homes / "profiles" / "other", "foreign-must-not-run", False, homes.parent)
        assert denied_child["configured_url"] == foreign.mcp_url
        assert owned["configured_url"] == owner.mcp_url
        assert foreign.ledger == before_foreign
        assert owner.ledger == before_owner
        assert all(row["authorization"] is None for row in foreign.operations("mcp_request"))
        assert foreign.operations("token_request") == []
        assert foreign.operations("sentinel") == []
        assert not (homes / "profiles" / "other" / "mcp-tokens" / "reports.json").exists()
        record_property("owned_processes", json.dumps([owned, denied_child]))
        record_property("foreign_peer_ledger", json.dumps(foreign.ledger))


@pytest.mark.parametrize("initial_error", [FileNotFoundError(2, "pending"), PermissionError(13, "sharing refusal")])
def test_owned_handshake_waits_for_readable_content(tmp_path, monkeypatch, initial_error):
    from tests.fakes import mcp_oauth_cold_process as launcher

    path = tmp_path / "owned.observed"
    path.write_text("observed", encoding="utf-8")
    original_read = type(path).read_text
    attempts = []

    def read(candidate, *args, **kwargs):
        if candidate == path and not attempts:
            attempts.append(initial_error)
            raise initial_error
        return original_read(candidate, *args, **kwargs)

    monkeypatch.setattr(launcher.sys, "platform", "win32")
    monkeypatch.setattr(type(path), "read_text", read)
    assert launcher.read_handshake(path, tmp_path, launcher.time.monotonic() + 1) == "observed"
    assert attempts == [initial_error]


def test_owned_handshake_expiry_preserves_original_access_error(tmp_path, monkeypatch):
    from tests.fakes import mcp_oauth_cold_process as launcher

    path = tmp_path / "owned.observed"
    original = PermissionError(13, "persistent sharing refusal")
    monkeypatch.setattr(launcher.sys, "platform", "win32")

    def refused(*args, **kwargs):
        raise original

    monkeypatch.setattr(type(path), "read_text", refused)
    with pytest.raises(PermissionError) as failure:
        launcher.read_handshake(path, tmp_path, launcher.time.monotonic() - 1)
    assert failure.value is original
    assert "final read" in failure.value.__notes__[-1]


def test_owned_handshake_other_errors_and_wrong_content_are_not_retried(tmp_path, monkeypatch):
    from tests.fakes import mcp_oauth_cold_process as launcher

    path = tmp_path / "owned.observed"
    path.write_text("unexpected", encoding="utf-8")
    assert launcher.read_handshake(path, tmp_path, launcher.time.monotonic() + 1) == "unexpected"
    original = OSError(5, "read failure")

    def refused(*args, **kwargs):
        raise original

    monkeypatch.setattr(type(path), "read_text", refused)
    with pytest.raises(OSError) as failure:
        launcher.read_handshake(path, tmp_path, launcher.time.monotonic() + 1)
    assert failure.value is original


def test_owned_handshake_rejects_foreign_paths_before_read(tmp_path):
    from tests.fakes import mcp_oauth_cold_process as launcher

    owner = tmp_path / "owner"
    owner.mkdir()
    foreign = tmp_path / "foreign.observed"
    foreign.write_text("observed", encoding="utf-8")
    with pytest.raises(AssertionError):
        launcher.read_handshake(foreign, owner, launcher.time.monotonic() + 1)


def test_owned_handshake_never_reads_again_after_original_deadline(tmp_path, monkeypatch):
    from types import SimpleNamespace
    from tests.fakes import mcp_oauth_cold_process as launcher

    path = tmp_path / "owned.observed"
    original = PermissionError(13, "sharing refusal")
    attempts = []
    ticks = iter((0.0, 1.0))

    def read(*args, **kwargs):
        attempts.append(True)
        if len(attempts) == 1:
            raise original
        return "observed"

    monkeypatch.setattr(launcher.sys, "platform", "win32")
    monkeypatch.setattr(launcher, "time", SimpleNamespace(monotonic=lambda: next(ticks), sleep=lambda _: None))
    monkeypatch.setattr(type(path), "read_text", read)
    with pytest.raises(PermissionError) as failure:
        launcher.read_handshake(path, tmp_path, 1.0)
    assert failure.value is original and attempts == [True]


def test_owned_handshake_never_reads_again_after_child_exit(tmp_path, monkeypatch):
    from types import SimpleNamespace
    from tests.fakes import mcp_oauth_cold_process as launcher

    path = tmp_path / "owned.birth.json"
    original = FileNotFoundError(2, "birth pending")
    attempts = []
    poll_results = iter((None, 1))

    def read(*args, **kwargs):
        attempts.append(True)
        if len(attempts) == 1:
            raise original
        return "{}"

    monkeypatch.setattr(launcher, "time", SimpleNamespace(monotonic=lambda: 0.0, sleep=lambda _: None))
    monkeypatch.setattr(type(path), "read_text", read)
    with pytest.raises(FileNotFoundError) as failure:
        launcher.read_handshake(path, tmp_path, 6.0, SimpleNamespace(poll=lambda: next(poll_results)))
    assert failure.value is original and attempts == [True]


def test_owned_handshake_keeps_first_cause_and_last_access_detail(tmp_path, monkeypatch):
    from types import SimpleNamespace
    from tests.fakes import mcp_oauth_cold_process as launcher

    path = tmp_path / "owned.observed"
    first = FileNotFoundError(2, "pending publication")
    last = PermissionError(13, "sharing refusal")
    errors = iter((first, last))
    ticks = iter((0.0, 0.0, 0.0, 1.0))

    def read(*args, **kwargs):
        raise next(errors)

    monkeypatch.setattr(launcher.sys, "platform", "win32")
    monkeypatch.setattr(launcher, "time", SimpleNamespace(monotonic=lambda: next(ticks), sleep=lambda _: None))
    monkeypatch.setattr(type(path), "read_text", read)
    with pytest.raises(FileNotFoundError) as failure:
        launcher.read_handshake(path, tmp_path, 1.0)
    assert failure.value is first
    assert repr(last) in failure.value.__notes__[-1]
