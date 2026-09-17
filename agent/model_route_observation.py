"""Model route observation data structures and helpers.

Tracks requested vs wire vs effective model routing for observability,
ensuring explicit visibility into canonicalization, fallback, and
provider-reported models without leaking secrets.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Optional


def _prettify_model_id(model_id: str) -> str:
    """Format model identifier cleanly (e.g. 'claude-3-7-sonnet' -> 'Claude 3 7 Sonnet')."""
    raw = model_id.split("/")[-1].strip() if "/" in model_id else model_id.strip()
    if not raw:
        return ""
    lower = raw.lower()
    if lower.startswith("claude-"):
        parts = raw[7:].replace("-", " ").title()
        return f"Claude {parts}"
    if lower.startswith("gpt-"):
        return f"GPT-{raw[4:]}"
    if lower.startswith("gemini-"):
        parts = raw[7:].replace("-", " ").title()
        return f"Gemini {parts}"
    return raw


def _prettify_provider(provider: str) -> str:
    """Friendly title for provider."""
    p = (provider or "").strip()
    if not p:
        return ""
    mapping = {
        "openai": "OpenAI",
        "openrouter": "OpenRouter",
        "nous": "Nous",
        "anthropic": "Anthropic",
        "google": "Google",
        "gemini": "Google",
        "deepseek": "DeepSeek",
        "copilot": "Copilot",
        "copilot-acp": "Copilot ACP",
        "nvidia": "NVIDIA",
        "meta": "Meta",
        "ollama": "Ollama",
    }
    return mapping.get(p.lower(), p.title())


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

    @property
    def isDivergent(self) -> bool:
        return self.is_divergent()

    @property
    def isDrift(self) -> bool:
        return self.is_drift()

    def is_drift(self) -> bool:
        """True when the provider/server reported a different model than requested/wire."""
        if self.fallback:
            return False
        if self.effective_model_source not in ("response", "server"):
            return False

        req = self.requested_model.strip()
        wire = self.wire_model.strip()
        eff = self.effective_model.strip()
        if not eff or not req:
            return False

        req_clean = req.split("/")[-1].strip().lower() if "/" in req else req.lower()
        wire_clean = wire.split("/")[-1].strip().lower() if "/" in wire else wire.lower()
        eff_clean = eff.split("/")[-1].strip().lower() if "/" in eff else eff.lower()

        if eff_clean == req_clean or eff_clean == wire_clean:
            return False

        return True

    def is_divergent(self) -> bool:
        """True if either fallback occurred or provider model drift was observed."""
        return bool(self.fallback or self.is_drift())

    def quiet_label(self) -> str:
        """Standard quiet label when no divergence occurred (e.g. 'Claude Sonnet 3.7 · Anthropic')."""
        eff_m = _prettify_model_id(self.effective_model)
        eff_p = _prettify_provider(self.effective_provider)
        if eff_m and eff_p:
            return f"{eff_m} · {eff_p}"
        return eff_m or eff_p or "Ready"

    def ux_summary(self) -> dict[str, Any]:
        """User-facing structured summary of the routing observation."""
        if self.fallback:
            req_p = _prettify_provider(self.requested_provider) or self.requested_provider
            eff_p = _prettify_provider(self.effective_provider) or self.effective_provider
            lines = [
                f"Requested: {req_p} / {self.requested_model}",
                f"Using: {eff_p} / {self.effective_model}",
            ]
            if self.reason:
                lines.append(f"Reason: {self.reason}")
            return {
                "type": "fallback",
                "divergent": True,
                "title": "Fallback active",
                "lines": lines,
                "banner": " | ".join(lines),
            }
        elif self.is_drift():
            lines = [
                f"Requested: {self.requested_model}",
                f"Provider reported: {self.effective_model}",
            ]
            return {
                "type": "drift",
                "divergent": True,
                "title": "Provider model drift",
                "lines": lines,
                "banner": " | ".join(lines),
            }
        else:
            return {
                "type": "normal",
                "divergent": False,
                "title": "Normal route",
                "lines": [self.quiet_label()],
                "banner": self.quiet_label(),
            }

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
            "is_divergent": self.is_divergent(),
            "is_drift": self.is_drift(),
            "quiet_label": self.quiet_label(),
            "ux_summary": self.ux_summary(),
            # CamelCase aliases for JSON consumers
            "sessionId": self.session_id,
            "requestedProvider": self.requested_provider,
            "requestedModel": self.requested_model,
            "wireProvider": self.wire_provider,
            "wireModel": self.wire_model,
            "effectiveProvider": self.effective_provider,
            "effectiveModel": self.effective_model,
            "effectiveModelSource": self.effective_model_source,
            "isDivergent": self.is_divergent(),
            "isDrift": self.is_drift(),
            "quietLabel": self.quiet_label(),
            "uxSummary": self.ux_summary(),
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
                getattr(agent, "_fallback_activated", False)
                or getattr(agent, "fallback_active", False)
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
