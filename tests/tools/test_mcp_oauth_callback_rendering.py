"""Exercise the OAuth callback's real HTTP response and logging boundary."""

import logging
import socket
import threading
from contextlib import contextmanager
from html.parser import HTMLParser
from http.client import HTTPConnection
from http.server import HTTPServer
from urllib.parse import urlencode

import pytest

from tools.mcp_oauth import _make_callback_handler


class _Page(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.tags: list[str] = []
        self.text: list[str] = []

    def handle_starttag(self, tag: str, attrs: list) -> None:
        self.tags.append(tag)

    def handle_data(self, data: str) -> None:
        self.text.append(data)


@contextmanager
def _callback_server():
    handler, result = _make_callback_handler()

    class _BoundedServer(HTTPServer):
        def get_request(self):
            connection, address = super().get_request()
            connection.settimeout(3)
            return connection, address

    server = _BoundedServer(("127.0.0.1", 0), handler)
    server.timeout = 3
    worker = threading.Thread(target=server.handle_request)
    worker.start()
    try:
        yield server.server_address, result
    finally:
        worker.join(timeout=5)
        server.server_close()
        assert not worker.is_alive(), "test-owned callback thread did not exit"


def _request(address: tuple[str, int], params: dict[str, str]):
    connection = HTTPConnection(*address, timeout=3)
    try:
        connection.request("GET", "/callback?" + urlencode(params))
        response = connection.getresponse()
        body = response.read().decode("utf-8")
        assert response.status == 200
        assert response.getheader("Content-Type") == "text/html; charset=utf-8"
        return body
    finally:
        connection.close()


@pytest.mark.parametrize(
    "error",
    [
        "access_denied",
        '<script>alert("fixture")</script>',
        '</p><img src=x onerror="fixture()"><p>',
        "< > & \" '",
        "認証を中止しました\nもう一度お試しください。",
        "&lt;script&gt; &amp; &#39;",
    ],
)
def test_callback_renders_untrusted_error_as_text(error: str):
    with _callback_server() as (address, result):
        body = _request(address, {"error": error})

    page = _Page()
    page.feed(body)
    assert page.tags == ["html", "body", "h2", "p"]
    assert "".join(page.text) == "Authorization FailedError: " + error
    assert result["error"] == error
    assert result["auth_code"] is None


@pytest.mark.parametrize("success", [False, True])
def test_callback_does_not_expose_secret_query_in_page_or_log(caplog, success):
    params = {
        "state": "fixture-private-state",
        "access_token": "fixture-private-token",
        "unrecognized": "fixture-private-query",
    }
    if success:
        params["code"] = "fixture-private-code"
    else:
        params["error"] = "access_denied"

    with caplog.at_level(logging.DEBUG, logger="tools.mcp_oauth"):
        with _callback_server() as (address, result):
            body = _request(address, params)

    for name in ("state", "access_token", "unrecognized", "code"):
        if name in params:
            assert params[name] not in body
            assert params[name] not in caplog.text
    assert result["state"] == params["state"]
    assert result["auth_code"] == params.get("code")
    if success:
        assert "Authorization Successful" in body
        assert "return to Hermes" in body
    else:
        assert "Authorization Failed" in body


def test_callback_missing_error_retains_unknown_message():
    with _callback_server() as (address, result):
        body = _request(address, {})
    assert "Error: unknown" in body
    assert result["error"] is None


@pytest.mark.parametrize(
    ("request_line", "status"),
    [
        (
            "GET /callback?code=fixture-private-code&state=fixture-private-state&x=a b HTTP/1.1",
            400,
        ),
        (
            "fixture-private-method /callback?access_token=fixture-private-token HTTP/1.1",
            501,
        ),
    ],
)
def test_callback_http_errors_do_not_reflect_request_secrets(
    caplog, request_line, status
):
    with caplog.at_level(logging.DEBUG, logger="tools.mcp_oauth"):
        with _callback_server() as (address, result):
            with socket.create_connection(address, timeout=3) as connection:
                connection.sendall(
                    (
                        request_line
                        + "\r\nHost: localhost\r\nConnection: close\r\n\r\n"
                    ).encode("ascii")
                )
                response = bytearray()
                while chunk := connection.recv(65536):
                    response.extend(chunk)
    assert f" {status} ".encode("ascii") in response
    assert b"fixture-private-" not in response
    assert "fixture-private-" not in caplog.text
    assert result == {"auth_code": None, "state": None, "error": None, "iss": None}
