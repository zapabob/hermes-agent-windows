"""Typed boundary for inference owned by a Hermes parent agent.

Logical delegated conversations may carry this capability without receiving a
provider client or credential resolver. Concrete dispatch lives in
``ParentInferencePort``; these contracts are importable by the agent loop and
focused tests without importing provider SDKs.
"""

from __future__ import annotations

import contextvars
import hashlib
import json
import secrets
import threading
import weakref
from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import Any, Iterator, Mapping, Protocol, runtime_checkable


@dataclass(frozen=True)
class InferenceRouteBinding:
    """Non-secret route identity pinned by the host when delegation is admitted."""

    profile_id: str
    provider: str
    model: str
    api_mode: str
    route_fingerprint: str
    max_calls: int
    max_tokens: int | None
    allowed_tool_names: tuple[str, ...]
    reasoning_fingerprint: str


@dataclass(frozen=True)
class InferenceTurn:
    """A regular Hermes request plus the logical child that owns cancellation."""

    api_kwargs: Mapping[str, Any]
    requester: Any = field(repr=False, compare=False)
    original_api_kwargs: Mapping[str, Any] | None = field(
        default=None, repr=False, compare=False
    )


@dataclass(frozen=True)
class ToolCallIdentity:
    """Safe identity and completeness summary for one executable call."""

    call_id: str
    name: str
    complete: bool


@dataclass(frozen=True)
class NormalizedTurn:
    """A provider response returned to Hermes' existing response normalizers.

    T05 deliberately keeps the established adapter/transport conversion in
    the normal agent loop. This wrapper carries no request credentials or
    provider-private reasoning state; its metadata is a safe summary used to
    refuse ambiguous turns before they can reach tool dispatch.
    """

    response: Any = field(repr=False, compare=False)
    terminal_status: str = "unknown"
    final_text: str | None = None
    commentary_count: int = 0
    tool_calls: tuple[ToolCallIdentity, ...] = ()
    configured_model: str | None = None
    requested_model: str | None = None
    reported_model: str | None = None
    configured_effort: str | None = None
    wire_effort: str | None = None
    reported_effort: str | None = None
    failure_code: str | None = None


@runtime_checkable
class InferencePort(Protocol):
    """Parent-owned model request capability exposed to a logical child."""

    def complete(
        self,
        turn: InferenceTurn,
        *,
        route_binding: InferenceRouteBinding,
        cancel_generation: int,
    ) -> NormalizedTurn:
        """Execute one host-bound request or fail closed."""


class InferencePortError(RuntimeError):
    """A controlled inference request could not honor its host binding."""

    _SAFE_CODES = frozenset(
        {
            "INFERENCE_PORT_ERROR",
            "INVALID_RESPONSE",
            "MISSING_TERMINAL_STATUS",
            "UNKNOWN_TERMINAL_STATUS",
            "UNKNOWN_MESSAGE_PHASE",
            "PROVIDER_INCOMPLETE",
            "PROVIDER_FAILED",
            "PROVIDER_REFUSAL_WITH_TOOL_CALL",
            "TOOL_CALL_STATUS_MISMATCH",
            "MISSING_TOOL_CALLS",
            "INCOMPLETE_TOOL_CALL",
            "DUPLICATE_TOOL_CALL_ID",
            "INVALID_TOOL_CALL",
            "UNREQUESTED_TOOL",
            "INCOMPLETE_TOOL_ARGUMENTS",
            "EMPTY_TURN",
        }
    )

    def __init__(
        self,
        message: str,
        *,
        failure_code: str = "INFERENCE_PORT_ERROR",
    ) -> None:
        super().__init__(message)
        self.failure_code = (
            failure_code
            if isinstance(failure_code, str) and failure_code in self._SAFE_CODES
            else "INFERENCE_PORT_ERROR"
        )


_PARENT_OWNER_LOCK = threading.RLock()
_PARENT_OWNER_REFS: dict[str, Any] = {}
_ACTIVE_REQUEST_ABORTS: dict[str, Any] = {}


def _register_parent_owner(parent: Any) -> str:
    """Keep the parent outside every child-visible port object."""
    token = secrets.token_urlsafe(32)

    def discard(ref: Any, *, key: str = token) -> None:
        with _PARENT_OWNER_LOCK:
            if _PARENT_OWNER_REFS.get(key) is ref:
                _PARENT_OWNER_REFS.pop(key, None)

    try:
        parent_ref = weakref.ref(parent, discard)
    except TypeError as exc:
        raise InferencePortError(
            "Parent inference owner cannot be safely retained."
        ) from exc
    with _PARENT_OWNER_LOCK:
        _PARENT_OWNER_REFS[token] = parent_ref
    return token


