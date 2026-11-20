"""Subagents never inherit the 1h prompt-cache tier.

With ``prompt_caching.cache_ttl: 1h`` the parent keeps 1h, the child is built
at 5m, and the child's wire markers carry no ``ttl``. A disabled cache stays
disabled (the child is not re-enabled to 5m).
"""

from types import SimpleNamespace

from agent.prompt_caching import apply_anthropic_cache_control
from tools.delegate_tool import _apply_child_cache_ttl


def _markers(messages):
    out = []
    for m in messages:
        c = m.get("content")
        if isinstance(c, list):
            out += [b["cache_control"] for b in c if isinstance(b, dict) and "cache_control" in b]
        if "cache_control" in m:
            out.append(m["cache_control"])
    return out


def test_child_1h_becomes_5m_and_wire_markers_drop_ttl():
    child = SimpleNamespace(_cache_ttl="1h")
    _apply_child_cache_ttl(child)
    assert child._cache_ttl == "5m"
    msgs = [
        {"role": "system", "content": "sys"},
        {"role": "user", "content": "hi"},
        {"role": "assistant", "content": "ok"},
        {"role": "user", "content": "go"},
    ]
    wire = apply_anthropic_cache_control([dict(m) for m in msgs], cache_ttl=child._cache_ttl)
    marks = _markers(wire)
    assert marks and all("ttl" not in m for m in marks), marks
    # The parent's 1h layout really is different, so this is not a vacuous check.
    parent_marks = _markers(apply_anthropic_cache_control([dict(m) for m in msgs], cache_ttl="1h"))
    assert any(m.get("ttl") == "1h" for m in parent_marks)


def test_disabled_and_5m_are_left_alone():
    for ttl in (None, "5m"):
        child = SimpleNamespace(_cache_ttl=ttl)
        _apply_child_cache_ttl(child)
        assert child._cache_ttl == ttl
