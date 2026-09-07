"""diagnostics.export_local — local-first ZIP export (no network).

Contract:
* Reuses collect_share_bundle with redaction FORCED.
* Writes Hermes-Diagnostics-YYYYMMDD-HHMMSS.zip under a profile-scoped dir.
* Secrets / emails from error_context and extra_files are redacted.
* share_to_nous / urllib must never be invoked.
"""

from __future__ import annotations

import json
import zipfile
from pathlib import Path

import pytest

from hermes_cli import diagnostics_local_export as lex
from tui_gateway import server


def _handler():
    fn = server._methods.get("diagnostics.export_local")
    assert fn is not None, "diagnostics.export_local not registered"
    return fn


@pytest.fixture()
def export_home(tmp_path, monkeypatch):
    home = tmp_path / ".hermes"
    home.mkdir()
    monkeypatch.setenv("HERMES_HOME", str(home))
    monkeypatch.setattr(lex, "default_export_dir", lambda: home / "diagnostics-exports")
    return home


def test_export_local_writes_zip_without_network(export_home, monkeypatch):
    calls: list[str] = []

    def _boom(*_a, **_k):
        calls.append("network")
        raise AssertionError("network must not be called for local export")

    import hermes_cli.diagnostics_upload as du
    import urllib.request

    monkeypatch.setattr(du, "share_to_nous", _boom)
    monkeypatch.setattr(urllib.request, "urlopen", _boom)

    result = _handler()("rid-local-1", {})
    payload = result["result"]

    assert payload["ok"] is True
    assert payload["redacted"] is True
    assert calls == []

    path = Path(payload["path"])
    assert path.is_file()
    assert path.name.startswith("Hermes-Diagnostics-")
    assert path.suffix == ".zip"
    assert path.parent == export_home / "diagnostics-exports"

    with zipfile.ZipFile(path, "r") as zf:
        names = zf.namelist()
        assert "manifest.json" in names
        assert "report" in names
        manifest = json.loads(zf.read("manifest.json").decode("utf-8"))
        assert manifest["format"] == lex.LOCAL_BUNDLE_FORMAT
        assert manifest["redacted"] is True


def test_export_local_redacts_secrets_and_emails(export_home):
    secret = "sk-abc123def456ghi789jkl012mno345pqr678"
    result = _handler()(
        "rid-local-2",
        {
            "error_context": f"user alice@example.com key={secret}",
            "extra_files": {"desktop.log": f"token={secret} mail=bob@example.com"},
        },
    )
    assert result["result"]["ok"] is True

    path = Path(result["result"]["path"])
    with zipfile.ZipFile(path, "r") as zf:
        context = zf.read("error-context.txt").decode("utf-8")
        client = zf.read("client/desktop.log").decode("utf-8")

    assert secret not in context
    assert secret not in client
    assert "alice@example.com" not in context
    assert "bob@example.com" not in client


def test_export_local_sanitizes_extra_labels(export_home):
    result = _handler()(
        "rid-local-3",
        {
            "extra_files": {
                "../../etc/passwd": "nope",
                "ok name (1).txt": "fine",
                "empty": "   ",
            }
        },
    )
    assert result["result"]["ok"] is True

    path = Path(result["result"]["path"])
    with zipfile.ZipFile(path, "r") as zf:
        names = zf.namelist()

    assert "client/ok name (1).txt" in names
    assert not any("/etc/passwd" in n or ".." in n for n in names)
    assert "client/empty" not in names


def test_make_bundle_filename_shape():
    name = lex.make_bundle_filename()
    assert name.startswith("Hermes-Diagnostics-")
    assert name.endswith(".zip")
    assert len(name) == len("Hermes-Diagnostics-YYYYMMDD-HHMMSS.zip")


def test_build_local_zip_bytes_forces_redacted_flag():
    blob = lex.build_local_zip_bytes(
        {"report": "ok"},
        metadata={"redacted": False, "format": "tamper"},
    )
    with zipfile.ZipFile(__import__("io").BytesIO(blob), "r") as zf:
        manifest = json.loads(zf.read("manifest.json").decode("utf-8"))
    assert manifest["redacted"] is True
    assert manifest["format"] == lex.LOCAL_BUNDLE_FORMAT