def _resolve_parent_owner(token: str) -> Any:
    with _PARENT_OWNER_LOCK:
        parent_ref = _PARENT_OWNER_REFS.get(token)
    parent = parent_ref() if parent_ref is not None else None
    if parent is None:
        raise InferencePortError("Parent inference owner has expired.")
    return parent


def _set_request_abort(request_id: str, abort: Any) -> None:
    with _PARENT_OWNER_LOCK:
        if callable(abort):
            _ACTIVE_REQUEST_ABORTS[request_id] = abort
        else:
            _ACTIVE_REQUEST_ABORTS.pop(request_id, None)


def _request_abort(request_id: str, reason: str) -> None:
    with _PARENT_OWNER_LOCK:
        abort = _ACTIVE_REQUEST_ABORTS.get(request_id)
    if callable(abort):
        abort(reason)


_ACTIVE_INFERENCE_PORT: contextvars.ContextVar[InferencePort | None] = (
    contextvars.ContextVar("hermes_active_inference_port", default=None)
)


@contextmanager
def bind_inference_port(port: InferencePort | None) -> Iterator[None]:
    """Mark the current execution as using a controlled primary inference port."""
    token = _ACTIVE_INFERENCE_PORT.set(port)
    try:
        yield
    finally:
        _ACTIVE_INFERENCE_PORT.reset(token)


def active_inference_port() -> InferencePort | None:
    """Return the controlled port active on this execution context, if any."""
    return _ACTIVE_INFERENCE_PORT.get()


def _fingerprint(value: Any) -> str:
    try:
        encoded = json.dumps(
            value,
            ensure_ascii=True,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
            default=str,
        ).encode("utf-8")
    except (TypeError, ValueError):
        encoded = repr(value).encode("utf-8", errors="replace")
    return hashlib.sha256(encoded).hexdigest()


def _route_fingerprint(parent: Any) -> str:
    return _fingerprint(
        (
            str(getattr(parent, "provider", "") or "").strip().lower(),
            str(getattr(parent, "model", "") or "").strip(),
            str(getattr(parent, "api_mode", "") or "").strip(),
            str(getattr(parent, "base_url", "") or "").strip(),
        )
    )


_PARENT_TRANSPORT_METHODS = frozenset(
    {
        "_create_request_openai_client",
        "_abort_request_openai_client",
        "_close_request_openai_client",
        "_create_request_anthropic_client",
        "_abort_request_anthropic_client",
        "_close_request_anthropic_client",
        "_run_codex_stream",
        "_anthropic_messages_create",
    }
)


class _ParentRequestAgent:
    """Per-request view with parent-only transport methods resolved by token."""

    __slots__ = (
        "__dict__",
        "_owner_token",
        "_requester",
        "_cancel_requested",
        "_abort_lock",

        "_request_id",
    )

    def __init__(self, owner_token: str, requester: Any, request_id: str) -> None:
        object.__setattr__(self, "_owner_token", owner_token)
        object.__setattr__(self, "_requester", requester)
        object.__setattr__(self, "_cancel_requested", threading.Event())
        object.__setattr__(self, "_abort_lock", threading.Lock())

        object.__setattr__(self, "_request_id", request_id)

    def request_abort(self, reason: str) -> None:
        """Abort only the request whose requester installed this callback."""
        event = object.__getattribute__(self, "_cancel_requested")
        event.set()
        _request_abort(object.__getattribute__(self, "_request_id"), reason)

    def __getattr__(self, name: str) -> Any:
        if name in {
            "api_key",
            "_anthropic_api_key",
            "_client_kwargs",
            "client",
            "_anthropic_client",
            "_credential_pool",
            "credential_pool",
        }:
            raise AttributeError(name)
        parent = _resolve_parent_owner(
            object.__getattribute__(self, "_owner_token")
        )
        requester = object.__getattribute__(self, "_requester")
        if name == "_interrupt_requested":
            return bool(getattr(requester, "_interrupt_requested", False))
        if name == "_active_request_abort":
            with object.__getattribute__(self, "_abort_lock"):
                abort = _ACTIVE_REQUEST_ABORTS.get(
                    object.__getattribute__(self, "_request_id")
                )
            return self.request_abort if callable(abort) else None
        if name in _PARENT_TRANSPORT_METHODS:
            return getattr(parent, name)
        if name in {"platform", "session_id", "log_prefix", "quiet_mode"}:
            return getattr(requester, name, None)
        if name == "_touch_activity":
            return getattr(requester, name)
        try:
            return getattr(requester, name)
        except AttributeError:
            raise AttributeError(name) from None

    def __setattr__(self, name: str, value: Any) -> None:
        if name != "_active_request_abort":
            if name in {
                "api_key",
                "_anthropic_api_key",
                "_client_kwargs",
                "client",
                "_anthropic_client",
                "_credential_pool",
                "credential_pool",
            }:
                raise AttributeError(name)
            requester = object.__getattribute__(self, "_requester")
            if hasattr(requester, name):
                setattr(requester, name, value)
            else:
                object.__setattr__(self, name, value)
            return

        lock = object.__getattribute__(self, "_abort_lock")
        event = object.__getattribute__(self, "_cancel_requested")
        with lock:
            _set_request_abort(
                object.__getattribute__(self, "_request_id"), value
            )
            cancel_now = callable(value) and (
                event.is_set()
                or bool(
                    getattr(
                        object.__getattribute__(self, "_requester"),
                        "_interrupt_requested",
                        False,
                    )
                )
            )
        if cancel_now:
            value("interrupt_abort")


