"""Official advanced-delegation adapter (model_map + profile_routes).

Selected via ``delegation.backend: model_map`` or ``profile_routes``. Settings
live under ``delegation.backends.<backend>``. Unknown options / unauthorized
profiles fail closed per task.
"""

from __future__ import annotations

from typing import Any, Mapping

from agent.delegation_provider import DelegationProvider, DelegationRouteError


def _options(settings: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    raw = settings.get("options")
    if not isinstance(raw, list):
        return []
    return [row for row in raw if isinstance(row, Mapping) and str(row.get("name") or "").strip()]


def _profiles(settings: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    raw = settings.get("profiles")
    if not isinstance(raw, list):
        return []
    return [row for row in raw if isinstance(row, Mapping) and str(row.get("name") or "").strip()]


class ModelMapDelegationProvider(DelegationProvider):
    """Named model options selected per task via ``option``."""

    @property
    def name(self) -> str:
        return "model_map"

    @property
    def display_name(self) -> str:
        return "Model map"

    @property
    def summary(self) -> str:
        return "Pick a titled model option per task (delegation.backends.model_map)."

    def task_parameters(self, config: Mapping[str, Any]) -> dict[str, dict[str, Any]]:
        names = [str(row["name"]).strip() for row in _options(self.settings(config))]
        if not names:
            return {}
        return {
            "option": {
                "type": "string",
                "enum": names,
                "description": "Named model option from delegation.backends.model_map.options.",
            }
        }

    def description(self, config: Mapping[str, Any]) -> str:
        names = [str(row["name"]).strip() for row in _options(self.settings(config))]
        if not names:
            return ""
        return f" Per-task option selects among: {', '.join(names)}."

    def route_task(self, task: Mapping[str, Any], config: Mapping[str, Any]) -> dict[str, Any]:
        settings = self.settings(config)
        options = _options(settings)
        by_name = {str(row["name"]).strip(): row for row in options}
        chosen = task.get("option")
        if chosen is None or (isinstance(chosen, str) and not chosen.strip()):
            default = settings.get("default")
            if isinstance(default, str) and default.strip() and default.strip() in by_name:
                chosen = default.strip()
            else:
                # Empty option → inherit the core delegation section (parent route).
                return {k: v for k, v in config.items() if k in {
                    "model", "provider", "base_url", "api_key", "api_mode",
                    "request_overrides", "reasoning_effort", "fallback_providers",
                }}
        if not isinstance(chosen, str) or chosen.strip() not in by_name:
            raise DelegationRouteError(
                f"Unknown model_map option {chosen!r}. Allowed: {sorted(by_name)}."
            )
        row = by_name[chosen.strip()]
        route = {
            "label": str(row.get("description") or chosen).strip() or chosen.strip(),
        }
        for key in (
            "model",
            "provider",
            "base_url",
            "api_key",
            "api_mode",
            "request_overrides",
            "reasoning_effort",
            "service_tier",
            "fallback_providers",
        ):
            if key in row and row[key] not in (None, ""):
                route[key] = row[key]
        return route


class ProfileRoutesDelegationProvider(DelegationProvider):
    """Hermes profile per task via ``profile``; allowlist only, no default-env fallback."""

    @property
    def name(self) -> str:
        return "profile_routes"

    @property
    def display_name(self) -> str:
        return "Profile routes"

    @property
    def summary(self) -> str:
        return "Run a child as an allowlisted Hermes profile (delegation.backends.profile_routes)."

    def task_parameters(self, config: Mapping[str, Any]) -> dict[str, dict[str, Any]]:
        names = [str(row["name"]).strip() for row in _profiles(self.settings(config))]
        if not names:
            return {}
        return {
            "profile": {
                "type": "string",
                "enum": names,
                "description": "Allowlisted Hermes profile for this child.",
            }
        }

    def description(self, config: Mapping[str, Any]) -> str:
        names = [str(row["name"]).strip() for row in _profiles(self.settings(config))]
        if not names:
            return ""
        return f" Per-task profile selects among: {', '.join(names)}."

    def route_task(self, task: Mapping[str, Any], config: Mapping[str, Any]) -> dict[str, Any]:
        settings = self.settings(config)
        profiles = _profiles(settings)
        allowed = {str(row["name"]).strip() for row in profiles}
        chosen = task.get("profile")
        if chosen is None or (isinstance(chosen, str) and not chosen.strip()):
            default = settings.get("default")
            if isinstance(default, str) and default.strip() and default.strip() in allowed:
                chosen = default.strip()
            else:
                return {k: v for k, v in config.items() if k in {
                    "model", "provider", "base_url", "api_key", "api_mode",
                    "request_overrides", "reasoning_effort", "fallback_providers",
                }}
        if not isinstance(chosen, str) or chosen.strip() not in allowed:
            raise DelegationRouteError(
                f"Profile '{chosen}' is not in the profile_routes allowlist "
                f"{sorted(allowed)}. Unauthorized profiles are refused; "
                f"Hermes never falls back to the default profile environment."
            )
        row = next(r for r in profiles if str(r["name"]).strip() == chosen.strip())
        return {
            "profile": chosen.strip(),
            "label": str(row.get("description") or chosen).strip() or chosen.strip(),
        }


def register(ctx) -> None:
    ctx.register_delegation_provider(ModelMapDelegationProvider())
    ctx.register_delegation_provider(ProfileRoutesDelegationProvider())
