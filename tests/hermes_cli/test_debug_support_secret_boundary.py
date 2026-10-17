"""Support exports scrub secrets without changing navigation or source logs."""

from urllib.parse import quote

import pytest

from hermes_cli import debug


SECRET = "DUMMY_SUPPORT_42_ABCD"


@pytest.mark.parametrize("text", [
    f"route=https://alice:{SECRET}@example.test/health?view=short",
    f"route=https://example.test/health?access_token={SECRET}&view=short",
    f"route=https://example.test/health#authToken={SECRET}&view=short",
    "redirect=" + quote(quote(f"https://example.test/health?private_key={SECRET}&view=short", safe=""), safe=""),
    f"Authorization: Bearer {SECRET}\nhttp_status=503",
    f"Proxy-Authorization: Basic {SECRET}\nhttp_status=503",
    f"Cookie: session={SECRET}; theme=dark\nhttp_status=503",
    f"argv=['worker', '--client-secret', '{SECRET}', '--port', '8080']",
    f"worker --private-key={SECRET} --port 8080",
    f"Authorization: {SECRET}\nhttp_status=503",
    f"aUtHoRiZaTiOn: Bearer {SECRET}\nhttp_status=503",
    f"https://alice:{SECRET}@localhost/health?view=short",
    f"//alice:{SECRET}@127.0.0.1/health?view=short",
    f"argv=['worker', '--client-secret', '{SECRET}",
    quote(f"https://alice:{SECRET}@example.test/health", safe=""),
    quote(quote(f"https://alice:{SECRET}@example.test/health", safe=""), safe=""),
    f'worker --password="two words {SECRET}" --port 8080',
    f"argv=['worker', '--password=two words {SECRET}', '--port', '8080']",
    f"Cookie: theme=dark; sid={SECRET}; locale=en\nhttp_status=503",
    f"Set-Cookie: theme=dark; sid={SECRET}; Secure\nhttp_status=503",
    f'worker --password="two \\"words {SECRET}" --port 8080',
    f"argv=['worker', '--password=two \\'words {SECRET}', '--port', '8080']",
    f'Authorization: "two \\"words {SECRET}"\nhttp_status=503',
    f'argv=["--header", "Authorization", "Bearer", "two \\"words {SECRET}"]',
])
def test_support_egress_scrubs_secret_values(text):
    redacted = debug._redact_log_text(text)
    assert SECRET not in redacted
    assert "DUMMY_SUPPORT" not in redacted
    assert redacted.strip()
    if "example.test" in text:
        assert "example.test" in redacted
    if "http_status=503" in text:
        assert "http_status=503" in redacted


def test_support_redactor_failure_never_returns_raw(monkeypatch):
    import agent.redact

    def broken(*args, **kwargs):
        raise RuntimeError(SECRET)

    monkeypatch.setattr(agent.redact, "redact_sensitive_text", broken)
    redacted = debug._redact_log_text(f"diagnostic {SECRET}")
    assert SECRET not in redacted
    assert "unavailable" in redacted.lower()


def test_privacy_redactor_failure_never_returns_raw(monkeypatch):
    def broken(*args):
        raise RuntimeError(SECRET)

    monkeypatch.setattr(debug, "_redact_debug_share_privacy", broken)
    redacted = debug._redact_log_text(f"message='{SECRET}'")
    assert SECRET not in redacted
    assert "unavailable" in redacted.lower()


def test_actual_log_snapshot_preserves_source_and_diagnostic_context(tmp_path, monkeypatch):
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    logs = tmp_path / "logs"
    logs.mkdir()
    original = f"http_status=503 route=https://example.test/health?token={SECRET}&view=short\nuser_id=42 message='private discussion'\n"
    source = logs / "agent.log"
    source.write_text(original, encoding="utf-8")
    snapshot = debug._capture_log_snapshot("agent", tail_lines=10)
    assert snapshot.full_text is not None
    for text in (snapshot.full_text, snapshot.tail_text):
        assert SECRET not in text
        assert "private discussion" not in text
        assert "user_id=42" not in text
        assert "http_status=503" in text
        assert "example.test/health" in text
        assert "view=short" in text
    assert source.read_text(encoding="utf-8") == original