class ParentInferencePort:
    """A child-scoped capability that dispatches only through its parent.

    The child receives this object instead of the parent's SDK client, provider
    key, or credential pool. It is an in-process authority boundary; it is not
    an OS isolation boundary.
    """

    def __init__(
        self,
        parent: Any | None = None,
        *,
        _owner_token: str | None = None,
        _profile_home: str | None = None,
        _base_binding: tuple[str, str, str, str, str] | None = None,
    ) -> None:
        if _owner_token is None:
            if parent is None:
                raise InferencePortError("Parent inference owner is unavailable.")
            owner_token = _register_parent_owner(parent)
            from hermes_constants import get_hermes_home, hermes_home_key

            home = get_hermes_home()
            profile_id = hashlib.sha256(
                hermes_home_key(home).encode("utf-8")
            ).hexdigest()
            owner = parent
            provider = str(getattr(owner, "provider", "") or "").strip().lower()
            model = str(getattr(owner, "model", "") or "").strip()
            api_mode = str(getattr(owner, "api_mode", "") or "").strip()
            base_binding = (
                profile_id,
                provider,
                model,
                api_mode,
                _route_fingerprint(owner),
            )
        else:
            owner = _resolve_parent_owner(_owner_token)
            home = _profile_home
            if not isinstance(home, str) or not home:
                raise InferencePortError("Parent profile binding is unavailable.")
            if not isinstance(_base_binding, tuple) or len(_base_binding) != 5:
                raise InferencePortError("Parent route binding is unavailable.")
            base_binding = _base_binding
            profile_id, provider, model, api_mode, _route_digest = base_binding
            if (
                str(getattr(owner, "provider", "") or "").strip().lower()
                != provider
                or str(getattr(owner, "model", "") or "").strip() != model
                or str(getattr(owner, "api_mode", "") or "").strip() != api_mode
                or _route_fingerprint(owner) != _route_digest
            ):
                raise InferencePortError("Parent inference route changed after admission.")
        if (
            not provider
            or not model
            or api_mode
            not in {
                "chat_completions",
                "codex_responses",
                "anthropic_messages",
            }
            or provider in {"moa", "copilot-acp"}
        ):
            raise InferencePortError(
                "This parent provider route is not supported for controlled delegation."
            )

        self._owner_token = owner_token
        self._profile_home = str(home)
        self._profile_id = profile_id
        self._base_binding = base_binding
        self._binding: InferenceRouteBinding | None = None
        self._calls_used = 0
        self._calls_lock = threading.Lock()
        self._request_lock = threading.Lock()
        self._requester_ref: Any | None = None

    @classmethod
    def for_parent(cls, parent: Any) -> "ParentInferencePort":
        """Create the root capability while the admitted profile is active."""
        return cls(parent)

    def fork_for_child(self) -> "ParentInferencePort":
        """Create a fresh child budget on the same parent-owned route."""
        _resolve_parent_owner(self._owner_token)
        return type(self)(
            _owner_token=self._owner_token,
            _profile_home=self._profile_home,
            _base_binding=self._base_binding,
        )

    def bind_child(
        self,
        child: Any,
        *,
        max_calls: int,
        max_tokens: int | None,
        allowed_tool_names: Any,
        reasoning_config: Any,
    ) -> None:
        """Bind this capability once to a constructed child's live policy."""
        if self._binding is not None:
            raise InferencePortError("Inference port was already bound to a child.")
        if type(max_calls) is not int or max_calls < 1:
            raise InferencePortError("Child inference call budget is invalid.")
        if max_tokens is not None and (
            type(max_tokens) is not int or max_tokens < 1
        ):
            raise InferencePortError("Child inference token budget is invalid.")
        if not isinstance(allowed_tool_names, (set, frozenset, tuple, list)):
            raise InferencePortError("Child tool permission snapshot is invalid.")
        try:
            self._requester_ref = weakref.ref(child)
        except TypeError as exc:
            raise InferencePortError("Child inference owner cannot be safely bound.") from exc
        names = tuple(sorted({
            name for name in allowed_tool_names
            if isinstance(name, str) and name
        }))
        profile_id, provider, model, api_mode, route_digest = self._base_binding
        self._binding = InferenceRouteBinding(
            profile_id=profile_id,
            provider=provider,
            model=model,
            api_mode=api_mode,
            route_fingerprint=route_digest,
            max_calls=max_calls,
            max_tokens=max_tokens,
            allowed_tool_names=names,
            reasoning_fingerprint=_fingerprint(reasoning_config),
        )

    @property
    def route_binding(self) -> InferenceRouteBinding:
        if self._binding is None:
            raise InferencePortError("Inference port has not been bound to a child.")
        return self._binding

    def complete(
        self,
        turn: InferenceTurn,
        *,
        route_binding: InferenceRouteBinding,
        cancel_generation: int,
    ) -> NormalizedTurn:
        binding = self.route_binding
        if route_binding is not binding:
            raise InferencePortError("Inference route binding does not match.")
        if type(cancel_generation) is not int or cancel_generation < 0:
            raise InferencePortError("Inference cancellation generation is invalid.")
        if not isinstance(turn, InferenceTurn) or not isinstance(turn.api_kwargs, Mapping):
            raise InferencePortError("Inference request is malformed.")
        parent = _resolve_parent_owner(self._owner_token)
        requester = turn.requester
        if requester is None:
            raise InferencePortError("Inference requester is unavailable.")
        bound_requester = self._requester_ref() if self._requester_ref is not None else None
        if requester is not bound_requester:
            raise InferencePortError("Inference requester differs from the bound child.")

        from hermes_constants import get_hermes_home, hermes_home_key

        if (
            str(getattr(parent, "provider", "") or "").strip().lower()
            != binding.provider
            or str(getattr(parent, "model", "") or "").strip() != binding.model
            or str(getattr(parent, "api_mode", "") or "").strip() != binding.api_mode
            or _route_fingerprint(parent) != binding.route_fingerprint
        ):
            raise InferencePortError("Parent inference route changed after admission.")
        if (
            str(getattr(requester, "provider", "") or "").strip().lower()
            != binding.provider
            or str(getattr(requester, "model", "") or "").strip() != binding.model
            or str(getattr(requester, "api_mode", "") or "").strip()
            != binding.api_mode
        ):
            raise InferencePortError("Child inference route differs from its binding.")
        if (
            getattr(requester, "_inference_cancel_generation", 0)
            != cancel_generation
            or bool(getattr(requester, "_interrupt_requested", False))
        ):
            raise InterruptedError("Controlled inference request was cancelled.")
        if (
            _fingerprint(getattr(requester, "reasoning_config", None))
            != binding.reasoning_fingerprint
        ):
            raise InferencePortError("Child reasoning configuration changed after admission.")
        current_names = getattr(requester, "valid_tool_names", set())
        if not isinstance(current_names, (set, frozenset, tuple, list)):
            raise InferencePortError("Child tool permission state is invalid.")
        if not set(current_names).issubset(set(binding.allowed_tool_names)):
            raise InferencePortError("Child tool permissions expanded after admission.")

        request = dict(turn.api_kwargs)
        self._validate_request(request, turn.original_api_kwargs, binding)
        if not self._request_lock.acquire(blocking=False):
            raise InferencePortError("Child already has an active inference request.")
        try:
            request_id = secrets.token_urlsafe(24)
            request_agent = _ParentRequestAgent(self._owner_token, requester, request_id)
            from hermes_constants import reset_hermes_home_override, set_hermes_home_override

            previous_abort = getattr(requester, "_active_request_abort", None)
            if callable(previous_abort):
                raise InferencePortError("Child already has an active inference request.")

            with self._calls_lock:
                if self._calls_used >= binding.max_calls:
                    raise InferencePortError("Child inference call budget is exhausted.")
                self._calls_used += 1

            setattr(requester, "_active_request_abort", request_agent.request_abort)

            profile_token = None
            try:
                profile_token = set_hermes_home_override(self._profile_home)
                bound_profile_id = hashlib.sha256(
                    hermes_home_key(get_hermes_home()).encode("utf-8")
                ).hexdigest()
                if bound_profile_id != binding.profile_id:
                    raise InferencePortError("Parent profile binding could not be restored.")
                from agent.chat_completion_helpers import interruptible_api_call

                response = interruptible_api_call(request_agent, request)
                if (
                    getattr(requester, "_inference_cancel_generation", 0)
                    != cancel_generation
                    or bool(getattr(requester, "_interrupt_requested", False))
                ):
                    raise InterruptedError("Controlled inference request was cancelled.")
                return _normalize_parent_turn(
                    response,
                    api_mode=binding.api_mode,
                    request=request,
                    requester=requester,
                )
            finally:
                request_agent._active_request_abort = None
                setattr(requester, "_active_request_abort", previous_abort)
                _set_request_abort(request_id, None)
                if profile_token is not None:
                    reset_hermes_home_override(profile_token)
        finally:
            self._request_lock.release()

    @staticmethod
    def _validate_request(
        request: dict[str, Any],
        original_request: Mapping[str, Any] | None,
        binding: InferenceRouteBinding,
    ) -> None:
        forbidden = {
            "api_key",
            "authorization",
            "auth",
            "base_url",
            "client",
            "client_kwargs",
            "credential_pool",
            "extra_headers",
            "headers",
            "http_client",
            "token",
            "token_provider",
        }
        if any(str(key).strip().lower() in forbidden for key in request):
            raise InferencePortError("Inference request contains a forbidden route field.")
        if request.get("model") != binding.model:
            raise InferencePortError("Inference request model differs from its binding.")
        if original_request is not None:
            for key in (
                "model",
                "max_tokens",
                "max_completion_tokens",
                "max_output_tokens",
                "reasoning",
                "reasoning_effort",
                "thinking",
            ):
                if key in original_request and request.get(key) != original_request.get(key):
                    raise InferencePortError(
                        "Inference middleware changed a bound route option."
                    )
        if binding.max_tokens is not None:
            for key in ("max_tokens", "max_completion_tokens", "max_output_tokens"):
                value = request.get(key)
                if value is not None and (
                    isinstance(value, bool)
                    or not isinstance(value, int)
                    or value > binding.max_tokens
                ):
                    raise InferencePortError("Inference request exceeds its token budget.")

        names = _request_tool_names(request)
        if not names.issubset(set(binding.allowed_tool_names)):
            raise InferencePortError("Inference request contains an unbound tool.")


