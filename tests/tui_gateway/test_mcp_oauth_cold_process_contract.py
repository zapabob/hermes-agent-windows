"""Actual new-process persisted token use and foreign peer/profile isolation."""

import json
import subprocess
import sys
import time
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen

import psutil
import pytest

from tests.fakes.mcp_oauth_issuer import serve_issuer
from tests.fakes.mcp_oauth_gateway import deliver, finish, homes as homes, rpc, running_flow, scoped


def cold(home, nonce, allowed, owned_root):
    script = Path(__file__).resolve().parents[1] / "fakes/mcp_oauth_cold_child.py"
    owned_root = owned_root.resolve()
    assert home.resolve().is_relative_to(owned_root)
    receipt_path = home / "m03-cold-receipt.json"
    launcher = actual_identity = None
    actual_verified = False
    original_error = None
    cleanup_errors = []
    process = subprocess.Popen([sys.executable, str(script), str(home), nonce,
                                "allowed" if allowed else "denied", str(receipt_path), str(owned_root)],
                               stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, encoding="utf-8",
                               creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0)
    try:
        parent = psutil.Process(process.pid)
        launcher = identity(parent)
        assert Path(launcher["argv"][1]).resolve() == script.resolve()
        assert str(owned_root) in launcher["argv"]
        assert str(home) in launcher["argv"] and str(receipt_path) in launcher["argv"]
        birth = receipt_path.with_suffix(".birth.json")
        deadline = time.monotonic() + 6
        while not birth.exists() and process.poll() is None and time.monotonic() < deadline:
            time.sleep(0.025)
        actual_identity = json.loads(birth.read_text(encoding="utf-8"))
        actual = same_process(actual_identity)
        assert actual is not None
        assert actual.pid == parent.pid or actual.pid in {child.pid for child in parent.children(recursive=True)}
        assert Path(actual_identity["argv"][1]).resolve() == script.resolve()
        assert str(owned_root) in actual_identity["argv"]
        assert str(home) in actual_identity["argv"] and str(receipt_path) in actual_identity["argv"]
        actual_verified = True
        temporary = receipt_path.with_suffix(".observed.tmp")
        temporary.write_text("observed", encoding="utf-8")
        temporary.replace(receipt_path.with_suffix(".observed"))
        stdout, stderr = process.communicate(timeout=45)
        receipt_path.with_suffix(".stdout.log").write_text(stdout, encoding="utf-8")
        receipt_path.with_suffix(".stderr.log").write_text(stderr, encoding="utf-8")
        assert process.returncode == 0, (stdout, stderr)
        result = json.loads(receipt_path.read_text(encoding="utf-8"))
        assert {key: result[key] for key in ("pid", "created", "exe", "argv")} == actual_identity
        assert result["allowed"] is allowed
        assert Path(result["home"]).resolve() == home.resolve()
    except BaseException as error:
        original_error = error
    finally:
        def attempt(label, action):
            try:
                action()
            except BaseException as error:
                cleanup_errors.append(label + ": " + repr(error))

        def terminate_actual():
            actual = same_process(actual_identity)
            if actual is not None:
                actual.terminate()

        if actual_verified:
            attempt("terminate_owned_actual", terminate_actual)
        attempt("launcher_wait", lambda: process.wait(timeout=8 if actual_verified else 12))
        for label, pipe in (("stdout", process.stdout), ("stderr", process.stderr)):
            if pipe:
                attempt(label + "_close", pipe.close)
        for label, observed_identity in (("launcher", launcher), ("actual", actual_identity if actual_verified else None)):
            if observed_identity:
                attempt(label + "_exit_audit", lambda row=observed_identity: exited(row))
        cleanup = {"original_error": repr(original_error), "errors": cleanup_errors,
                   "launcher": launcher, "actual": actual_identity, "actual_verified": actual_verified}
        attempt("cleanup_receipt", lambda: receipt_path.with_suffix(".cleanup.json").write_text(json.dumps(cleanup), encoding="utf-8"))
    if original_error is not None:
        original_error.add_note("Owned cleanup: " + repr(cleanup_errors))
        raise original_error
    assert cleanup_errors == [], cleanup_errors
    return result


def identity(process):
    return {"pid": process.pid, "created": process.create_time(), "exe": process.exe(), "argv": process.cmdline()}


def same_process(row):
    try:
        process = psutil.Process(row["pid"])
        if process.create_time() != row["created"]:
            return None
        assert process.exe() == row["exe"] and process.cmdline() == row["argv"]
        return process
    except psutil.NoSuchProcess:
        return None


def exited(row):
    assert same_process(row) is None, row


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
