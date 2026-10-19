"""URI identity across actual client transport and platform path conventions."""
from __future__ import annotations

import os
from pathlib import Path
import posixpath
import sys
from types import SimpleNamespace

import pytest

import agent.lsp.client as client_module
from agent.lsp.client import LSPClient, file_uri, uri_to_path


PEER = r'''
import json, os, sys
mode = sys.argv[1]
events = []
version = 0
uri = ""
def send(value):
    body = json.dumps(dict(jsonrpc="2.0", **value)).encode("utf-8")
    sys.stdout.buffer.write(("Content-Length: %d\r\n\r\n" % len(body)).encode("ascii") + body)
    sys.stdout.buffer.flush()
def reply_uri(value):
    if os.name == "nt":
        # Match vscode-uri's encoded, lower-case drive; alter path case too.
        value = value.replace("MixedCase", "mIXEDcASE")
        head, tail = value.split(":", 2)[1:]
        value = "file:" + head.lower() + "%3A" + tail
    return value
def diagnostic():
    return dict(range=dict(start=dict(line=0, character=0), end=dict(line=0, character=1)),
                severity=1, code="URI" + str(version), message="actual transport diagnostic")
while True:
    headers = {}
    while True:
        line = sys.stdin.buffer.readline()
        if not line:
            sys.exit(0)
        if line in (b"\r\n", b"\n"):
            break
        key, _, value = line.decode("ascii").partition(":")
        headers[key.lower()] = value.strip()
    message = json.loads(sys.stdin.buffer.read(int(headers["content-length"])))
    method, params = message.get("method"), message.get("params") or {}
    if method == "initialize":
        send(dict(id=message["id"], result=dict(capabilities=dict(textDocumentSync=1))))
    elif method in ("textDocument/didOpen", "textDocument/didChange", "textDocument/didSave"):
        doc = params["textDocument"]
        uri = doc["uri"]
        version = doc.get("version", version)
        events.append(dict(method=method, uri=uri))
        if mode == "push":
            send(dict(method="textDocument/publishDiagnostics", params=dict(
                uri=reply_uri(uri), version=version, diagnostics=[diagnostic()])))
    elif method == "textDocument/diagnostic":
        events.append(dict(method=method, uri=params["textDocument"]["uri"]))
        if mode == "related":
            send(dict(id=message["id"], result=dict(items=[], relatedDocuments={
                reply_uri(uri): dict(kind="full", items=[diagnostic()])})))
        else:
            send(dict(id=message["id"], error=dict(code=-32601, message="push only")))
    elif method == "peer/receipt":
        send(dict(id=message["id"], result=events))
    elif method == "shutdown":
        send(dict(id=message["id"], result=None))
    elif method == "exit":
        break
    elif "id" in message:
        send(dict(id=message["id"], result=None))
'''


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", ["push", "related"])
async def test_real_client_matches_encoded_reply_without_rewriting_wire_uri(tmp_path: Path, mode: str):
    source = tmp_path / "MixedCase 日本語 50% space.ts"
    source.write_text("const n = 1;\n", encoding="utf-8")
    peer = tmp_path / "uri_peer.py"
    peer.write_text(PEER, encoding="utf-8")
    client = LSPClient(server_id="uri-peer", workspace_root=str(tmp_path),
                       command=[sys.executable, "-I", "-B", str(peer), mode])
    await client.start()
    try:
        version = await client.open_file(str(source), language_id="typescript")
        await client.save_file(str(source))
        assert await client.wait_for_diagnostics(str(source), version, timeout=2)
        assert [d["code"] for d in client.diagnostics_for(str(source), fresh_only=True)] == ["URI0"]
        alternate = str(source).swapcase() if os.name == "nt" else str(source)
        source.write_text("const n = 2;\n", encoding="utf-8")
        version = await client.open_file(alternate, language_id="typescript")
        assert version == 1
        assert await client.wait_for_diagnostics(alternate, version, timeout=2)
        assert [d["code"] for d in client.diagnostics_for(str(source), fresh_only=True)] == ["URI1"]
        assert len(client._docs) == 1
        events = await client._send_request("peer/receipt", {})
        assert next(event["uri"] for event in events if event["method"] == "textDocument/didOpen") == source.absolute().as_uri()
        assert next(event["uri"] for event in events if event["method"] == "textDocument/didSave") == source.absolute().as_uri()
        assert next(event["uri"] for event in events if event["method"] == "textDocument/didChange") == Path(alternate).absolute().as_uri()
    finally:
        await client.shutdown()