def _request_tool_names(request: Mapping[str, Any]) -> set[str]:
    tools = request.get("tools")
    if tools is None:
        tools = request.get("functions")
    if tools is None:
        return set()
    if not isinstance(tools, list):
        raise InferencePortError("Inference tool schema is malformed.")
    result: set[str] = set()
    for item in tools:
        if not isinstance(item, Mapping):
            raise InferencePortError("Inference tool schema is malformed.")
        fn = item.get("function")
        name = item.get("name")
        if isinstance(fn, Mapping):
            name = fn.get("name", name)
        if not isinstance(name, str) or not name:
            raise InferencePortError("Inference tool schema is unsupported.")
        result.add(name)
    return result


_MISSING = object()


def _response_field(value: Any, name: str, default: Any = None) -> Any:
    if isinstance(value, Mapping):
        return value.get(name, default)
    try:
        return getattr(value, name, default)
    except Exception:
        return default


def _safe_string(value: Any) -> str | None:
    return value.strip() if isinstance(value, str) and value.strip() else None


def _output_text(value: Any) -> str | None:
    return value if isinstance(value, str) and value.strip() else None


def _request_tool_schemas(request: Mapping[str, Any]) -> dict[str, Mapping[str, Any]]:
    tools = request.get("tools")
    if tools is None:
        tools = request.get("functions")
    if tools is None:
        return {}
    if not isinstance(tools, list):
        raise InferencePortError("Inference tool schema is malformed.")

    schemas: dict[str, Mapping[str, Any]] = {}
    for item in tools:
        if not isinstance(item, Mapping):
            raise InferencePortError("Inference tool schema is malformed.")
        function = item.get("function")
        function = function if isinstance(function, Mapping) else item
        name = function.get("name")
        if not isinstance(name, str) or not name:
            raise InferencePortError("Inference tool schema is unsupported.")
        parameters = function.get("parameters")
        if not isinstance(parameters, Mapping):
            parameters = function.get("input_schema")
        schemas[name] = parameters if isinstance(parameters, Mapping) else {}
    return schemas


