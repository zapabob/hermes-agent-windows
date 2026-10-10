"""Concrete CLI callback producers preserve exact present issuer values."""

import http.server
import io
import sys
import threading
from urllib.parse import urlencode
from urllib.request import urlopen

import pytest

from tools.mcp_oauth import (
    _authorization_code_result,
    _make_callback_handler,
    _paste_callback_reader,
)


@pytest.mark.parametrize("producer", ["http", "paste"])
@pytest.mark.parametrize("issuer", [None, "", "https://owned.example/issuer", "https://owned.example/issuer/"])
def test_cli_issuer_exact_presence(producer, issuer, monkeypatch):
    handler, result = _make_callback_handler()
    params = {"code": "owned-code", "state": "owned-state"}
    if issuer is not None:
        params["iss"] = issuer
    query = urlencode(params)
    if producer == "paste":
        monkeypatch.setattr(sys, "stdin", io.StringIO("?" + query + "\n"))
        _paste_callback_reader(result)
    else:
        class OwnedServer(http.server.HTTPServer):
            def get_request(self):
                request, address = super().get_request()
                request.settimeout(3)
                return request, address

        server = OwnedServer(("127.0.0.1", 0), handler)
        server.timeout = 4
        worker = threading.Thread(target=server.handle_request, name="owned-m03-cli-callback")
        try:
            worker.start()
            with urlopen(f"http://127.0.0.1:{server.server_port}/callback?{query}", timeout=3) as response:
                assert response.status == 200
        finally:
            server.server_close()
            if worker.ident is not None:
                worker.join(timeout=5)
            assert not worker.is_alive()
    assert result["auth_code"] == "owned-code"
    assert result["state"] == "owned-state"
    assert result["iss"] == issuer
    actual = _authorization_code_result(result["auth_code"], result["state"], result["iss"])
    assert actual.code == "owned-code" and actual.state == "owned-state"
    assert actual.iss == issuer
