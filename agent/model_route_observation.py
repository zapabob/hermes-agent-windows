"""Model route observation data structures and helpers.

Tracks requested vs wire vs effective model routing for observability,
ensuring explicit visibility into canonicalization, fallback, and
provider-reported models without leaking secrets.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Optional


@dataclass
class ModelRouteObservation:
    """Internal representation of model routing intent vs reality.

    No secrets are stored here (no api_key, OAuth token, headers,
    or credential identifiers).
    """

    requested_provider: str
    requested_model: str
    wire_provider: str
    wire_model: str
    effective_provider: str
    effective_model: str
    fallback: bool = False
    reason: Optional[str] = None
    effective_model_source: str = "request"  # "request" | "response" | "server"
    session_id: Optional[str] = None

    # CamelCase properties for interoperability
    @property
    def sessionId(self) -> Optional[str]:
        return self.session_id

    @property
    def requestedProvider(self) -> str:
        return self.requested_provider

    @property
    def requestedModel(self) -> str:
        return self.requested_model

    @property
    def wireProvider(self) -> str:
        return self.wire_provider

    @property
    def wireModel(self) -> str:
        return self.wire_model

    @property
    def effectiveProvider(self) -> str:
        return self.effective_provider

    @property
    def effectiveModel(self) -> str:
        return self.effective_model

    @property
    def effectiveModelSource(self) -> str:
        return self.effective_model_source

    def to_dict(self) -> dict[str, Any]:
        return {
            "session_id": self.session_id,
            "requested_provider": self.requested_provider,
            "requested_model": self.requested_model,
            "wire_provider": self.wire_provider,
            "wire_model": self.wire_model,
            "effective_provider": self.effective_provider,
            "effective_model": self.effective_model,
            "fallback": self.fallback,
            "reason": self.reason,
            "effective_model_source": self.effective_model_source,
            # CamelCase aliases for JSON consumers
            "sessionId": self.session_id,
            "requestedProvider": self.requested_provider,
            "requestedModel": self.requested_model,
            "wireProvider": self.wire_provider,
            "wireModel": self.wire_model,
            "effectiveProvider": self.effective_provider,
            "effectiveModel": self.effective_model,
            "effectiveModelSource": self.effective_model_source,
        }

    @classmethod
    def from_agent(
        cls,
        agent: Any,
        *,
        wire_provider: Optional[str] = None,
        wire_model: Optional[str] = None,
        effective_provider: Optional[str] = None,
        effective_model: Optional[str] = None,
        fallback: Optional[bool] = None,
        reason: Optional[str] = None,
        effective_model_source: str = "request",
        session_id: Optional[str] = None,
    ) -> ModelRouteObservation:
        req_p = str(getattr(agent, "requested_provider", "") or getattr(agent, "provider", "")).strip()
        req_m = str(getattr(agent, "requested_model", "") or getattr(agent, "model", "")).strip()
        act_p = str(getattr(agent, "provider", "")).strip()
        act_m = str(getattr(agent, "model", "")).strip()

        wp = str(wire_provider or act_p or req_p).strip()
        wm = str(wire_model or act_m or req_m).strip()
        ep = str(effective_provider or act_p or wp).strip()
        em = str(effective_model or act_m or wm).strip()

        fb = bool(
            fallback
            if fallback is not None
            else (
                getattr(agent, "fallback_active", False)
                or getattr(agent, "_fallback_reason", None)
                or (act_p != req_p and act_p != "")
            )
        )
        r = str(reason or getattr(agent, "_fallback_reason", None) or "").strip() or None
        sess_id = str(session_id or getattr(agent, "session_id", None) or "").strip() or None

        return cls(
            requested_provider=req_p,
            requested_model=req_m,
            wire_provider=wp,
            wire_model=wm,
            effective_provider=ep,
            effective_model=em,
            fallback=fb,
            reason=r,
            effective_model_source=effective_model_source,
            session_id=sess_id,
        )


def build_route_observation(
    agent: Any = None,
    *,
    requested_provider: Optional[str] = None,
    requested_model: Optional[str] = None,
    wire_provider: Optional[str] = None,
    wire_model: Optional[str] = None,
    effective_provider: Optional[str] = None,
    effective_model: Optional[str] = None,
    fallback: Optional[bool] = None,
    reason: Optional[str] = None,
    effective_model_source: str = "request",
    session_id: Optional[str] = None,
) -> ModelRouteObservation:
    """Build a sanitized ModelRouteObservation from agent or explicit parameters."""
    if agent is not None:
        return ModelRouteObservation.from_agent(
            agent,
            wire_provider=wire_provider,
            wire_model=wire_model,
            effective_provider=effective_provider,
            effective_model=effective_model,
            fallback=fallback,
            reason=reason,
            effective_model_source=effective_model_source,
            session_id=session_id,
        )

    req_p = str(requested_provider or "").strip()
    req_m = str(requested_model or "").strip()
    wp = str(wire_provider or req_p).strip()
    wm = str(wire_model or req_m).strip()
    ep = str(effective_provider or wp).strip()
    em = str(effective_model or wm).strip()
    sess_id = str(session_id or "").strip() or None

    return ModelRouteObservation(
        requested_provider=req_p,
        requested_model=req_m,
        wire_provider=wp,
        wire_model=wm,
        effective_provider=ep,
        effective_model=em,
        fallback=bool(fallback),
        reason=str(reason).strip() if reason else None,
        effective_model_source=str(effective_model_source or "request").strip(),
        session_id=sess_id,
    )