def _configured_effort(requester: Any) -> str | None:
    configured = getattr(requester, "reasoning_config", None)
    if _response_field(configured, "enabled") is False:
        return None
    return _safe_string(_response_field(configured, "effort"))


def _wire_effort(request: Mapping[str, Any]) -> str | None:
    candidates = [
        _response_field(request.get("reasoning"), "effort"),
        request.get("reasoning_effort"),
        _response_field(request.get("output_config"), "effort"),
        _response_field(_response_field(request.get("extra_body"), "reasoning"), "effort"),
        _response_field(request.get("extra_body"), "reasoning_effort"),
    ]
    return next((value for candidate in candidates if (value := _safe_string(candidate))), None)


def _reported_effort(response: Any) -> str | None:
    candidates = [
        _response_field(response, "reasoning_effort"),
        _response_field(_response_field(response, "output_config"), "effort"),
    ]
    return next((value for candidate in candidates if (value := _safe_string(candidate))), None)


def _strict_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate JSON property")
        result[key] = value
    return result


def _reject_nonfinite(value: str) -> None:
    raise ValueError("non-finite JSON number")


def _validated_arguments(
    raw_arguments: Any,
    *,
    schema: Mapping[str, Any],
    allow_mapping: bool,
) -> None:
    if allow_mapping and isinstance(raw_arguments, Mapping):
        arguments = raw_arguments
    else:
        if not isinstance(raw_arguments, str):
            raise InferencePortError(
                "Controlled provider tool arguments are incomplete.",
                failure_code="INCOMPLETE_TOOL_ARGUMENTS",
            )
        if not raw_arguments.strip():
            required = schema.get("required", [])
            if isinstance(required, list) and required:
                raise InferencePortError(
                    "Controlled provider tool arguments are incomplete.",
                    failure_code="INCOMPLETE_TOOL_ARGUMENTS",
                )
            raw_arguments = "{}"
        try:
            arguments = json.loads(
                raw_arguments,
                object_pairs_hook=_strict_object,
                parse_constant=_reject_nonfinite,
            )
        except (TypeError, ValueError, RecursionError):
            raise InferencePortError(
                "Controlled provider tool arguments are incomplete.",
                failure_code="INCOMPLETE_TOOL_ARGUMENTS",
            ) from None

    if not isinstance(arguments, Mapping):
        raise InferencePortError(
            "Controlled provider tool arguments are incomplete.",
            failure_code="INCOMPLETE_TOOL_ARGUMENTS",
        )
    required = schema.get("required", [])
    if isinstance(required, list) and any(key not in arguments for key in required):
        raise InferencePortError(
            "Controlled provider tool arguments are incomplete.",
            failure_code="INCOMPLETE_TOOL_ARGUMENTS",
        )


