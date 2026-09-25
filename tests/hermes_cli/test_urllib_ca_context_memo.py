"""The explicit CA context for Hermes-owned urllib openers is parsed once and memoised safely."""

from __future__ import annotations

import logging
import ssl
import urllib.request
from pathlib import Path

import pytest

import hermes_cli.urllib_security as urllib_security

_CA_BUNDLE_ENV_VARS = ("HERMES_CA_BUNDLE", "SSL_CERT_FILE", "REQUESTS_CA_BUNDLE", "CURL_CA_BUNDLE")


@pytest.fixture(autouse=True)
def _isolated_ca_state(monkeypatch):
    for name in _CA_BUNDLE_ENV_VARS:
        monkeypatch.delenv(name, raising=False)
    urllib_security._HTTPS_CONTEXT_CACHE = None
    yield
    urllib_security._HTTPS_CONTEXT_CACHE = None


def _counting_context_factory():
    """Return (factory, calls) where each call yields a distinct context object."""
    calls: list[str | None] = []

    def create_default_context(*, cafile=None):
        calls.append(cafile)
        return ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)

    return create_default_context, calls


def test_hermes_owned_openers_parse_the_ca_bundle_once(monkeypatch, tmp_path):
    ca_bundle = tmp_path / "corporate-ca.pem"
    ca_bundle.write_text("-----BEGIN CERTIFICATE-----\n", encoding="utf-8")
    factory, calls = _counting_context_factory()
    monkeypatch.setenv("HERMES_CA_BUNDLE", str(ca_bundle))
    monkeypatch.setattr(ssl, "create_default_context", factory)
    monkeypatch.setattr(urllib.request, "_opener", None)

    contexts = []
    for _ in range(5):
        opener = urllib_security._secure_opener_from_installed_policy("https://models.example.test/v1")
        contexts.extend(
            handler._context
            for handler in opener.handlers
            if isinstance(handler, urllib.request.HTTPSHandler)
        )

    assert calls == [str(ca_bundle)]
    assert len(contexts) == 5
    assert all(context is contexts[0] for context in contexts)


def test_rotated_ca_bundle_is_picked_up(monkeypatch, tmp_path):
    ca_bundle = tmp_path / "corporate-ca.pem"
    ca_bundle.write_text("first", encoding="utf-8")
    factory, calls = _counting_context_factory()
    monkeypatch.setenv("HERMES_CA_BUNDLE", str(ca_bundle))
    monkeypatch.setattr(ssl, "create_default_context", factory)

    first = urllib_security._resolved_https_context()
    assert urllib_security._resolved_https_context() is first

    ca_bundle.write_text("a rotated bundle with a different length", encoding="utf-8")
    rotated = urllib_security._resolved_https_context()

    assert rotated is not first
    assert calls == [str(ca_bundle), str(ca_bundle)]


def test_fallback_bundle_change_does_not_invalidate_the_memo(monkeypatch, tmp_path):
    """The memo keys on the preferred bundle only: the fallback was never read."""
    preferred = tmp_path / "corporate-ca.pem"
    fallback = tmp_path / "cacert.pem"
    preferred.write_text("preferred", encoding="utf-8")
    fallback.write_text("first", encoding="utf-8")
    factory, calls = _counting_context_factory()
    monkeypatch.setattr(ssl, "create_default_context", factory)
    monkeypatch.setattr(
        urllib_security, "_ca_bundle_candidates", lambda: (str(preferred), str(fallback)),
    )

    first = urllib_security._resolved_https_context()
    fallback.write_text("a rotated fallback bundle with a different length", encoding="utf-8")

    assert urllib_security._resolved_https_context() is first
    assert calls == [str(preferred)]


def test_default_certificates_fallback_is_logged_once_after_all_bundles_fail(monkeypatch, caplog):
    def create_default_context(*, cafile=None):
        raise ssl.SSLError(f"bad bundle {cafile}")

    monkeypatch.setattr(ssl, "create_default_context", create_default_context)

    with caplog.at_level(logging.WARNING, logger=urllib_security.logger.name):
        assert urllib_security._build_https_context(("/a.pem", "/b.pem")) == (None, None)

    messages = [record.getMessage() for record in caplog.records]
    per_failure = [m for m in messages if "trying the next bundle" in m]
    assert [m.split(":")[0] for m in per_failure] == [
        "CA bundle could not be loaded from /a.pem",
        "CA bundle could not be loaded from /b.pem",
    ]
    assert [m for m in messages if "falling back to default certificates" in m] == [
        "No configured CA bundle could be loaded — falling back to default certificates"
    ]


@pytest.mark.parametrize(
    ("candidates", "first_load_fails_for", "expected_load_sequence"),
    [
        pytest.param(
            ("corporate-ca.pem",), "corporate-ca.pem",
            ["corporate-ca.pem", "corporate-ca.pem"], id="no-context",
        ),
        pytest.param(
            ("corporate-ca.pem", "cacert.pem"), "corporate-ca.pem",
            ["corporate-ca.pem", "cacert.pem", "corporate-ca.pem"], id="fallback-context",
        ),
    ],
)
def test_a_failed_preferred_bundle_load_is_not_memoised(
    monkeypatch, tmp_path, candidates, first_load_fails_for, expected_load_sequence
):
    """A transient failure of the preferred bundle is retried on the next request, not pinned."""
    paths = tuple(str(tmp_path / name) for name in candidates)
    for path in paths:
        Path(path).write_text("pem", encoding="utf-8")
    failing_path = str(tmp_path / first_load_fails_for)
    expected = [str(tmp_path / name) for name in expected_load_sequence]
    monkeypatch.setattr(urllib_security, "_ca_bundle_candidates", lambda: paths)

    state = {"failing": True, "loads": []}

    def load_verify_locations(self, cafile=None, capath=None, cadata=None):
        state["loads"].append(cafile)
        if state["failing"] and cafile == failing_path:
            raise ssl.SSLError("transient read failure")

    monkeypatch.setattr(ssl.SSLContext, "load_verify_locations", load_verify_locations)

    first = urllib_security._resolved_https_context()
    assert (first is None) == (len(candidates) == 1)
    assert state["loads"] == expected[: len(candidates)]

    state["failing"] = False
    recovered = urllib_security._resolved_https_context()

    assert recovered is not None
    assert recovered is not first
    assert state["loads"] == expected
    assert urllib_security._resolved_https_context() is recovered
    assert state["loads"] == expected


def test_file_signature_changes_when_content_length_changes(tmp_path):
    from utils import file_signature

    target = tmp_path / "bundle.pem"
    target.write_text("one", encoding="utf-8")
    before = file_signature(target.stat())
    target.write_text("a longer body", encoding="utf-8")

    assert file_signature(target.stat()) != before
    assert len(before) == 4
