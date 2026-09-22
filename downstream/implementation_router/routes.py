"""Operator-owned stage routes. Never accept authentication material here."""
from __future__ import annotations

from dataclasses import asdict, dataclass
import hashlib
import json
import re
from typing import Mapping

ROLES = ("planner", "worker", "reviewer")
_PROVIDER = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,63}\Z")
_MODEL = re.compile(r"[^\s\x00-\x1f\x7f]{1,256}\Z")
_EFFORT = re.compile(r"[A-Za-z0-9][A-Za-z0-9_-]{0,63}\Z")


@dataclass(frozen=True)
class ModelRoute:
    provider: str
    model: str
    reasoning_effort: str | None = None

    def __post_init__(self) -> None:
        if (not isinstance(self.provider, str) or not _PROVIDER.fullmatch(self.provider)
                or not isinstance(self.model, str) or not _MODEL.fullmatch(self.model)
                or "://" in self.model or "@" in self.model or "?" in self.model):
            raise ValueError("invalid_route_identifier")
        if self.reasoning_effort is not None and (
            not isinstance(self.reasoning_effort, str)
            or not _EFFORT.fullmatch(self.reasoning_effort)
        ):
            raise ValueError("invalid_reasoning_setting")


@dataclass(frozen=True)
class RoutingTable:
    enabled: bool = False
    entries: tuple[tuple[str, ModelRoute], ...] = ()

    def __post_init__(self) -> None:
        if type(self.enabled) is not bool or type(self.entries) is not tuple:
            raise ValueError("invalid_routing_configuration")
        if not self.enabled:
            if self.entries:
                raise ValueError("disabled_routes_must_be_empty")
            return
        if (len(self.entries) != len(ROLES)
                or any(type(row) is not tuple or len(row) != 2 for row in self.entries)
                or tuple(row[0] for row in self.entries) != ROLES
                or any(type(row[1]) is not ModelRoute for row in self.entries)):
            raise ValueError("all_stage_roles_must_be_configured")

    @classmethod
    def from_config(cls, value: Mapping | None) -> RoutingTable:
        if value is None:
            return cls()
        if type(value) is not dict or set(value) - {"enabled", "roles"}:
            raise ValueError("invalid_routing_configuration")
        enabled = value.get("enabled", False)
        if type(enabled) is not bool:
            raise ValueError("enabled_must_be_boolean")
        roles = value.get("roles")
        if not enabled and roles is None:
            return cls()
        if type(roles) is not dict or set(roles) != set(ROLES):
            raise ValueError("all_stage_roles_must_be_configured")
        rows = []
        for role in ROLES:
            raw = roles[role]
            if (type(raw) is not dict or set(raw) - {"provider", "model", "reasoning_effort"}
                    or not {"provider", "model"}.issubset(raw)):
                raise ValueError("route_fields_not_permitted")
            rows.append((role, ModelRoute(**raw)))
        return cls(True, tuple(rows)) if enabled else cls()

    def for_role(self, role: str) -> ModelRoute:
        if not self.enabled:
            raise ValueError("routing_disabled")
        for name, route in self.entries:
            if name == role:
                return route
        raise ValueError("unknown_stage_role")

    def fingerprint(self) -> str:
        payload = {role: asdict(route) for role, route in self.entries}
        encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
        return hashlib.sha256(encoded.encode("ascii")).hexdigest()
