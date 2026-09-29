"""Serializer-warning leak regression tests (#82xxx).

The Anthropic SDK's streaming accumulator builds ``ParsedMessage`` snapshots
whose content blocks (``ParsedTextBlock``) don't match the generic union
pydantic expects at serialization time. ``model_dump()`` on those objects
emits ``PydanticSerializationUnexpectedValue`` UserWarnings that leak
straight into the user's terminal mid-response.

Every Hermes serialization helper that dumps arbitrary SDK models must pass
``warnings=False`` (with a TypeError fallback for duck-typed models). These
tests pin that contract for all four helpers.

Newer SDK releases no longer trip the warning with the streaming fixture, so
the suppression contract is pinned with a deliberately mistyped pydantic
model that always warns; the SDK fixture still checks the payload shape.
"""

import warnings

import pytest
from pydantic import BaseModel

anthropic = pytest.importorskip("anthropic")

from anthropic._models import build
from anthropic.lib.streaming._messages import accumulate_event
from anthropic.lib.streaming._types import ParsedMessageStopEvent
from anthropic.types import (
    Message,
    RawContentBlockDeltaEvent,
    RawContentBlockStartEvent,
    RawMessageStartEvent,
    Usage,
)


def _accumulated_stop_event():
    """Build a message_stop event exactly the way the SDK stream does."""
    start = RawMessageStartEvent(
        type="message_start",
        message=Message(
            id="msg_1",
            content=[],
            model="claude-x",
            role="assistant",
            stop_reason=None,
            stop_sequence=None,
            type="message",
            usage=Usage(input_tokens=1, output_tokens=0),
        ),
    )
    cb_start = RawContentBlockStartEvent(
        type="content_block_start", index=0, content_block={"type": "text", "text": ""}
    )
    cb_delta = RawContentBlockDeltaEvent(
        type="content_block_delta",
        index=0,
        delta={"type": "text_delta", "text": "hello"},
    )
    snapshot = None
    for event in (start, cb_start, cb_delta):
        snapshot = accumulate_event(event=event, current_snapshot=snapshot)
    return build(ParsedMessageStopEvent, type="message_stop", message=snapshot), snapshot


def _pydantic_warnings(recorded):
    return [w for w in recorded if "Pydantic serializer warnings" in str(w.message)]


class _Inner(BaseModel):
    x: int


class _Outer(BaseModel):
    inner: _Inner


def _mistyped_model():
    """A model whose field holds a value of the wrong type, as SDK snapshots can."""
    return _Outer.model_construct(inner="not-a-model")


def _helpers():
    from agent.anthropic_adapter import _to_plain_data
    from agent.relay_llm import _jsonable as relay_llm_jsonable
    from agent.relay_tools import _jsonable as relay_tools_jsonable
    from run_agent import AIAgent

    return {
        "relay_llm": relay_llm_jsonable,
        "relay_tools": relay_tools_jsonable,
        "anthropic_adapter": _to_plain_data,
        "hook_jsonable": AIAgent._hook_jsonable,
    }


def test_mistyped_model_dump_warns_without_suppression():
    """Precondition: the synthetic fixture really trips the pydantic warning."""
    with warnings.catch_warnings(record=True) as recorded:
        warnings.simplefilter("always")
        _mistyped_model().model_dump()
    assert _pydantic_warnings(recorded)


@pytest.mark.parametrize(
    "helper_name", ["relay_llm", "relay_tools", "anthropic_adapter", "hook_jsonable"]
)
def test_helpers_suppress_serializer_warnings(helper_name):
    helper = _helpers()[helper_name]
    with warnings.catch_warnings(record=True) as recorded:
        warnings.simplefilter("always")
        payload = helper(_mistyped_model())
    assert not _pydantic_warnings(recorded)
    assert payload == {"inner": "not-a-model"}


def test_relay_llm_jsonable_no_warning_leak():
    from agent.relay_llm import _jsonable

    stop_event, _ = _accumulated_stop_event()
    with warnings.catch_warnings(record=True) as recorded:
        warnings.simplefilter("always")
        payload = _jsonable(stop_event)
    assert not _pydantic_warnings(recorded)
    assert payload["message"]["content"][0]["text"] == "hello"


def test_relay_tools_jsonable_no_warning_leak():
    from agent.relay_tools import _jsonable

    stop_event, _ = _accumulated_stop_event()
    with warnings.catch_warnings(record=True) as recorded:
        warnings.simplefilter("always")
        payload = _jsonable(stop_event)
    assert not _pydantic_warnings(recorded)
    assert payload["message"]["content"][0]["text"] == "hello"


def test_anthropic_to_plain_data_no_warning_leak():
    from agent.anthropic_adapter import _to_plain_data

    _, snapshot = _accumulated_stop_event()
    with warnings.catch_warnings(record=True) as recorded:
        warnings.simplefilter("always")
        payload = _to_plain_data(snapshot)
    assert not _pydantic_warnings(recorded)
    assert payload["content"][0]["text"] == "hello"


def test_hook_jsonable_no_warning_leak():
    from run_agent import AIAgent

    stop_event, _ = _accumulated_stop_event()
    with warnings.catch_warnings(record=True) as recorded:
        warnings.simplefilter("always")
        payload = AIAgent._hook_jsonable(stop_event)
    assert not _pydantic_warnings(recorded)
    assert payload["message"]["content"][0]["text"] == "hello"


def test_duck_typed_model_dump_fallback():
    """Non-pydantic objects with a bare model_dump() must still serialize."""
    from agent.relay_llm import _jsonable as rl_jsonable
    from agent.relay_tools import _jsonable as rt_jsonable
    from agent.anthropic_adapter import _to_plain_data

    class Duck:
        def model_dump(self):  # no mode/warnings kwargs
            return {"quack": True}

    assert rl_jsonable(Duck()) == {"quack": True}
    assert rt_jsonable(Duck()) == {"quack": True}
    assert _to_plain_data(Duck()) == {"quack": True}
