"""Fresh field projections; never return configuration or credential objects."""
from __future__ import annotations

import re

from .contracts import ControlError

ENGINEERING_SLOTS = ("engineering_planner", "engineering_worker", "engineering_reviewer")
_ROUTE_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.:/+@-]{0,255}\Z")
_EFFORT = re.compile(r"[A-Za-z][A-Za-z0-9_-]{0,31}\Z")


def _route_string(value: object) -> str:
    if (type(value) is not str or not _ROUTE_ID.fullmatch(value)
            or "://" in value or ".." in value):
        raise ControlError("invalid_snapshot")
    return value


def project_routes(config: dict, *, slots: tuple[str, ...] = ENGINEERING_SLOTS) -> list[dict]:
    """Only configured slots are returned; configuration is not execution evidence.

    The caller supplies registered slot names, intersected with the engineering
    surface. This function does not build or refresh a model catalogue.
    """
    if type(config) is not dict:
        raise ControlError("invalid_snapshot")
    auxiliary = config.get("auxiliary", {})
    if type(auxiliary) is not dict:
        raise ControlError("invalid_snapshot")
    result = []
    for slot in ENGINEERING_SLOTS:
        if slot not in slots or slot not in auxiliary:
            continue
        raw = auxiliary[slot]
        if type(raw) is not dict:
            raise ControlError("invalid_snapshot")
        provider = _route_string(raw.get("provider", "auto"))
        model_raw = raw.get("model", "")
        model = "" if model_raw == "" else _route_string(model_raw)
        effort = raw.get("reasoning_effort")
        if "reasoning" in raw:
            reasoning = raw["reasoning"]
            if type(reasoning) is not dict:
                raise ControlError("invalid_snapshot")
            enabled = reasoning.get("enabled", True)
            if type(enabled) is not bool:
                raise ControlError("invalid_snapshot")
            effort = reasoning.get("effort") if enabled else None
        if effort is not None and (type(effort) is not str or not _EFFORT.fullmatch(effort)):
            raise ControlError("invalid_snapshot")
        result.append({"slot": slot, "provider": provider, "model": model,
                       "configured_effort": effort})
    return result
