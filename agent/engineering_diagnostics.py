"""Fixed engineering failure metadata, never exception text or credentials.

Classification is diagnostic only. It does not grant retry, execution, model
fallback, or permission to discard a lease. Unknown exceptions stay unknown.
"""
from __future__ import annotations

from contextlib import contextmanager


def failure_code(error: BaseException) -> str:
    """Map known error classes/statuses to a small non-secret vocabulary."""
    for cls, code in (
        (PermissionError, "permission_denied"),
        (TimeoutError, "timeout"),
        (ConnectionError, "connection_error"),
        (TypeError, "call_contract_error"),
        (ValueError, "invalid_payload"),
        (ImportError, "missing_dependency"),
    ):
        if isinstance(error, cls):
            return code
    try:
        from openai import APIConnectionError, APIStatusError, APITimeoutError
    except ImportError:
        return "host_error"
    if isinstance(error, APITimeoutError):
        return "timeout"
    if isinstance(error, APIConnectionError):
        return "connection_error"
    if isinstance(error, APIStatusError):
        status = error.status_code
        if type(status) is not int:
            return "provider_error"
        if status >= 500:
            return "provider_unavailable"
        return {
            400: "provider_request_rejected", 401: "provider_authentication",
            403: "provider_authorisation", 429: "provider_rate_limit",
        }.get(status, "provider_error")
    return "host_error"


@contextmanager
def diagnostic_boundary(boundary, report=None):
    """Report a fixed boundary/code to the trusted host, preserving the exception.

    A failed diagnostic write propagates as failure; no successful checkpoint
    is fabricated. Callers must use literal boundary names, not model content.
    """
    try:
        yield
    except Exception as error:
        if report is not None:
            report(boundary, failure_code(error))
        raise
