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


def test_sanitize_and_bound_route_reason_bounding():
    from agent.model_route_observation import sanitize_and_bound_route_reason

    # Reason exceeding max_len (default 200)
    long_reason = "rate limit exceeded: " + ("x" * 250)
    sanitized = sanitize_and_bound_route_reason(long_reason, max_len=200)
    assert sanitized is not None
    assert len(sanitized) <= 200
    assert sanitized.endswith("...")
    assert sanitized.startswith("rate limit exceeded: xxx")


def test_sanitize_and_bound_route_reason_normalization():
    from agent.model_route_observation import sanitize_and_bound_route_reason

    # Reason with ANSI escapes, newlines, tabs, and multiple spaces
    raw = "\x1b[31mError:\x1b[0m\n\tprovider failed\r\nwith status   503"
    sanitized = sanitize_and_bound_route_reason(raw)
    assert sanitized == "Error: provider failed with status 503"


def test_sanitize_and_bound_route_reason_redaction():
    from agent.model_route_observation import sanitize_and_bound_route_reason

    # Reason containing bearer token, api key, and sensitive credentials
    raw = "Failed with Bearer eyJhbGciOiJIUzI1Ni... and key sk-1234567890abcdef and token=secret_value_12345"
    sanitized = sanitize_and_bound_route_reason(raw)
    assert "Bearer [REDACTED]" in sanitized
    assert "sk-[REDACTED]" in sanitized
    assert "token=[REDACTED]" in sanitized
    assert "secret_value" not in sanitized


def test_model_route_observation_sanitizes_automatically():
    raw_reason = "HTTP 401: Invalid key sk-abcdef1234567890\n\tDetails: unauthorized"
    obs = ModelRouteObservation(
        requested_provider="nvidia",
        requested_model="model-N",
        wire_provider="nous",
        wire_model="model-F",
        effective_provider="nous",
        effective_model="model-F",
        fallback=True,
        reason=raw_reason,
    )
    assert "sk-[REDACTED]" in obs.reason
    assert "\n" not in obs.reason
    assert "\t" not in obs.reason

    # Check to_dict() and ux_summary()
    d = obs.to_dict()
    assert "sk-[REDACTED]" in d["reason"]
    assert "\n" not in d["reason"]

    summary = obs.ux_summary()
    assert any("sk-[REDACTED]" in line for line in summary["lines"])
    assert not any("\n" in line for line in summary["lines"])

