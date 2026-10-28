"""Per-task child routes from the active delegation provider (``delegation.backend``).

Fail-closed: an unusable backend, undeclared parameter, unknown option, or
unauthorized profile refuses that task alone; siblings still run. Secrets never
appear in route metadata returned to callers.
"""

from __future__ import annotations

import logging
from contextlib import contextmanager, nullcontext
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterator, Mapping, Optional

from agent.delegation_provider import (
    RESERVED_TASK_PARAMETERS,
    ROUTE_KEYS,
    DelegationProvider,
    DelegationRouteError,
)
from agent.delegation_registry import _registry, configured_backend, get_active_provider

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class TaskRoute:
    """Resolved non-secret route for one delegated task."""

    backend: str
    model: Optional[str] = None
    provider: Optional[str] = None
    base_url: Optional[str] = None
    api_key: Optional[str] = None
    api_mode: Optional[str] = None
    request_overrides: Optional[dict[str, Any]] = None
    reasoning_effort: Optional[str] = None
    fallback_providers: Any = None
    profile: Optional[str] = None
    label: Optional[str] = None
    service_tier: Optional[str] = None
    refused: bool = False
    error: Optional[str] = None
    profile_home: Optional[Path] = None
    max_output_tokens: Optional[int] = None
    command: Optional[str] = None
    args: Optional[list[str]] = None

    def credential_bundle(self) -> dict[str, Any]:
        """Shape consumed by ``_build_child_agent`` override_* kwargs."""
        return {
            "model": self.model,
            "provider": self.provider,
            "base_url": self.base_url,
            "api_key": self.api_key,
            "api_mode": self.api_mode,
            "request_overrides": self.request_overrides,
            "max_output_tokens": self.max_output_tokens,
            "command": self.command,
            "args": self.args,
        }

    def public_metadata(self, *, fallback_activated: bool = False) -> dict[str, Any]:
        """Safe result metadata (no secrets)."""
        meta: dict[str, Any] = {"backend": self.backend}
        if self.label:
            meta["label"] = self.label
        if self.refused:
            meta["refused"] = True
            return meta
        if self.provider:
            meta["provider"] = self.provider
        if self.model:
            meta["model"] = self.model
        if self.reasoning_effort:
            meta["reasoning_effort"] = self.reasoning_effort
        if self.service_tier:
            meta["service_tier"] = self.service_tier
        if self.profile:
            meta["profile"] = self.profile
        if fallback_activated:
            meta["fallback_activated"] = True
        return meta


def _active_provider(config: Mapping[str, Any]) -> DelegationProvider:
    return get_active_provider(config)


def _declared_parameters(
    provider: DelegationProvider, config: Mapping[str, Any]
) -> dict[str, dict[str, Any]]:
    raw = provider.task_parameters(config) or {}
    cleaned: dict[str, dict[str, Any]] = {}
    for name, schema in raw.items():
        if not isinstance(name, str) or not name or name in RESERVED_TASK_PARAMETERS:
            raise DelegationRouteError(
                f"Delegation backend '{provider.name}' cannot declare reserved "
                f"task parameter '{name}'."
            )
        if not isinstance(schema, dict):
            raise DelegationRouteError(
                f"Delegation backend '{provider.name}' parameter '{name}' must be a schema object."
            )
        cleaned[name] = schema
    return cleaned


def schema_extension(config: Mapping[str, Any]) -> tuple[dict[str, dict[str, Any]], str]:
    """Extra task properties + description addendum for the active backend."""
    try:
        provider = _active_provider(config)
    except DelegationRouteError:
        return {}, ""
    params = _declared_parameters(provider, config)
    addendum = (provider.description(config) or "").strip()
    return params, addendum


def _param_error(index: int, name: str, value: Any, schema: Mapping[str, Any]) -> Optional[str]:
    enum = schema.get("enum")
    if isinstance(enum, list) and value not in enum:
        return (
            f"Task {index}: '{name}' must be one of {enum!r} "
            f"(got {value!r})."
        )
    return None


def _clean_route(provider_name: str, route: Any) -> dict[str, Any]:
    if not isinstance(route, Mapping):
        raise DelegationRouteError(
            f"Delegation backend '{provider_name}' returned a non-object route."
        )
    return {k: v for k, v in route.items() if k in ROUTE_KEYS}


def _with_inherited_fallback(route: dict[str, Any], config: Mapping[str, Any]) -> dict[str, Any]:
    if "fallback_providers" in route:
        return route
    if isinstance(config, Mapping) and "fallback_providers" in config:
        return {**route, "fallback_providers": config.get("fallback_providers")}
    return route


