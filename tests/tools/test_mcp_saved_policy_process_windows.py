"""Saved policy survives a fresh Windows Python process, via actual public API."""
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys

import psutil
import pytest
from starlette.testclient import TestClient

from tests.tools.test_mcp_saved_policy_native_windows import ROOT, native_owner, rows, wait_for

pytestmark = pytest.mark.skipif(sys.platform != "win32", reason="Fresh native Windows process qualification.")


def _same_process(identity):
    try:
        process = psutil.Process(identity["pid"])
        if process.create_time() != identity["created"]:
            return None
        assert process.exe() == identity["exe"] and process.cmdline() == identity["argv"]
        return process
    except psutil.NoSuchProcess:
        return None


def _run_owned_child(argv, env, owned, receipt_path, phase):
    identity = actual_identity = None
    actual_verified = False
    original_error = None
    cleanup_errors = []
    code = None
    with (owned / ("fresh-" + phase + ".log")).open("xb") as log:
        child = subprocess.Popen(argv, cwd=ROOT, env=env, stdin=subprocess.DEVNULL,
                                 stdout=log, stderr=subprocess.STDOUT, creationflags=subprocess.CREATE_NO_WINDOW)
        # All observation after Popen belongs to this child's recovery boundary.
        try:
            process = psutil.Process(child.pid)
            identity = {"pid": child.pid, "created": process.create_time(), "exe": process.exe(), "argv": process.cmdline()}
            assert Path(identity["argv"][1]).resolve() == ROOT / "tests/fixtures/mcp_saved_policy_process.py"
            assert str(owned) in identity["argv"] and str(receipt_path) in identity["argv"]
            birth_path = receipt_path.with_suffix(".birth.json")
            wait_for(lambda: birth_path.exists() or child.poll() is not None)
            actual_identity = json.loads(birth_path.read_text(encoding="utf-8"))
            actual = _same_process(actual_identity)
            assert actual is not None
            assert actual.pid == child.pid or actual.pid in {descendant.pid for descendant in process.children(recursive=True)}
            assert Path(actual_identity["argv"][1]).resolve() == ROOT / "tests/fixtures/mcp_saved_policy_process.py"
            assert str(owned) in actual_identity["argv"] and str(receipt_path) in actual_identity["argv"]
            actual_verified = True
            observed_temporary = receipt_path.with_suffix(".observed.tmp")
            with observed_temporary.open("x", encoding="utf-8") as stream:
                stream.write("observed")
            observed_temporary.replace(receipt_path.with_suffix(".observed"))
            code = child.wait(timeout=45)
        except BaseException as error:
            original_error = error
        finally:
            # An unobserved helper keeps its barrier and exits itself after eight seconds.
            # Only the already verified identity may authorize termination.
            if child.poll() is None and actual_verified:
                try:
                    actual = _same_process(actual_identity)
                    if actual is not None:
                        actual.terminate()
                except Exception as error:
                    cleanup_errors.append("terminate: " + repr(error))
            try:
                child.wait(timeout=8 if actual_verified else 12)
            except Exception as error:
                cleanup_errors.append("wait: " + repr(error))
            for label, observed in (("launcher", identity), ("actual", actual_identity if actual_verified else None)):
                if observed is not None:
                    try:
                        assert _same_process(observed) is None, label + " process survived"
                    except Exception as error:
                        cleanup_errors.append(label + " exit audit: " + repr(error))
            cleanup = {"original_error": repr(original_error) if original_error is not None else None,
                       "cleanup_errors": cleanup_errors, "launcher": identity, "actual": actual_identity,
                       "actual_verified": actual_verified, "exit_code": child.poll()}
            try:
                with receipt_path.with_suffix(".cleanup.json").open("x", encoding="utf-8") as stream:
                    json.dump(cleanup, stream, indent=2)
            except Exception as error:
                cleanup_errors.append("cleanup receipt: " + repr(error))
    if original_error is not None:
        if cleanup_errors:
            original_error.add_note("Owned child cleanup errors: " + repr(cleanup_errors))
        raise original_error
    assert cleanup_errors == [], cleanup_errors
    return code, identity, actual_identity


def test_public_saved_policy_disabled_and_reenabled_in_fresh_processes(tmp_path, monkeypatch, record_property):
    from hermes_constants import get_hermes_home
    with native_owner("stdio", tmp_path, monkeypatch, record_property) as (core, registry, name, save, handles, effects, workers):
        from hermes_cli.web_server import app, _SESSION_HEADER_NAME, _SESSION_TOKEN
        home = get_hermes_home().resolve()
        owned = home.parent
        assert owned.name == "mcp-admission-owned"
        client = TestClient(app)
        client.headers[_SESSION_HEADER_NAME] = _SESSION_TOKEN
        target = "mcp__" + name + "__write_sentinel"
        assert "error" not in json.loads(registry.dispatch(target, {"nonce": "warm-parent-positive"}))
        seen_processes = []
        for enabled in (False, True):
            response = client.put(f"/api/mcp/servers/{name}/enabled", json={"enabled": enabled})
            assert response.status_code == 200 and response.json()["ok"] is True
            assert response.json()["application"]["policy_check"] == "rpc_admission"
            config_hash = hashlib.sha256((home / "config.yaml").read_bytes()).hexdigest()
            before = rows(effects)
            phase = "enabled" if enabled else "disabled"
            receipt_path = owned / ("fresh-" + phase + ".json")
            argv = [sys.executable, str(ROOT / "tests/fixtures/mcp_saved_policy_process.py"),
                    "--owned", str(owned), "--name", name, "--nonce", "cold-" + phase, "--receipt", str(receipt_path)]
            allowed = ("SYSTEMROOT", "WINDIR", "COMSPEC", "PATH", "PATHEXT", "TEMP", "TMP", "PYTHONUTF8", "PYTHONIOENCODING", "TZ", "LANG")
            env = {key: os.environ[key] for key in allowed if key in os.environ}
            env.update(HERMES_HOME=str(home), HOME=str(owned), USERPROFILE=str(owned))
            code, identity, actual_identity = _run_owned_child(argv, env, owned, receipt_path, phase)
            assert code == 0, (owned / ("fresh-" + phase + ".log")).read_text(encoding="utf-8")
            receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
            assert receipt["process"] == actual_identity
            assert Path(receipt["owner_module"]) == ROOT / "tools/mcp_tool.py"
            assert receipt["home"] == str(home) and receipt["survivors"] == []
            assert receipt["loop_closed"] and receipt["thread_exited"]
            assert hashlib.sha256((home / "config.yaml").read_bytes()).hexdigest() == config_hash
            after = rows(effects)
            if enabled:
                assert target in receipt["registered"] and "error" not in receipt["result"]
                assert len([row for row in after if row["operation"] == "boot"]) == len([row for row in before if row["operation"] == "boot"]) + 1
                assert len([row for row in after if row["operation"] == "tool_effect" and row["nonce"] == "cold-enabled"]) == 1
                assert receipt["owned_identities"]
            else:
                assert target not in receipt["registered"] and receipt["result"] is None
                assert after == before, "Disabled cold process spawned or invoked the owned MCP server"
            assert _same_process(identity) is None
            assert _same_process(actual_identity) is None
            seen_processes.append(actual_identity)
            record_property("fresh_process_" + phase, json.dumps(receipt, sort_keys=True))
        assert seen_processes[0]["created"] != seen_processes[1]["created"]
        assert all(row.get("nonce") != "cold-disabled" for row in rows(effects))