def _normalize_tool_calls(
    raw_calls: Any,
    *,
    api_mode: str,
    schemas: Mapping[str, Mapping[str, Any]],
) -> tuple[ToolCallIdentity, ...]:
    if raw_calls is None:
        return ()
    if not isinstance(raw_calls, (list, tuple)):
        raise InferencePortError(
            "Controlled provider tool calls are malformed.",
            failure_code="INVALID_TOOL_CALL",
        )

    normalized: list[ToolCallIdentity] = []
    seen_ids: set[str] = set()
    for raw_call in raw_calls:
        call_type = _response_field(raw_call, "type")
        if api_mode == "chat_completions":
            call_id = _safe_string(_response_field(raw_call, "id"))
            function = _response_field(raw_call, "function")
            name = _safe_string(_response_field(function, "name"))
            arguments = _response_field(function, "arguments", _MISSING)
            allow_mapping = False
        elif api_mode == "anthropic_messages":
            call_id = _safe_string(_response_field(raw_call, "id"))
            name = _safe_string(_response_field(raw_call, "name"))
            arguments = _response_field(raw_call, "input", _MISSING)
            allow_mapping = True
        else:
            call_id = _safe_string(_response_field(raw_call, "call_id"))
            name = _safe_string(_response_field(raw_call, "name"))
            if call_type == "custom_tool_call":
                arguments = _response_field(raw_call, "input", _MISSING)
            else:
                arguments = _response_field(raw_call, "arguments", _MISSING)
            allow_mapping = False
            item_status = _safe_string(_response_field(raw_call, "status"))
            if item_status != "completed":
                code = (
                    "INCOMPLETE_TOOL_CALL"
                    if item_status in {"queued", "in_progress", "incomplete", None}
                    else "UNKNOWN_TERMINAL_STATUS"
                )
                raise InferencePortError(
                    "Controlled provider tool call did not complete.",
                    failure_code=code,
                )

        if call_id is None or name is None:
            raise InferencePortError(
                "Controlled provider tool identity is incomplete.",
                failure_code="INVALID_TOOL_CALL",
            )
        if call_id in seen_ids:
            raise InferencePortError(
                "Controlled provider returned a duplicate tool-call identity.",
                failure_code="DUPLICATE_TOOL_CALL_ID",
            )
        seen_ids.add(call_id)
        schema = schemas.get(name)
        if schema is None:
            raise InferencePortError(
                "Controlled provider returned a tool that was not requested.",
                failure_code="UNREQUESTED_TOOL",
            )
        _validated_arguments(
            arguments,
            schema=schema,
            allow_mapping=allow_mapping,
        )
        normalized.append(ToolCallIdentity(call_id=call_id, name=name, complete=True))

    return tuple(normalized)