@contextmanager
def delegated_profile_scope(home: Any) -> Iterator[None]:
    """Run with HERMES_HOME + secret scope bound to ``home`` (fail closed on miss)."""
    target = Path(home)
    from hermes_constants import reset_hermes_home_override, set_hermes_home_override

    token = set_hermes_home_override(target)
    try:
        try:
            from agent.secret_scope import (
                build_profile_secret_scope,
                reset_secret_scope,
                set_secret_scope,
            )

            scope = build_profile_secret_scope(target)
            scope_token = set_secret_scope(scope)
        except Exception:
            scope_token = None
            reset_secret_scope = None  # type: ignore[assignment]
        try:
            yield
        finally:
            if scope_token is not None and callable(reset_secret_scope):
                reset_secret_scope(scope_token)
    finally:
        reset_hermes_home_override(token)


def child_profile_scope(child: Any) -> Any:
    # MagicMock (and similar auto-attr stubs) invent truthy values for any
    # getattr name — only honor a real filesystem home, never a mock object.
    home = getattr(child, "_delegation_profile_home", None)
    if not isinstance(home, (str, Path)):
        return nullcontext()
    return delegated_profile_scope(home)


def _profile_home(name: Any) -> Path:
    from hermes_cli.profiles import get_profile_dir, profile_exists

    if not isinstance(name, str) or not name.strip():
        raise DelegationRouteError("Profile route requires a non-empty profile name.")
    profile = name.strip()
    if not profile_exists(profile):
        raise DelegationRouteError(
            f"Profile '{profile}' is not an allowed Hermes profile on this host "
            f"(missing under profiles/). Cross-profile delegation never falls back "
            f"to the default profile environment."
        )
    return get_profile_dir(profile)


def _profile_route(home: Path, backend: str, label: Optional[str]) -> TaskRoute:
    from hermes_cli.config import load_config_readonly
    from hermes_cli.runtime_provider import resolve_runtime_provider

    with delegated_profile_scope(home):
        cfg = load_config_readonly()
        model_cfg = cfg.get("model") if isinstance(cfg, dict) else None
        target_model = ""
        if isinstance(model_cfg, dict):
            target_model = str(model_cfg.get("default") or "").strip()
        requested = ""
        if isinstance(model_cfg, dict):
            requested = str(model_cfg.get("provider") or "").strip()
        try:
            resolved = resolve_runtime_provider(
                requested=requested or None,
                target_model=target_model or None,
            )
        except Exception as exc:
            raise DelegationRouteError(
                f"Profile at {home} has no usable model provider: {exc}"
            ) from exc
    model = (resolved or {}).get("model") or target_model or None
    provider = (resolved or {}).get("provider")
    return TaskRoute(
        backend=backend,
        model=str(model).strip() if model else None,
        provider=str(provider).strip().lower() if provider else None,
        base_url=(resolved or {}).get("base_url"),
        api_key=(resolved or {}).get("api_key"),
        api_mode=(resolved or {}).get("api_mode"),
        label=label,
        profile=home.name,
        profile_home=home,
    )


def _resolve_route(route: dict[str, Any], parent_agent: Any, backend: str) -> TaskRoute:
    from tools.delegate_tool import _resolve_delegation_credentials

    label = route.get("label") if isinstance(route.get("label"), str) else None
    profile = route.get("profile")
    if profile is not None:
        home = _profile_home(profile)
        return _profile_route(home, backend, label)

    routing_cfg = {k: v for k, v in route.items() if k != "label"}
    try:
        creds = _resolve_delegation_credentials(routing_cfg, parent_agent)
    except ValueError as exc:
        raise DelegationRouteError(str(exc)) from exc
    return TaskRoute(
        backend=backend,
        model=creds.get("model"),
        provider=creds.get("provider"),
        base_url=creds.get("base_url"),
        api_key=creds.get("api_key"),
        api_mode=creds.get("api_mode"),
        request_overrides=creds.get("request_overrides"),
        reasoning_effort=route.get("reasoning_effort")
        if isinstance(route.get("reasoning_effort"), str)
        else None,
        fallback_providers=route.get("fallback_providers"),
        label=label,
        service_tier=route.get("service_tier")
        if isinstance(route.get("service_tier"), str)
        else None,
        max_output_tokens=creds.get("max_output_tokens"),
        command=creds.get("command"),
        args=creds.get("args"),
    )


def _undeclared_error(
    provider: DelegationProvider,
    index: int,
    names: list[str],
    config: Mapping[str, Any],
) -> str:
    active = provider.name
    owners: set[str] = set()
    for other in _registry.list_providers():
        try:
            declared = set((other.task_parameters(config) or {}).keys())
        except Exception:
            declared = set()
        if set(names) & declared:
            owners.add(other.name)
    names_repr = "{" + ", ".join(repr(n) for n in sorted(names)) + "}"
    if owners:
        owners_repr = "{" + ", ".join(repr(n) for n in sorted(owners)) + "}"
        return (
            f"Task {index}: this session's delegation backend is '{active}', which does not "
            f"take {names_repr} (declared by {owners_repr}), so this task was not started. "
            f"Start a new session with /new after switching backends so delegate_task choices "
            f"match '{active}', or resend without {names_repr}."
        )
    return (
        f"Task {index}: this session's delegation backend is '{active}', which does not take "
        f"{names_repr}, and no installed delegation backend does, so this task was not started. "
        f"Resend it without {names_repr}."
    )


