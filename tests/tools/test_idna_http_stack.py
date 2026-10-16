"""IDNA normalization and native HTTP consumers of the locked dependency."""
from __future__ import annotations

import asyncio
import http.server
import ipaddress
import socket
import threading

import idna
import pytest


@pytest.mark.parametrize(("domain", "normalized"), [
    ("Example.COM", "example.com"), ("ＦＯＯ.example", "foo.example"),
    ("例え.test", "例え.test"), ("münich.example", "münich.example"),
    ("bücher.example", "bücher.example"), ("faß.example", "faß.example"),
])
def test_valid_hostname_normalization_and_round_trip(domain, normalized):
    assert idna.uts46_remap(domain, std3_rules=True) == normalized
    assert idna.decode(idna.encode(domain, uts46=True)) == normalized


@pytest.mark.parametrize("domain", [
    "tenant_service.example", "tenant!service.example", "tenant＿service.example",
    "aβ_.example", "a！b.example",
])
def test_explicit_std3_rejects_ascii_and_mapped_punctuation(domain):
    with pytest.raises(idna.InvalidCodepoint):
        idna.uts46_remap(domain, std3_rules=True)


def test_default_remap_rules_also_reject_non_ldh_ascii():
    with pytest.raises(idna.InvalidCodepoint):
        idna.uts46_remap("tenant_service.example")


@pytest.mark.parametrize(("domain", "expected"), [
    ("TENANT_service.example", "tenant_service.example"),
    ("tenant＿service.example", "tenant_service.example"), ("a！b.example", "a!b.example"),
])
def test_explicit_non_std3_mapping_preserves_its_useful_behavior(domain, expected):
    assert idna.uts46_remap(domain, std3_rules=False) == expected


@pytest.mark.parametrize("std3", [True, False])
def test_encode_still_validates_labels_after_optional_mapping(std3):
    with pytest.raises(idna.IDNAError):
        idna.encode("tenant_service.example", uts46=True, std3_rules=std3)


def test_noncanonical_alabel_is_rejected_while_its_canonical_form_round_trips():
    canonical = b"xn--bbk"
    decoded = idna.ulabel(canonical)
    assert decoded == "ま"
    assert idna.alabel(decoded) == canonical
    with pytest.raises(idna.IDNAError):
        idna.ulabel(b"xn---bbk")


@pytest.mark.parametrize(("domain", "codepoint", "position"), [
    ("tenant_service.example", ord("_"), 7), ("a！b.example", ord("！"), 2),
    ("aβ_.example", ord("_"), 3),
])
def test_mapping_error_remains_unicode_error_with_structured_context(domain, codepoint, position):
    with pytest.raises(UnicodeError) as caught:
        idna.uts46_remap(domain, std3_rules=True)
    error = caught.value
    assert isinstance(error, idna.InvalidCodepoint)
    assert (error.code, error.text, error.codepoint, error.position) == (
        "uts46_std3", domain, codepoint, position,
    )


@pytest.mark.parametrize("entrypoint", ["ulabel", "alabel", "encode", "decode"])
def test_noncanonical_label_is_rejected_by_public_entrypoints(entrypoint):
    with pytest.raises(idna.IDNAError) as caught:
        getattr(idna, entrypoint)("xn---bbk")
    assert caught.value.code == "non_canonical_alabel"


def test_display_mode_keeps_invalid_wire_label_without_fabricating_unicode():
    assert idna.decode("XN---BBK", display=True) == "xn---bbk"


@pytest.mark.parametrize("consumer", ["httpx", "httpx2", "requests", "yarl"])
@pytest.mark.parametrize(("domain", "expected", "decoded"), [
    ("WWW.Example.COM", "www.example.com", "www.example.com"),
    ("例え.test", "xn--r8jz45g.test", "例え.test"),
    ("faß.example", "xn--fa-hia.example", "faß.example"),
    ("xn--bbk", "xn--bbk", "ま"),
])
def test_unicode_url_consumers_keep_the_same_ascii_wire_hostname(consumer, domain, expected, decoded):
    module = pytest.importorskip(consumer)
    if consumer == "requests":
        prepared = module.Request("GET", f"http://{domain}/path").prepare()
        assert prepared.url == f"http://{expected}/path"
    else:
        url = module.URL(f"http://{domain}/path")
        if consumer == "yarl":
            assert url.raw_host == expected
        else:
            assert url.raw_host == expected.encode("ascii")
        assert url.host == decoded


@pytest.mark.parametrize("consumer", ["httpx", "httpx2"])
def test_ascii_url_constructor_and_decoded_host_have_distinct_contracts(consumer):
    module = pytest.importorskip(consumer)
    url = module.URL("http://xn---bbk/path")
    assert url.raw_host == b"xn---bbk"
    if consumer == "httpx2":
        assert url.host == "xn---bbk"
    else:
        with pytest.raises(idna.IDNAError):
            _ = url.host


@pytest.fixture
def owned_unicode_peer(monkeypatch):
    expected = "xn--r8jz45g.test"
    original_resolver = socket.getaddrinfo
    resolutions, wire = [], []

    def resolver(host, port, *args, **kwargs):
        name = host.decode("ascii") if isinstance(host, bytes) else host
        if name == expected:
            resolutions.append(name)
            return original_resolver("127.0.0.1", port, *args, **kwargs)
        try:
            if ipaddress.ip_address(name).is_loopback:
                return original_resolver(host, port, *args, **kwargs)
        except ValueError:
            pass
        raise AssertionError("Test attempted resolution outside its owned peer")

    class Handler(http.server.BaseHTTPRequestHandler):
        def log_message(self, *_args):
            pass

        def do_GET(self):
            wire.append({"host": self.headers.get("Host"), "path": self.path,
                         "authorization": bool(self.headers.get("Authorization")),
                         "proxy_authorization": bool(self.headers.get("Proxy-Authorization"))})
            self.send_response(200)
            self.send_header("Content-Length", "2")
            self.end_headers()
            self.wfile.write(b"ok")

    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    worker = threading.Thread(target=lambda: server.serve_forever(poll_interval=0.05))
    monkeypatch.setattr(socket, "getaddrinfo", resolver)
    worker.start()
    try:
        yield f"http://例え.test:{server.server_port}/path", server.server_port, expected, resolutions, wire
    finally:
        server.shutdown()
        server.server_close()
        worker.join(3)
    assert not worker.is_alive()


@pytest.mark.parametrize("consumer", ["httpx", "httpx2", "requests"])
def test_actual_http_request_uses_unicode_dependency_and_owned_peer(consumer, owned_unicode_peer):
    module = pytest.importorskip(consumer)
    url, port, expected, resolutions, wire = owned_unicode_peer
    if consumer == "requests":
        with module.Session() as client:
            client.trust_env = False
            response = client.get(url, timeout=3)
    else:
        with module.Client(trust_env=False, timeout=3) as client:
            response = client.get(url)
    assert response.status_code == 200 and response.text == "ok"
    assert resolutions and set(resolutions) == {expected}
    assert wire == [{"host": f"{expected}:{port}", "path": "/path",
                     "authorization": False, "proxy_authorization": False}]


def test_anyio_unicode_resolution_reaches_only_the_owned_peer(owned_unicode_peer):
    anyio = pytest.importorskip("anyio")
    _url, port, expected, resolutions, _wire = owned_unicode_peer
    result = asyncio.run(anyio.getaddrinfo("例え.test", port, type=socket.SOCK_STREAM))
    assert result and all(row[4][0] == "127.0.0.1" for row in result)
    assert resolutions == [expected]
