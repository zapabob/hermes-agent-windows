"""A non-retryable 4xx (rejected OAuth token, bad key) must reach UI clients with the
classifier's verdict: without ``failure_reason`` the desktop error card read a 401 as a
retryable "Provider error" and offered Retry instead of a re-login.

Windows keeps the terminal non-retryable path inlined in ``agent/conversation_loop.py``
(upstream extracted ``agent/turn_recovery.nonretryable_client_error_result``). This test
locks the stamped result shape that path must emit for the error-surface classifier.
"""
from __future__ import annotations

from agent.error_classifier import classify_api_error
from agent.error_surface import LAYER_AUTH, build_error_surface_from_result


class _Rejected(Exception):
    status_code = 401

    def __init__(self) -> None:
        super().__init__("HTTP 401: User not found.")


def test_nonretryable_401_result_classifies_as_auth_for_the_ui():
    error = _Rejected()
    classified = classify_api_error(error, provider="nous", model="m")
    # Mirror the conversation_loop non-retryable abort result stamp (not the
    # billing/content-policy specializations).
    result = {
        "final_response": str(error),
        "messages": [],
        "api_calls": 1,
        "completed": False,
        "failed": True,
        "error": str(error),
        "failure_reason": classified.reason.value,
        "failure_retryable": bool(classified.retryable),
    }
    assert result["failure_reason"] == classified.reason.value
    assert result["failure_retryable"] is classified.retryable is False

    surface = build_error_surface_from_result(result, provider="nous", model="m")
    assert surface["layer"] == LAYER_AUTH
    assert surface["retryable"] is False
    assert surface["auth_kind"] == "oauth"