def test_dump_and_late_report_content_are_redacted_in_every_bundle_copy(monkeypatch):
    dump = f"model=owned route=https://example.test/health?token={SECRET}&view=short"
    snapshots = {name: debug.LogSnapshot(path=None, tail_text="safe diagnostic", full_text="safe diagnostic")
                 for name in ("agent", "errors", "gateway", "gui", "desktop")}
    monkeypatch.setattr(debug, "_capture_dump", lambda: dump)
    monkeypatch.setattr(debug, "_capture_default_log_snapshots", lambda *args, **kwargs: snapshots)
    for text in debug.collect_share_bundle().values():
        assert SECRET not in text
        assert "model=owned" in text
        assert "example.test/health" in text
    assert SECRET in debug.collect_share_bundle(redact=False)["report"]


def test_client_attachment_redaction_precedes_character_limit():
    from hermes_cli.diagnostics_local_export import attach_client_artifacts
    value = "x" * 7990 + f" argv=['worker', '--client-secret', '{SECRET}']"
    result = attach_client_artifacts({}, error_context=value)
    assert "DUMMY" not in result["error-context.txt"]
    assert len(result["error-context.txt"]) <= 8000


def test_local_zip_and_owned_loopback_upload_contain_scrubbed_useful_bytes(tmp_path, monkeypatch):
    from http.server import BaseHTTPRequestHandler, HTTPServer
    from pathlib import Path
    import threading
    import zipfile

    from hermes_cli import diagnostics_local_export

    monkeypatch.setenv("HERMES_HOME", str(tmp_path / "home"))
    monkeypatch.setenv("NO_PROXY", "127.0.0.1")
    logs = tmp_path / "home" / "logs"
    logs.mkdir(parents=True)
    original = f'http_status=503 route=https://example.test/health?token={SECRET}\nCookie: theme=dark; sid={SECRET}\nworker --password="two words {SECRET}"\n'
    log = logs / "agent.log"
    log.write_text(original, encoding="utf-8")
    monkeypatch.setattr(debug, "_capture_dump", lambda: f"model=owned-test --token={SECRET}")
    monkeypatch.setattr(diagnostics_local_export, "collect_identity_metadata", lambda: {"fixture": "owned"})
    result = diagnostics_local_export.export_local_diagnostics(
        destination_dir=tmp_path / "export", error_context=original,
        extra_files={"owned.txt": original},
    )
    assert result["ok"] is True
    with zipfile.ZipFile(result["path"]) as archive:
        members = {name: archive.read(name) for name in archive.namelist()}
    assert "client/owned.txt" in members
    assert all(SECRET.encode() not in data for data in members.values())
    assert any(b"http_status=503" in data for data in members.values())
    bodies = []

    class OwnedSink(BaseHTTPRequestHandler):
        def do_POST(self):
            bodies.append(self.rfile.read(int(self.headers["Content-Length"])))
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b"http://127.0.0.1/owned-paste")

        def log_message(self, *args):
            pass

    sink = HTTPServer(("127.0.0.1", 0), OwnedSink)
    thread = threading.Thread(target=sink.serve_forever, daemon=True)
    thread.start()
    try:
        monkeypatch.setattr(debug, "_PASTE_RS_URL", f"http://127.0.0.1:{sink.server_port}/owned")
        assert debug._upload_paste_rs(debug.collect_share_bundle()["report"]).endswith("owned-paste")
    finally:
        sink.shutdown()
        sink.server_close()
        thread.join(timeout=5)
    assert not thread.is_alive()
    assert len(bodies) == 1 and SECRET.encode() not in bodies[0]
    assert b"http_status=503" in bodies[0] and b"example.test/health" in bodies[0]
    assert log.read_text(encoding="utf-8") == original
    assert Path(result["path"]).is_file()
