"""Bounded loopback streaming through Requests and the existing TTS reader.

These tests use no provider, credential, decoder double, or production resource.
The chunk-size line is finite and at most one byte above the 64 KiB boundary.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import threading

import pytest
import requests

from tools.tts_tool import _read_tts_response_bytes


CHUNK_LINE_LIMIT = 65536
SOCKET_TIMEOUT = 5.0


def _chunked_body(chunks: tuple[bytes, ...]) -> bytes:
    return b"".join(
        f"{len(chunk):x}\r\n".encode("ascii") + chunk + b"\r\n"
        for chunk in chunks
        if chunk
    ) + b"0\r\n\r\n"


def _extension_body(line_length: int) -> bytes:
    prefix = b"1;pad="
    line = prefix + b"a" * (line_length - len(prefix) - 2) + b"\r\n"
    assert len(line) == line_length
    return line + b"x\r\n0\r\n\r\n"


@contextmanager
def _loopback_response(wire_body: bytes) -> Iterator[requests.Response]:
    """Own the socket, Requests session, server and every request thread."""
    assert len(wire_body) <= CHUNK_LINE_LIMIT + 64
    finished = threading.Event()
    errors: list[Exception] = []

    class Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def setup(self) -> None:
            super().setup()
            self.connection.settimeout(SOCKET_TIMEOUT)

        def log_message(self, format: str, *args: object) -> None:
            pass

        def do_GET(self) -> None:
            try:
                assert self.path == "/stream"
                self.send_response(200)
                self.send_header("Content-Type", "application/octet-stream")
                self.send_header("Transfer-Encoding", "chunked")
                self.send_header("Connection", "close")
                self.end_headers()
                self.wfile.write(wire_body)
                self.wfile.flush()
            except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
                # Rejecting a partial response may close its test-owned peer.
                pass
            except Exception as exc:
                errors.append(exc)
            finally:
                self.close_connection = True
                finished.set()

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    server.daemon_threads = False
    thread = threading.Thread(
        target=server.serve_forever,
        kwargs={"poll_interval": 0.05},
        name="urllib3-security-loopback",
        daemon=False,
    )
    session = requests.Session()
    session.trust_env = False
    response: requests.Response | None = None
    thread.start()
    try:
        response = session.get(
            f"http://127.0.0.1:{server.server_port}/stream",
            stream=True,
            timeout=(SOCKET_TIMEOUT, SOCKET_TIMEOUT),
            allow_redirects=False,
        )
        assert response.status_code == 200
        assert isinstance(response, requests.Response)
        assert response._content is False  # The real reader must consume streaming.
        yield response
    finally:
        if response is not None:
            response.close()
        session.close()
        server.shutdown()
        server.server_close()  # Joins non-daemon owned request threads.
        thread.join(timeout=SOCKET_TIMEOUT)
        assert not thread.is_alive(), "owned HTTP serving thread did not terminate"
        assert finished.is_set(), "owned HTTP handler did not finish"
        assert not errors, errors


def _assert_reader_closed(response: requests.Response) -> None:
    # Checked before the fixture's cleanup; the fixture cannot satisfy this.
    assert response.raw.closed
    assert response.raw._fp.isclosed()


@pytest.mark.parametrize(
    "chunks",
    [
        ("こんにちは".encode("utf-8")[:4], "こんにちは".encode("utf-8")[4:]),
        (b"\x00\xff\x80", b"\r\n\x00"),
        (),
    ],
    ids=["split-utf8", "binary", "empty"],
)
def test_normal_chunked_body_preserves_bytes(chunks: tuple[bytes, ...]) -> None:
    expected = b"".join(chunks)
    with _loopback_response(_chunked_body(chunks)) as response:
        assert _read_tts_response_bytes(response, label="loopback", limit=64) == expected
        _assert_reader_closed(response)


@pytest.mark.parametrize("line_length", [16, CHUNK_LINE_LIMIT])
def test_bounded_chunk_extension_is_accepted(line_length: int) -> None:
    with _loopback_response(_extension_body(line_length)) as response:
        assert _read_tts_response_bytes(response, label="loopback", limit=1) == b"x"
        _assert_reader_closed(response)


def test_exact_body_cap_is_accepted_and_closed() -> None:
    with _loopback_response(_chunked_body((b"1234", b"5678"))) as response:
        assert _read_tts_response_bytes(response, label="loopback", limit=8) == b"12345678"
        _assert_reader_closed(response)


def test_over_body_cap_is_rejected_and_closed() -> None:
    with _loopback_response(_chunked_body((b"1234", b"56789", b"unread"))) as response:
        with pytest.raises(RuntimeError, match="loopback response exceeds 8 bytes"):
            _read_tts_response_bytes(response, label="loopback", limit=8)
        _assert_reader_closed(response)


def test_truncated_chunk_is_rejected_and_closed() -> None:
    with _loopback_response(b"4\r\nab") as response:
        with pytest.raises(requests.exceptions.ChunkedEncodingError):
            _read_tts_response_bytes(response, label="loopback", limit=8)
        _assert_reader_closed(response)


def test_overlong_chunk_header_is_rejected_and_closed() -> None:
    with _loopback_response(_extension_body(CHUNK_LINE_LIMIT + 1)) as response:
        try:
            with pytest.raises(
                requests.exceptions.ChunkedEncodingError,
                match=r"(?i)(65536|chunk size|line too long)",
            ):
                _read_tts_response_bytes(response, label="loopback", limit=8)
        finally:
            _assert_reader_closed(response)
