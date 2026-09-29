"""Credentials must never reach the logs through a provider base URL.

Covers ``agent.redact.redact_base_url`` and the log sites that format a
base URL (the stale ``OPENAI_BASE_URL`` warning in the auxiliary client and
the context-length fallback warning), plus the global ``RedactingFormatter``
for NVIDIA ``nvapi-`` keys.
"""

import io
import logging
from unittest.mock import patch

import pytest

import agent.redact as redact_mod
from agent.redact import RedactingFormatter, redact_base_url

# Synthetic values assembled at runtime; not real credentials.
NVAPI_TOKEN = "nvapi-" + "Zq9Xw2" * 10 + "_-ab"
OPAQUE_TOKEN = "Tk" + "7rLm" * 10
USER_SECRET = "hunter2-" + "p4ss" * 4
QUERY_SECRET = "qs-" + "9f8e" * 6

NORMAL_URLS = [
    "https://integrate.api.nvidia.com/v1",
    "http://127.0.0.1:8080/v1",
    "https://openrouter.ai/api/v1",
    "https://example.com/v1?api-version=2024-10-21",
]


def _assert_clean(text: str) -> None:
    for secret in (NVAPI_TOKEN, NVAPI_TOKEN[6:], OPAQUE_TOKEN, USER_SECRET, QUERY_SECRET):
        assert secret not in text


# ── redact_base_url ─────────────────────────────────────────────────────


@pytest.mark.parametrize("url", NORMAL_URLS)
def test_normal_urls_unchanged(url):
    assert redact_base_url(url) == url


def test_none_and_empty():
    assert redact_base_url(None) == ""
    assert redact_base_url("") == ""


def test_api_key_pasted_into_base_url_is_replaced():
    out = redact_base_url(NVAPI_TOKEN)
    _assert_clean(out)
    assert str(len(NVAPI_TOKEN)) in out


def test_opaque_non_url_token_is_replaced():
    out = redact_base_url(OPAQUE_TOKEN)
    _assert_clean(out)
    assert out.startswith("<redacted non-URL value")


def test_nvapi_token_inside_url_is_masked():
    out = redact_base_url(f"https://proxy.example.com/{NVAPI_TOKEN}/v1")
    _assert_clean(out)
    assert out.startswith("https://proxy.example.com/")
    assert out.endswith("/v1")


def test_userinfo_is_stripped():
    out = redact_base_url(f"https://alice:{USER_SECRET}@llm.example.com/v1")
    _assert_clean(out)
    assert "alice" not in out
    assert out == "https://***@llm.example.com/v1"


def test_bare_token_userinfo_is_stripped():
    out = redact_base_url(f"https://{OPAQUE_TOKEN}@llm.example.com/v1")
    _assert_clean(out)
    assert out.endswith("@llm.example.com/v1")


def test_credential_query_params_masked_public_params_kept():
    out = redact_base_url(
        f"https://llm.example.com/v1?api_key={QUERY_SECRET}&region=eu&token={QUERY_SECRET}"
    )
    _assert_clean(out)
    assert "region=eu" in out
    assert "api_key=***" in out and "token=***" in out


def test_redacts_even_when_global_redaction_disabled(monkeypatch):
    monkeypatch.setattr(redact_mod, "_REDACT_ENABLED", False)
    _assert_clean(redact_base_url(f"https://u:{USER_SECRET}@h.example/v1?key={QUERY_SECRET}"))
    _assert_clean(redact_base_url(NVAPI_TOKEN))


# ── Log sites ───────────────────────────────────────────────────────────


def _stale_base_url_warning(monkeypatch, caplog, env_value: str) -> str:
    import agent.auxiliary_client as aux

    for key in ("OPENAI_API_KEY", "NVIDIA_API_KEY", "ANTHROPIC_API_KEY"):
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setattr(aux, "_stale_base_url_warned", False)
    monkeypatch.setenv("OPENAI_BASE_URL", env_value)
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-or-test")
    aux._aux_unhealthy_until.clear()
    with (
        patch("agent.auxiliary_client._read_main_provider", return_value="openrouter"),
        patch("agent.auxiliary_client._read_main_model", return_value="google/gemini-flash"),
        caplog.at_level(logging.WARNING, logger="agent.auxiliary_client"),
    ):
        aux._resolve_auto()
    messages = [r.getMessage() for r in caplog.records if "OPENAI_BASE_URL is set" in r.getMessage()]
    assert len(messages) == 1
    return messages[0]


def test_stale_base_url_warning_masks_pasted_nvapi_key(monkeypatch, caplog):
    msg = _stale_base_url_warning(monkeypatch, caplog, NVAPI_TOKEN)
    _assert_clean(msg)
    assert "<redacted non-URL value" in msg


def test_stale_base_url_warning_masks_userinfo_and_query(monkeypatch, caplog):
    msg = _stale_base_url_warning(
        monkeypatch, caplog,
        f"https://bob:{USER_SECRET}@proxy.example.com/v1?api_key={QUERY_SECRET}",
    )
    _assert_clean(msg)
    assert "proxy.example.com/v1" in msg


def test_stale_base_url_warning_keeps_normal_url(monkeypatch, caplog):
    msg = _stale_base_url_warning(monkeypatch, caplog, "http://localhost:11434/v1")
    assert "(http://localhost:11434/v1)" in msg


def test_context_length_fallback_warning_masks_base_url(monkeypatch, caplog):
    import agent.model_metadata as mm

    monkeypatch.setattr(mm, "_FALLBACK_WARNED", set())
    with caplog.at_level(logging.WARNING, logger="agent.model_metadata"):
        mm._warn_context_length_fallback("m-secret", f"https://u:{USER_SECRET}@h.example/{NVAPI_TOKEN}")
        mm._warn_context_length_fallback("m-plain", "https://integrate.api.nvidia.com/v1")
    text = "\n".join(r.getMessage() for r in caplog.records)
    _assert_clean(text)
    assert "base_url=https://integrate.api.nvidia.com/v1)" in text


# ── Global formatter ────────────────────────────────────────────────────


def test_redacting_formatter_masks_nvapi_key_in_any_message(monkeypatch):
    monkeypatch.setattr(redact_mod, "_REDACT_ENABLED", True)
    stream = io.StringIO()
    handler = logging.StreamHandler(stream)
    handler.setFormatter(RedactingFormatter("%(levelname)s %(message)s"))
    log = logging.getLogger("tests.redact_base_url.formatter")
    log.addHandler(handler)
    log.propagate = False
    try:
        log.warning("conversation turn: msg=%r", NVAPI_TOKEN)
    finally:
        log.removeHandler(handler)
    out = stream.getvalue()
    _assert_clean(out)
    assert "nvapi-" in out
