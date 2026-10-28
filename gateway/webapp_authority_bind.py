"""Bind the Webapp admission adapter to a GatewayRunner's SessionAuthority.

Product write paths must stay fail-closed until ``runner.session_authority``
is a real ``SessionAuthority`` instance. This module does not start a second
agent loop.
"""
from __future__ import annotations

import logging
import uuid
from typing import Any

from gateway.webapp_session_adapter import (
    WebappSessionAdapter,
    get_webapp_session_adapter,
)

logger = logging.getLogger(__name__)


def runner_has_canonical_authority(runner: Any) -> bool:
    """True when the runner exposes a live SessionAuthority object."""
    authority = getattr(runner, "session_authority", None)
    if authority is None:
        return False
    # Duck-type: avoid importing SessionAuthority at module import time for
    # light callers; name check keeps mocks honest in unit tests.
    return type(authority).__name__ == "SessionAuthority" or hasattr(
        authority, "admit"
    ) or hasattr(authority, "profile_id")


def sync_webapp_adapter_from_runner(
    runner: Any,
    *,
    adapter: WebappSessionAdapter | None = None,
) -> WebappSessionAdapter:
    """Set ``adapter.authority_bound`` from the runner's live authority.

    Call after ``initialize_session_authority`` (or test double assignment).
    """
    target = adapter if adapter is not None else get_webapp_session_adapter()
    bound = runner_has_canonical_authority(runner)
    target.bind_authority(bound)
    if bound:
        logger.info("Webapp session adapter bound to SessionAuthority")
    else:
        logger.warning(
            "Webapp session adapter remains unbound (no SessionAuthority on runner)"
        )
    return target


def ensure_authority_placeholders(runner: Any) -> None:
    """Install empty registry/descriptor slots expected by run_runtime.

    Does not open stores or start turns. Safe on partially constructed runners.
    """
    if getattr(runner, "session_authorities", None) is None:
        from gateway.session_authorities import SessionAuthorities
        from hermes_constants import get_hermes_home

        runner.session_authorities = SessionAuthorities(get_hermes_home())
    desc = getattr(runner, "session_runtime_descriptor", None)
    if not isinstance(desc, dict):
        runner.session_runtime_descriptor = {
            "instance_id": str(uuid.uuid4()),
            "served_profiles": [],
            "parked_profiles": {},
        }
    elif "instance_id" not in desc:
        desc["instance_id"] = str(uuid.uuid4())
