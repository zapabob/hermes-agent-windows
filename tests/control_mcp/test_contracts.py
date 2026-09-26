"""Weakening expiry/scope/profile checks or JSON boundaries must be detected."""
from dataclasses import FrozenInstanceError

import pytest


def test_read_never_implies_merge(control_module, control_context):
    m = control_module("contracts")
    with pytest.raises(m.ControlError) as error:
        m.require_access(control_context(), scope="hermes:repo:merge", profile_id="p1", workspace_id="w1", now=100)
    assert error.value.code == "insufficient_scope"


@pytest.mark.parametrize("change", [{"expires_at": 100}, {"profiles": ("p2",)}, {"workspaces": (("p2", "w1"),)}, {"scopes": ()}])
def test_grants_expiry_and_resource_pairs_are_enforced(control_module, control_context, change):
    m = control_module("contracts")
    with pytest.raises(m.ControlError):
        m.require_access(control_context(**change), scope="hermes:read", profile_id="p1", workspace_id="w1", now=100)


def test_context_is_frozen_and_has_no_token(control_context):
    ctx = control_context()
    with pytest.raises(FrozenInstanceError):
        ctx.subject = "other"
    assert "token" not in vars(ctx)


@pytest.mark.parametrize("expiry", [True, "200", float("inf")])
def test_context_requires_exact_integer_expiry(control_module, control_context, expiry):
    with pytest.raises(control_module("contracts").ControlError):
        control_context(expires_at=expiry)


@pytest.mark.parametrize("raw", ['{"x":1,"x":2}', '{"x":NaN}', '{"x":Infinity}', '[1]', '{', '{"x":"\\ud800"}'])
def test_strict_json_rejects_ambiguous_input(control_module, raw):
    m = control_module("contracts")
    with pytest.raises(m.ControlError):
        m.decode_request(raw.encode())


def test_json_byte_and_depth_budgets(control_module):
    m = control_module("contracts")
    with pytest.raises(m.ControlError):
        m.decode_request(('{"x":"' + 'あ'*12000 + '"}').encode())
    with pytest.raises(m.ControlError):
        m.decode_request(('{' + '"x":{'*25 + '"a":1' + '}'*26).encode())


def test_digest_is_canonical_and_order_independent(control_module):
    m = control_module("contracts")
    assert m.canonical_intent_digest({"a":1,"b":"日本"}) == m.canonical_intent_digest({"b":"日本","a":1})
    assert m.canonical_intent_digest({"a":1}) != m.canonical_intent_digest({"a":2})


def test_error_does_not_carry_untrusted_details(control_module):
    m = control_module("contracts")
    assert str(m.ControlError("insufficient_scope")) == "insufficient_scope"
    with pytest.raises(ValueError):
        m.ControlError("error: secret=http://token.invalid")