def _normalize_chat_turn(
    response: Any,
    *,
    schemas: Mapping[str, Mapping[str, Any]],
) -> tuple[str, str | None, int, tuple[ToolCallIdentity, ...]]:
    choices = _response_field(response, "choices")
    if not isinstance(choices, (list, tuple)) or not choices:
        raise InferencePortError(
            "Controlled provider returned no completion choice.",
            failure_code="INVALID_RESPONSE",
        )
    choice = choices[0]
    message = _response_field(choice, "message")
    raw_status = _safe_string(_response_field(choice, "finish_reason"))
    raw_calls = _response_field(message, "tool_calls")
    has_calls = bool(raw_calls)

    if raw_status == "length":
        raise InferencePortError(
            "Controlled provider completion was incomplete.",
            failure_code="PROVIDER_INCOMPLETE",
        )
    if raw_status == "content_filter":
        status = "refused"
    elif raw_status in {"stop", "tool_calls"}:
        status = "completed"
    elif raw_status is None:
        raise InferencePortError(
            "Controlled provider omitted its terminal status.",
            failure_code="MISSING_TERMINAL_STATUS",
        )
    else:
        raise InferencePortError(
            "Controlled provider returned an unknown terminal status.",
            failure_code="UNKNOWN_TERMINAL_STATUS",
        )

    if has_calls and status == "refused":
        raise InferencePortError(
            "Provider refusal cannot authorize a tool call.",
            failure_code="PROVIDER_REFUSAL_WITH_TOOL_CALL",
        )
    if has_calls and raw_status != "tool_calls":
        raise InferencePortError(
            "Controlled provider tool calls do not match the terminal status.",
            failure_code="TOOL_CALL_STATUS_MISMATCH",
        )
    if raw_status == "tool_calls" and not has_calls:
        raise InferencePortError(
            "Controlled provider announced tool calls but returned none.",
            failure_code="MISSING_TOOL_CALLS",
        )

    tool_calls = _normalize_tool_calls(
        raw_calls,
        api_mode="chat_completions",
        schemas=schemas,
    )
    text = _output_text(_response_field(message, "content"))
    if text is None:
        text = _output_text(_response_field(message, "refusal"))
    return status, text, 0, tool_calls


def _normalize_anthropic_turn(
    response: Any,
    *,
    schemas: Mapping[str, Mapping[str, Any]],
) -> tuple[str, str | None, int, tuple[ToolCallIdentity, ...]]:
    raw_status = _safe_string(_response_field(response, "stop_reason"))
    if raw_status in {"end_turn", "stop_sequence", "tool_use"}:
        status = "completed"
    elif raw_status == "refusal":
        status = "refused"
    elif raw_status == "max_tokens":
        raise InferencePortError(
            "Controlled provider completion was incomplete.",
            failure_code="PROVIDER_INCOMPLETE",
        )
    elif raw_status is None:
        raise InferencePortError(
            "Controlled provider omitted its terminal status.",
            failure_code="MISSING_TERMINAL_STATUS",
        )
    else:
        raise InferencePortError(
            "Controlled provider returned an unknown terminal status.",
            failure_code="UNKNOWN_TERMINAL_STATUS",
        )

    content = _response_field(response, "content")
    if not isinstance(content, (list, tuple)):
        raise InferencePortError(
            "Controlled provider returned malformed content.",
            failure_code="INVALID_RESPONSE",
        )
    raw_calls = [block for block in content if _response_field(block, "type") == "tool_use"]
    if raw_calls and raw_status != "tool_use":
        raise InferencePortError(
            "Controlled provider tool calls do not match the terminal status.",
            failure_code="TOOL_CALL_STATUS_MISMATCH",
        )
    if raw_status == "tool_use" and not raw_calls:
        raise InferencePortError(
            "Controlled provider announced tool use but returned none.",
            failure_code="MISSING_TOOL_CALLS",
        )
    if raw_calls and status == "refused":
        raise InferencePortError(
            "Provider refusal cannot authorize a tool call.",
            failure_code="PROVIDER_REFUSAL_WITH_TOOL_CALL",
        )
    tool_calls = _normalize_tool_calls(
        raw_calls,
        api_mode="anthropic_messages",
        schemas=schemas,
    )
    text = "\n".join(
        value
        for block in content
        if _response_field(block, "type") == "text"
        if (value := _output_text(_response_field(block, "text")))
    ) or None
    return status, text, 0, tool_calls


def _text_from_responses_message(item: Any) -> str:
    content = _response_field(item, "content")
    if not isinstance(content, (list, tuple)):
        return ""
    parts = []
    for part in content:
        if _response_field(part, "type") != "output_text":
            continue
        text = _output_text(_response_field(part, "text"))
        if text:
            parts.append(text)
    return "".join(parts)