def _route_one(
    provider: DelegationProvider,
    declared: dict[str, dict[str, Any]],
    index: int,
    task: Mapping[str, Any],
    config: Mapping[str, Any],
    parent_agent: Any,
    cache: dict[str, TaskRoute],
) -> TaskRoute:
    extras = {
        k: v
        for k, v in task.items()
        if k not in RESERVED_TASK_PARAMETERS and k not in {"goal", "context", "role"}
    }
    undeclared = sorted(k for k in extras if k not in declared)
    if undeclared:
        raise DelegationRouteError(_undeclared_error(provider, index, undeclared, config))
    for name, schema in declared.items():
        if name not in extras:
            continue
        err = _param_error(index, name, extras[name], schema)
        if err:
            raise DelegationRouteError(err)

    payload = {
        "goal": task.get("goal"),
        "context": task.get("context"),
        "index": index,
        **{k: extras[k] for k in declared if k in extras},
    }
    try:
        raw = provider.route_task(payload, config)
    except DelegationRouteError:
        raise
    except Exception as exc:
        raise DelegationRouteError(
            f"Task {index}: delegation backend '{provider.name}' failed: {exc}"
        ) from exc
    route = _with_inherited_fallback(_clean_route(provider.name, raw), config)

    cache_key = ""
    if isinstance(route.get("profile"), str) and route["profile"].strip():
        cache_key = f"profile:{route['profile'].strip()}"
    elif route.get("provider") or route.get("model") or route.get("base_url"):
        cache_key = (
            f"model:{route.get('provider')}|{route.get('model')}|"
            f"{route.get('base_url')}|{route.get('api_mode')}"
        )
    if cache_key and cache_key in cache:
        cached = cache[cache_key]
        return TaskRoute(
            backend=provider.name,
            model=cached.model,
            provider=cached.provider,
            base_url=cached.base_url,
            api_key=cached.api_key,
            api_mode=cached.api_mode,
            request_overrides=cached.request_overrides,
            reasoning_effort=route.get("reasoning_effort")
            if isinstance(route.get("reasoning_effort"), str)
            else cached.reasoning_effort,
            fallback_providers=route.get("fallback_providers", cached.fallback_providers),
            profile=cached.profile,
            label=route.get("label") if isinstance(route.get("label"), str) else cached.label,
            service_tier=route.get("service_tier")
            if isinstance(route.get("service_tier"), str)
            else cached.service_tier,
            profile_home=cached.profile_home,
            max_output_tokens=cached.max_output_tokens,
            command=cached.command,
            args=cached.args,
        )

    resolved = _resolve_route(route, parent_agent, provider.name)
    if cache_key:
        cache[cache_key] = resolved
    return resolved


def resolve_task_routes(
    task_list: list[dict[str, Any]],
    config: Mapping[str, Any],
    parent_agent: Any,
) -> list[TaskRoute]:
    """One :class:`TaskRoute` per task. Refused tasks carry ``refused=True`` + ``error``."""
    from agent.delegation_backends import pinned_backend

    pinned = pinned_backend(parent_agent)
    effective_config = dict(config) if isinstance(config, Mapping) else {}
    if pinned:
        effective_config["backend"] = pinned

    try:
        provider = _active_provider(effective_config)
    except DelegationRouteError as exc:
        # Whole-call refuse when the backend itself cannot run.
        raise

    try:
        declared = _declared_parameters(provider, effective_config)
    except DelegationRouteError as exc:
        raise

    cache: dict[str, TaskRoute] = {}
    routes: list[TaskRoute] = []
    for index, task in enumerate(task_list):
        try:
            routes.append(
                _route_one(
                    provider,
                    declared,
                    index,
                    task if isinstance(task, Mapping) else {},
                    effective_config,
                    parent_agent,
                    cache,
                )
            )
        except DelegationRouteError as exc:
            routes.append(
                TaskRoute(
                    backend=provider.name,
                    refused=True,
                    error=str(exc),
                    label=task.get("label") if isinstance(task, Mapping) else None,
                )
            )
    return routes


def route_for_config(routing_cfg: dict[str, Any], parent_agent: Any) -> TaskRoute:
    """Single route for an internal credentials_cfg owner (e.g. /review)."""
    from tools.delegate_tool import _resolve_delegation_credentials

    creds = _resolve_delegation_credentials(routing_cfg, parent_agent)
    return TaskRoute(
        backend=configured_backend(routing_cfg),
        model=creds.get("model"),
        provider=creds.get("provider"),
        base_url=creds.get("base_url"),
        api_key=creds.get("api_key"),
        api_mode=creds.get("api_mode"),
        request_overrides=creds.get("request_overrides"),
        fallback_providers=routing_cfg.get("fallback_providers")
        if isinstance(routing_cfg, Mapping)
        else None,
        max_output_tokens=creds.get("max_output_tokens"),
        command=creds.get("command"),
        args=creds.get("args"),
    )
