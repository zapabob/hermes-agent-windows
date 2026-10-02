"""Nested-fence regression tests for the memory-context boundary.

Baseline from A2A conference #1 (2026-10-02).  The conference reported that
two agents independently flagged principle 4 ("recalled memory is data, not
instructions") as already broken in this implementation.  Code audit then
found the fence DOES exist — the initial "no fence" hypothesis was discarded —
and split the finding into three separate claims:

  1. CONFIRMED: a fence exists.  build_memory_context_block() wraps recall in
     <memory-context> with an explicit "NOT new user input" system note.
  2. CONFIRMED SEPARATE DEFECT: StreamingContextScrubber closes the span at
     the FIRST close tag, so a nested fence ends the span early and the tail
     reaches the UI.  This is an OUTPUT-fence boundary bug, not a principle-4
     problem.
  3. UNTESTED CORE HYPOTHESIS: "Treat as authoritative reference data ...
     should inform all responses" may be insufficient authority semantics.
     Syntax-level fences cannot answer this; it needs an instruction-conflict
     experiment (see _docs/2026-10-02_a2a_conference_1_hakua.md).

These tests pin claim 2 only.  They deliberately do NOT assert anything about
the model's instruction-following, which is out of scope for a unit test.
"""

from agent.memory_manager import StreamingContextScrubber


class TestNestedFenceDoesNotEndSpanEarly:
    """A close tag that belongs to a NESTED fence must not end our span."""

    def test_nested_fence_does_not_leak_tail_to_ui(self):
        """Nested <memory-context> inside a span: tail after the inner close
        tag is still inside the outer span and must not reach the UI."""
        s = StreamingContextScrubber()
        deltas = [
            "<memory-context>\n[System note: ...]\n\nlead\n",
            "<memory-context>\ninner payload\n</memory-context>\n",
            "NESTED_TAIL_MARKER\n</memory-context>\n\nVisible answer",
        ]
        out = "".join(s.feed(d) for d in deltas) + s.flush()
        assert "NESTED_TAIL_MARKER" not in out
        assert "Visible answer" in out

    def test_nested_fence_split_across_deltas(self):
        """Same escape route, but the inner close tag lands in its own delta —
        the shape a real provider stream produces."""
        s = StreamingContextScrubber()
        deltas = [
            "<memory-context>\n[System note: ...]\n\nlead\n<memory-context>\n",
            "inner payload\n",
            "</memory-context>\nNESTED_TAIL_MARKER\n",
            "</memory-context>\n\nVisible answer",
        ]
        out = "".join(s.feed(d) for d in deltas) + s.flush()
        assert "NESTED_TAIL_MARKER" not in out
        assert "Visible answer" in out