def _normalize_codex_turn(
    response: Any,
    *,
    schemas: Mapping[str, Mapping[str, Any]],
) -> tuple[str, str | None, int, tuple[ToolCallIdentity, ...]]:
    if _response_field(response, "terminal_observed") is not True:
        raise InferencePortError(
            "Controlled provider did not emit a terminal response.",
            failure_code="MISSING_TERMINAL_STATUS",
        )
    raw_status = _safe_string(_response_field(response, "status"))
    output = _response_field(response, "output", [])
    if output is None:
        output = []
    if not isinstance(output, (list, tuple)):
        raise InferencePortError(
            "Controlled provider returned malformed output items.",
            failure_code="INVALID_RESPONSE",
        )
    incomplete_details = _response_field(response, "incomplete_details")
    incomplete_reason = _safe_string(_response_field(incomplete_details, "reason"))
    if raw_status == "incomplete" and incomplete_reason == "content_filter":
        status = "refused"
    elif raw_status == "completed":
        if _response_field(response, "completion_observed") is not True:
            raise InferencePortError(
                "Controlled provider did not confirm completion.",
                failure_code="MISSING_TERMINAL_STATUS",
            )
        status = "completed"
    elif raw_status == "incomplete":
        raise InferencePortError(
            "Controlled provider completion was incomplete.",
            failure_code="PROVIDER_INCOMPLETE",
        )
    elif raw_status == "failed":
        raise InferencePortError(
            "Controlled provider reported a failed completion.",
            failure_code="PROVIDER_FAILED",
        )
    elif raw_status is None:
        raise InferencePortError(
            "Controlled provider omitted its terminal status.",
            failure_code="MISSING_TERMINAL_STATUS",
        )
    else:
        raise InferencePortError(
            "Controlled provider returned an unknown terminal status.",
            failure_code="UNKNOWN_TERMINAL_STATUS",
        )

    raw_calls = []
    final_parts: list[str] = []
    commentary_count = 0
    saw_nonfinal_phase = False
    for item in output:
        item_type = _response_field(item, "type")
        if item_type in {"function_call", "custom_tool_call"}:
            raw_calls.append(item)
            continue
        if item_type != "message":
            continue
        item_status = _safe_string(_response_field(item, "status"))
        if item_status in {"queued", "in_progress", "incomplete"}:
            raise InferencePortError(
                "Controlled provider returned an incomplete message item.",
                failure_code="PROVIDER_INCOMPLETE",
            )
        if item_status and item_status != "completed":
            raise InferencePortError(
                "Controlled provider returned an unknown output-item status.",
                failure_code="UNKNOWN_TERMINAL_STATUS",
            )
        phase = (_safe_string(_response_field(item, "phase")) or "").lower()
        if phase == "commentary":
            commentary_count += 1
            saw_nonfinal_phase = True
            continue
        if phase == "analysis":
            saw_nonfinal_phase = True
            continue
        if phase not in {"", "final", "final_answer"}:
            raise InferencePortError(
                "Controlled provider returned an unknown message phase.",
                failure_code="UNKNOWN_MESSAGE_PHASE",
            )
        text = _text_from_responses_message(item)
        if text:
            final_parts.append(text)

    if raw_calls and status == "refused":
        raise InferencePortError(
            "Provider refusal cannot authorize a tool call.",
            failure_code="PROVIDER_REFUSAL_WITH_TOOL_CALL",
        )
    tool_calls = _normalize_tool_calls(
        raw_calls,
        api_mode="codex_responses",
        schemas=schemas,
    )
    joined_final_text = "\n".join(final_parts)
    final_text = joined_final_text if joined_final_text.strip() else None
    if final_text is None and not saw_nonfinal_phase:
        final_text = _output_text(_response_field(response, "output_text"))
    if status == "completed" and final_text is None and not tool_calls:
        raise InferencePortError(
            "Controlled provider returned an empty completion.",
            failure_code="EMPTY_TURN",
        )
    return status, final_text, commentary_count, tool_calls


def _normalize_parent_turn(
    response: Any,
    *,
    api_mode: str,
    request: Mapping[str, Any],
    requester: Any,
) -> NormalizedTurn:
    if response is None:
        raise InferencePortError(
            "Controlled provider returned no response.",
            failure_code="INVALID_RESPONSE",
        )
    schemas = _request_tool_schemas(request)
    if api_mode == "chat_completions":
        status, text, commentary_count, tool_calls = _normalize_chat_turn(
            response,
            schemas=schemas,
        )
    elif api_mode == "anthropic_messages":
        status, text, commentary_count, tool_calls = _normalize_anthropic_turn(
            response,
            schemas=schemas,
        )
    elif api_mode == "codex_responses":
        status, text, commentary_count, tool_calls = _normalize_codex_turn(
            response,
            schemas=schemas,
        )
    else:
        raise InferencePortError(
            "Controlled provider response mode is unsupported.",
            failure_code="INVALID_RESPONSE",
        )

    configured_model = _safe_string(getattr(requester, "requested_model", None))
    if configured_model is None:
        configured_model = _safe_string(getattr(requester, "model", None))
    return NormalizedTurn(
        response=response,
        terminal_status=status,
        final_text=text,
        commentary_count=commentary_count,
        tool_calls=tool_calls,
        configured_model=configured_model,
        requested_model=_safe_string(request.get("model")),
        reported_model=_safe_string(
            _response_field(
                response,
                "provider_reported_model" if api_mode == "codex_responses" else "model",
            )
        ),
        configured_effort=_configured_effort(requester),
        wire_effort=_wire_effort(request),
        reported_effort=_reported_effort(response),
    )
