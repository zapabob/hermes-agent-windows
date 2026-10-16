"""Route-scoped prompt progress and measured reading budgets for local streams."""
from __future__ import annotations

import contextlib
import contextvars
import logging
import math
from typing import Any, Callable

logger = logging.getLogger(__name__)


class LocalPromptProgress:
    """Attempt-local high-water mark for progress-only local stream frames."""

    def __init__(self) -> None:
        self.processed = 0

    @staticmethod
    def metadata_only(chunk: Any) -> bool:
        """Usage/heartbeat metadata is not forward work; output/errors are."""
        def field(value: Any, name: str) -> Any:
            return value.get(name) if isinstance(value, dict) else getattr(value, name, None)

        if field(chunk, "error_type") or field(chunk, "error_message"):
            return False
        for choice in field(chunk, "choices") or []:
            if field(choice, "finish_reason"):
                return False
            delta = field(choice, "delta")
            if any(field(delta, name) for name in (
                "content", "tool_calls", "reasoning_content", "reasoning", "refusal",
            )):
                return False
        return True

    @staticmethod
    def payload(chunk: Any) -> dict[str, Any]:
        extra = chunk if isinstance(chunk, dict) else getattr(chunk, "model_extra", None)
        progress = extra.get("prompt_progress") if isinstance(extra, dict) else None
        return progress if isinstance(progress, dict) else {}

    def advance(self, chunk: Any) -> bool:
        """Only a strictly increasing valid token count buys more idle time."""
        progress = self.payload(chunk)
        processed, total = progress.get("processed"), progress.get("total")
        if not isinstance(processed, int) or isinstance(processed, bool) or processed <= self.processed:
            return False
        if total is not None and (
            not isinstance(total, int) or isinstance(total, bool) or total < processed
        ):
            return False
        self.processed = processed
        return True


class PromptReadingClock(LocalPromptProgress):
    """Credit only measured forward reading, capped by observed caller time."""

    def __init__(self, started: float) -> None:
        super().__init__()
        self._mark = started
        self._server_ms = 0.0
        self.seconds = 0.0
        self._credit, self._deadline = _reading_budget.get()

    def deadline_monotonic(self) -> float | None:
        """Read the captured attempt's budget, never a later task's scope."""
        return self._deadline() if self._deadline is not None else None

    def tick(self, chunk: Any, now: float) -> bool:
        interval = max(0.0, now - self._mark)
        self._mark = max(now, self._mark)
        if not self.advance(chunk):
            return False
        elapsed_ms = self.payload(chunk).get("time_ms")
        # A count proves liveness, but without measured duration it does not
        # prove how much of an initial queue/load delay was prompt reading.
        if (isinstance(elapsed_ms, (int, float)) and not isinstance(elapsed_ms, bool)
                and math.isfinite(elapsed_ms) and elapsed_ms >= self._server_ms):
            spent = min(interval, (elapsed_ms - self._server_ms) / 1000)
            self._server_ms = float(elapsed_ms)
            self.seconds += spent
            hook = self._credit
            if spent > 0 and hook is not None:
                hook(spent)
        return True


_reading_budget: contextvars.ContextVar[tuple[
    Callable[[float], Any] | None, Callable[[], float | None] | None,
]] = contextvars.ContextVar("prompt_reading_budget", default=(None, None))


@contextlib.contextmanager
def prompt_reading_budget(
    extend: Callable[[float], Any] | None,
    deadline: Callable[[], float | None] | None,
):
    """Bind the original attempt fence across async tasks and copied threads."""
    token = _reading_budget.set((extend, deadline))
    try:
        yield
    finally:
        _reading_budget.reset(token)


def with_prompt_progress(kwargs: dict[str, Any], base_url: str) -> dict[str, Any]:
    """Add the extension only for an explicitly capable exact route/model."""
    extra = kwargs.get("extra_body")
    if extra is not None and not isinstance(extra, dict):
        return kwargs
    if isinstance(extra, dict) and "return_progress" in extra:
        return kwargs
    model = kwargs.get("model")
    if not isinstance(model, str) or not model or not base_url:
        return kwargs
    from hermes_cli.config import get_custom_provider_model_capability

    try:
        capable = get_custom_provider_model_capability(model, base_url, "prompt_progress")
    except Exception as exc:
        logger.debug("Prompt progress capability unavailable (%s)", type(exc).__name__)
        return kwargs
    if capable is not True:
        return kwargs
    merged = dict(extra) if isinstance(extra, dict) else {}
    merged["return_progress"] = True
    return {**kwargs, "extra_body": merged}


def tracks_prompt_progress(base_url: str, kwargs: dict[str, Any]) -> bool:
    """Unknown remote endpoints retain their existing event accounting."""
    from agent.model_metadata import is_local_endpoint

    extra = kwargs.get("extra_body")
    return bool((base_url and is_local_endpoint(base_url)) or (
        isinstance(extra, dict) and extra.get("return_progress") is True
    ))
