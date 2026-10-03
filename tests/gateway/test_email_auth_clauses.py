"""Receiving-server verdicts must remain bound to their own RFC 8601 clause."""
import asyncio
from email.mime.text import MIMEText
from unittest.mock import AsyncMock

import pytest

from gateway.config import PlatformConfig
from plugins.platforms.email.adapter import EmailAdapter, _verify_sender_authentication


REJECTED = [
    ('spf=fail reason="spf=pass" smtp.mailfrom=admin@trusted.example', "quoted-verdict"),
    ("spf=fail (spf=pass) smtp.mailfrom=admin@trusted.example", "comment-verdict"),
    ("spf=fail smtp.mailfrom=spf=pass@trusted.example", "property-verdict"),
    ('dkim=pass header.d=evil.example reason="header.d=trusted.example"', "quoted-domain"),
    ("dkim=pass header.d=evil.example; dkim=fail header.d=trusted.example", "cross-clause-domain"),
    ("spf=fail smtp.mailfrom=x@evil.example; spf=pass smtp.mailfrom=admin@trusted.example", "duplicate-spf"),
    ("spf=pass smtp.mailfrom=admin@trusted.example (unfinished", "unbalanced-comment"),
    ('spf=pass smtp.mailfrom=admin@trusted.example reason="unfinished', "unbalanced-quote"),
    ("spf=fail " + "(" * 1000 + "spf=pass" + ")" * 1000 + " smtp.mailfrom=admin@trusted.example", "deep-comment"),
    (r"spf=pass\fail smtp.mailfrom=admin@trusted.example", "escaped-result"),
    ("spf=pass1 smtp.mailfrom=admin@trusted.example", "result-prefix"),
    ('spf=fail reason="dmarc=pass" smtp.mailfrom=x@evil.example', "quoted-dmarc"),
    ("spf=fail (dmarc=pass) smtp.mailfrom=x@evil.example", "comment-dmarc"),
    ("dmarc=pass ) header.from=trusted.example", "stray-close-comment"),
    (r'spf=fail smtp.mailfrom="a\";dmarc=pass header.from=trusted.example;x=\""@evil.example', "escaped-quote"),
    ('dmarc=pass header.from=evil.example', "misaligned-dmarc"),
    ('dmarc=fail; dmarc=pass header.from=trusted.example', "duplicate-dmarc"),
    ('dkim=pass header.d=evil.example header.d=trusted.example', "duplicate-domain"),
    ('dkim=pass header.d=evil.example; dkim=none reason="header.d=trusted.example"', "failed-clause-property"),
]
ACCEPTED = [
    "spf=pass smtp.mailfrom=admin@trusted.example",
    'spf=pass smtp.mailfrom="admin@trusted.example" (nested (comment))',
    "dkim=pass header.d=trusted.example",
    "dkim=fail header.d=evil.example; dkim=pass header.d=trusted.example",
    "dkim=pass header.d=trusted.example; dkim=pass header.d=evil.example",
    "dmarc=pass header.from=trusted.example",
    "dmarc=pass",
    "spf=fail; spf=pass smtp.mailfrom=x@evil.example; dkim=pass header.d=trusted.example",
    'dmarc=pass reason="header.from=evil.example;a;b" header.from="trusted.example"',
]


def message(verdict):
    msg = MIMEText("Test-owned inbound request")
    msg["From"] = "Admin <admin@trusted.example>"
    msg["Subject"] = "Authentication contract"
    msg["Message-ID"] = "<test-only@trusted.example>"
    msg["Authentication-Results"] = "mx.trusted.example; " + verdict
    return msg


@pytest.mark.parametrize("verdict", [x[0] for x in REJECTED], ids=[x[1] for x in REJECTED])
def test_injected_or_ambiguous_verdict_is_denied(verdict):
    ok, reason = _verify_sender_authentication(
        message(verdict), "admin@trusted.example", authserv_id="mx.trusted.example"
    )
    assert not ok, reason


@pytest.mark.parametrize("verdict", ACCEPTED)
def test_legitimate_receiving_server_verdict_is_accepted(verdict):
    ok, reason = _verify_sender_authentication(
        message(verdict), "admin@trusted.example", authserv_id="mx.trusted.example"
    )
    assert ok, reason


@pytest.mark.parametrize("verdict,accepted", [(v, False) for v, _ in REJECTED] + [(v, True) for v in ACCEPTED],
                         ids=[label for _, label in REJECTED] + [f"legitimate-{i}" for i in range(len(ACCEPTED))])
def test_native_inbound_parse_to_dispatch(monkeypatch, tmp_path, verdict, accepted):
    """Exercise the real adapter chain without IMAP, SMTP or production state."""
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    for key in ("EMAIL_ALLOW_ALL_USERS", "GATEWAY_ALLOW_ALL_USERS", "EMAIL_TRUST_FROM_HEADER"):
        monkeypatch.delenv(key, raising=False)
    for key, value in {
        "EMAIL_ADDRESS": "bot@trusted.example",
        "EMAIL_PASSWORD": "TEST_ONLY_SECRET_DO_NOT_USE",
        "EMAIL_IMAP_HOST": "mx.trusted.example",
        "EMAIL_SMTP_HOST": "mx.trusted.example",
        "EMAIL_ALLOWED_USERS": "admin@trusted.example",
    }.items():
        monkeypatch.setenv(key, value)
    adapter = EmailAdapter(PlatformConfig(enabled=True, extra={"authserv_id": "mx.trusted.example"}))
    adapter.handle_message = AsyncMock()
    parsed = adapter._parse_fetched_message(b"test-owned-uid", message(verdict).as_bytes())
    assert parsed is not None
    asyncio.run(adapter._dispatch_message(parsed))
    assert adapter.handle_message.await_count == int(accepted)
