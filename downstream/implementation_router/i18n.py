"""Localised presentation only; protocol states and reason codes are invariant."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

REASON_CODES = frozenset(('all_required_host_checks_passed', 'credential_boundary_unavailable', 'duplicate_json_key', 'handoff_budget_exhausted', 'host_boundary_error_no_replay', 'host_cancellation', 'incomplete_verification', 'invalid_cancellation_state', 'invalid_json_output', 'invalid_or_oversized_output', 'invalid_plan_contract', 'invalid_required_checks', 'invalid_run_input', 'invalid_worker_contract', 'missing_workspace_snapshot', 'non_finite_json_value', 'output_must_be_an_object', 'planner_reentry_budget_exhausted', 'routing_disabled', 'stage_binding_mismatch', 'stage_call_budget_exhausted', 'stage_completion_uncertain', 'unknown_result', 'untrusted_verification_receipt', 'verification_binding_mismatch', 'verification_not_conclusively_complete'))


def load_catalog() -> dict[str, dict[str, str]]:
    return json.loads(Path(__file__).with_name("locales.json").read_text(encoding="utf-8"))


def normalise_locale(value: object) -> str:
    if not isinstance(value, str):
        return "en"
    value = value.strip().lower().replace("_", "-")
    if value == "zh-hant" or value.startswith(("zh-hant-", "zh-tw", "zh-hk", "zh-mo")):
        return "zh-hant"
    for locale in ("en", "ja", "zh", "ar"):
        if value == locale or value.startswith(locale + "-"):
            return locale
    if value in ("arabic", "العربية"):
        return "ar"
    return "en"


def text_direction(locale: object) -> str:
    return "rtl" if normalise_locale(locale) == "ar" else "ltr"


def render_result(result: Any, locale: object = "en") -> dict[str, Any]:
    language = normalise_locale(locale)
    catalog = load_catalog()
    messages = catalog.get(language, catalog["en"])
    state = result.state if result.state in {"SUCCEEDED", "BLOCKED", "CANCELLED"} else "BLOCKED"
    reason = result.reason if result.reason in REASON_CODES else "unknown_result"
    if reason == "unknown_result":
        state = "BLOCKED"
    message = messages.get(reason, messages[state])
    return {
        "state": state, "reason_code": reason, "message": message,
        "locale": language, "direction": text_direction(language),
        "stage_calls": result.stage_calls, "revision": result.revision,
    }