@pytest.mark.windows_only
@pytest.mark.parametrize("uri,expected", [
    ("file:///c%3A/MixedCase/%E6%97%A5%E6%9C%AC%E8%AA%9E%20x%2520.py", "c:\\MixedCase\\日本語 x%20.py"),
    ("file://Server/Share/%E6%97%A5%E6%9C%AC%E8%AA%9E%20x.py", "\\\\Server\\Share\\日本語 x.py"),
    ("file://localhost/C:/MixedCase/x.py", "C:\\MixedCase\\x.py"),
])
def test_windows_uri_decodes_drive_or_unc_once(uri: str, expected: str):
    assert uri_to_path(uri) == expected


@pytest.mark.windows_only
def test_windows_unc_uri_has_authority_and_escapes_path():
    path = "\\\\Server\\Share\\MixedCase 日本語 %20.py"
    uri = file_uri(path)
    assert uri.startswith("file://Server/Share/MixedCase%20")
    assert "%2520.py" in uri
    assert uri_to_path(uri) == path


@pytest.mark.windows_only
@pytest.mark.parametrize("server", ["日本語Server", "Host%20Literal"])
def test_windows_unc_escaped_authority_roundtrips_once_without_network(server):
    path = "\\\\" + server + "\\Share\\MixedCase 日本語 %20.py"
    uri = file_uri(path)
    assert uri_to_path(uri) == path
    assert uri_to_path(file_uri(uri_to_path(uri))) == path
    if "%" in server:
        assert "Host%2520Literal/" in uri


@pytest.mark.parametrize("uri,expected", [
    ("file://%E6%97%A5%E6%9C%AC%E8%AA%9EServer/Share/MixedCase%20x.py", "//日本語Server/Share/MixedCase x.py"),
    ("file://Host%2520Literal/Share/x%2520.py", "//Host%20Literal/Share/x%20.py"),
])
def test_posix_uri_decodes_authority_once_preserving_case(monkeypatch, uri, expected):
    # Path/URI algebra only: no network filesystem or native POSIX acceptance.
    monkeypatch.setattr(client_module, "os", SimpleNamespace(name="posix", path=posixpath))
    assert uri_to_path(uri) == expected


@pytest.mark.parametrize("value", ["https://日本語Server/Share/a%20.py", "untitled:MixedCase%20.py"])
def test_nonfile_uri_is_not_decoded_or_converted_to_network_path(value):
    assert uri_to_path(value) == value


def test_posix_case_and_percent_escapes_remain_distinct(monkeypatch):
    # Platform branch test; native Windows transport above supplies process proof.
    monkeypatch.setattr(client_module, "os", SimpleNamespace(name="posix", path=posixpath))
    upper = "/Workspace/MixedCase 日本語 %20.py"
    lower = "/Workspace/mixedcase 日本語 %20.py"
    assert uri_to_path(file_uri(upper)) == upper
    assert uri_to_path(file_uri(lower)) == lower
    client = LSPClient(server_id="posix-identity", workspace_root="/Workspace", command=[])
    for path, code in ((upper, "UPPER"), (lower, "lower")):
        client._handle_publish_diagnostics({"uri": file_uri(path), "diagnostics": [{"code": code}]})
    assert client.diagnostics_for(upper) == [{"code": "UPPER"}]
    assert client.diagnostics_for(lower) == [{"code": "lower"}]
    assert len(client._docs) == 2
