"""Credential-free control identities and strict, bounded wire primitives."""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import math
import re

MAX_REQUEST_BYTES = 32_768
MAX_EVIDENCE_BYTES = 65_536
_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}\Z")
_CODE = re.compile(r"[a-z][a-z0-9_]{0,79}\Z")


class ControlError(ValueError):
    """Only a stable code crosses the boundary; never exception/provider text."""

    def __init__(self, code: str):
        if type(code) is not str or not _CODE.fullmatch(code):
            raise ValueError("invalid_control_error_code")
        self.code = code
        super().__init__(code)


def valid_id(value: object) -> bool:
    return type(value) is str and bool(_ID.fullmatch(value)) and ".." not in value


@dataclass(frozen=True)
class ControlContext:
    """Constructed by the resource verifier, not from model-supplied arguments.

    A Python object is not an isolation barrier against an authorised in-process
    plugin. Authentication at the transport and live grant checks remain required.
    Workspace grants are profile/workspace pairs, not a Cartesian product.
    """

    subject: str
    client_registration: str
    issuer: str
    resource: str
    grant_revision: int
    expires_at: int
    scopes: tuple[str, ...]
    profiles: tuple[str, ...]
    workspaces: tuple[tuple[str, str], ...]

    def __post_init__(self) -> None:
        if (not valid_id(self.subject) or not valid_id(self.client_registration)
                or type(self.issuer) is not str or not self.issuer
                or type(self.resource) is not str or not self.resource
                or type(self.expires_at) is not int or self.expires_at < 0
                or type(self.grant_revision) is not int or self.grant_revision < 1):
            raise ControlError("invalid_context")
        for values in (self.scopes, self.profiles):
            if type(values) is not tuple or not all(valid_id(v) for v in values):
                raise ControlError("invalid_context")
        if (type(self.workspaces) is not tuple
                or any(type(pair) is not tuple or len(pair) != 2
                       or not all(valid_id(v) for v in pair) for pair in self.workspaces)):
            raise ControlError("invalid_context")


@dataclass(frozen=True)
class VerifiedResultReceipt:
    """Host verification of one scratch result: evidence for an apply, never authority.

    Only the trusted host verifier constructs it; it carries no approval, and an
    apply still needs its own human decision bound to these same digests.
    """

    source_operation_id: str
    run_id: str
    candidate_digest: str
    verification_digest: str
    verified: bool


def require_access(ctx: ControlContext, *, scope: str, profile_id: str,
                   workspace_id: str | None = None, now: float) -> None:
    if type(ctx) is not ControlContext:
        raise ControlError("unauthenticated")
    if type(now) not in (int, float) or not math.isfinite(now) or now >= ctx.expires_at:
        raise ControlError("expired_grant")
    if "hermes:read" not in ctx.scopes or scope not in ctx.scopes:
        raise ControlError("insufficient_scope")
    if not valid_id(profile_id) or profile_id not in ctx.profiles:
        raise ControlError("resource_denied")
    if workspace_id is not None and (
            not valid_id(workspace_id) or (profile_id, workspace_id) not in ctx.workspaces):
        raise ControlError("resource_denied")


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ControlError("duplicate_json_key")
        result[key] = value
    return result


def _invalid_constant(_):
    raise ControlError("invalid_json")


def _validate_json(value: object, depth: int = 0) -> None:
    if depth > 16:
        raise ControlError("request_too_deep")
    if type(value) is dict:
        for key, item in value.items():
            if type(key) is not str:
                raise ControlError("invalid_json")
            key.encode("utf-8", "strict")
            _validate_json(item, depth + 1)
    elif type(value) is list:
        for item in value:
            _validate_json(item, depth + 1)
    elif type(value) is str:
        value.encode("utf-8", "strict")
    elif type(value) is float:
        if not math.isfinite(value):
            raise ControlError("invalid_json")
    elif type(value) not in (int, bool, type(None)):
        raise ControlError("invalid_json")


def canonical_json(payload: dict, *, limit: int = MAX_REQUEST_BYTES) -> bytes:
    if type(payload) is not dict:
        raise ControlError("invalid_request")
    try:
        _validate_json(payload)
        encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True,
                             separators=(",", ":"), allow_nan=False).encode("utf-8")
    except (UnicodeError, TypeError, ValueError, RecursionError) as exc:
        if isinstance(exc, ControlError):
            raise
        raise ControlError("invalid_json") from None
    if len(encoded) > limit:
        raise ControlError("request_too_large")
    return encoded


def decode_request(raw: bytes, *, limit: int = MAX_REQUEST_BYTES) -> dict:
    if type(raw) is not bytes or len(raw) > limit:
        raise ControlError("request_too_large")
    try:
        value = json.loads(raw.decode("utf-8"), object_pairs_hook=_unique_object,
                           parse_constant=_invalid_constant)
        canonical_json(value, limit=limit)
        return value
    except (ValueError, UnicodeError, RecursionError) as exc:
        if isinstance(exc, ControlError):
            raise
        raise ControlError("invalid_json") from None


def canonical_intent_digest(payload: dict) -> str:
    return hashlib.sha256(canonical_json(payload)).hexdigest()
