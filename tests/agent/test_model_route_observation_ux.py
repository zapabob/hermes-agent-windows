"""Unit tests for ModelRouteObservation UX contract (Slice G).

Verifies:
1. Normal turn: quiet label, no divergence, no warnings.
2. Canonicalization turn: prefix stripping is NOT flagged as drift or divergence.
3. Provider model drift: requested != reported model from provider flagged as drift.
4. Fallback turn: fallback=True flagged as divergent with structured UX summary.
5. to_dict() serialization preserves all presentation fields.
"""

from agent.model_route_observation import ModelRouteObservation


def test_normal_route_observation_quiet():
    obs = ModelRouteObservation(
        requested_provider="anthropic",
        requested_model="claude-3-7-sonnet",
        wire_provider="anthropic",
        wire_model="claude-3-7-sonnet",
        effective_provider="anthropic",
        effective_model="claude-3-7-sonnet",
        fallback=False,
        effective_model_source="request",
    )
    assert not obs.is_divergent()
    assert not obs.is_drift()
    assert not obs.isDivergent
    assert not obs.isDrift

    summary = obs.ux_summary()
    assert summary["type"] == "normal"
    assert summary["divergent"] is False
    assert "Claude" in obs.quiet_label()
    assert "Anthropic" in obs.quiet_label()


def test_canonicalization_not_treated_as_drift():
    # e.g. User requested anthropic/claude-3-7-sonnet, wire/effective is claude-3-7-sonnet
    obs = ModelRouteObservation(
        requested_provider="anthropic",
        requested_model="anthropic/claude-3-7-sonnet",
        wire_provider="anthropic",
        wire_model="claude-3-7-sonnet",
        effective_provider="anthropic",
        effective_model="claude-3-7-sonnet",
        fallback=False,
        effective_model_source="response",
    )
    assert not obs.is_divergent()
    assert not obs.is_drift()
    assert obs.ux_summary()["type"] == "normal"


def test_provider_model_drift_prominent():
    # User requested model-A, provider responded with model-B
    obs = ModelRouteObservation(
        requested_provider="openai",
        requested_model="model-A",
        wire_provider="openai",
        wire_model="model-A",
        effective_provider="openai",
        effective_model="model-B",
        fallback=False,
        effective_model_source="response",
    )
    assert obs.is_divergent()
    assert obs.is_drift()
    assert obs.isDivergent
    assert obs.isDrift

    summary = obs.ux_summary()
    assert summary["type"] == "drift"
    assert summary["divergent"] is True
    assert "Provider model drift" in summary["title"]
    assert "Requested: model-A" in summary["lines"]
    assert "Provider reported: model-B" in summary["lines"]


def test_fallback_prominent():
    # Fallback from NVIDIA / model-N to Nous / model-F
    obs = ModelRouteObservation(
        requested_provider="nvidia",
        requested_model="model-N",
        wire_provider="nous",
        wire_model="model-F",
        effective_provider="nous",
        effective_model="model-F",
        fallback=True,
        reason="rate limit",
        effective_model_source="request",
    )
    assert obs.is_divergent()
    assert not obs.is_drift()  # fallback takes precedence over drift
    assert obs.isDivergent
    assert not obs.isDrift

    summary = obs.ux_summary()
    assert summary["type"] == "fallback"
    assert summary["divergent"] is True
    assert "Fallback active" in summary["title"]
    assert "Requested: NVIDIA / model-N" in summary["lines"]
    assert "Using: Nous / model-F" in summary["lines"]
    assert "Reason: rate limit" in summary["lines"]


def test_to_dict_preserves_observability_fields():
    obs = ModelRouteObservation(
        requested_provider="nvidia",
        requested_model="model-N",
        wire_provider="nous",
        wire_model="model-F",
        effective_provider="nous",
        effective_model="model-F",
        fallback=True,
        reason="service unavailable",
    )
    d = obs.to_dict()
    assert d["fallback"] is True
    assert d["is_divergent"] is True
    assert d["isDivergent"] is True
    assert d["is_drift"] is False
    assert d["isDrift"] is False
    assert "ux_summary" in d
    assert "uxSummary" in d
    assert "quiet_label" in d
    assert "quietLabel" in d
    assert d["requestedProvider"] == "nvidia"
    assert d["requestedModel"] == "model-N"
    assert d["effectiveProvider"] == "nous"
    assert d["effectiveModel"] == "model-F"
