"""Minimal Webapp listener bring-up for the ordinary gateway process.

Owns only the Webapp fixed-port attempt + private-listener fallback. Session
authority / bot-mailbox recovery from the upstream ``run_runtime`` split stays
out of scope (not required for Desktop Web access → browser Desktop).
"""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)


async def start_gateway_runtime_api(runner) -> None:
    """Bind the gateway HTTP/WS listener; prefer the Webapp port when configured."""
    from gateway import run_api
    from gateway.webapp_listener import (
        STARTING,
        BrowserCredentialError,
        browser_session_token,
        dial_origin,
        listener_plan,
        register_control_verbs,
    )
    from hermes_constants import get_hermes_home

    home = get_hermes_home()
    register_control_verbs(runner, home)
    host, port, webapp, unusable = listener_plan(home)
    runner.webapp_status = (
        {"state": "unavailable", "url": None, "reason": unusable}
        if unusable
        else {"state": "off", "url": None, "reason": None}
        if webapp is None
        else dict(STARTING)
    )
    try:
        runner.session_api = await (
            run_api.start_gateway_api(runner, host=host, port=port, webapp=webapp)
            if webapp is not None
            else run_api.start_gateway_api(runner)
        )
    except (Exception, SystemExit) as exc:
        if webapp is None:
            raise
        if isinstance(exc, SystemExit):
            reason = str(exc.code).strip()
        elif isinstance(exc, BrowserCredentialError):
            reason = str(exc)
        elif isinstance(exc, OSError) and exc.filename:
            reason = f"could not use {exc.filename} ({exc.strerror or exc})"
        else:
            cause = (exc.strerror or exc) if isinstance(exc, OSError) else exc
            reason = f"could not listen on {host}:{port} ({cause})"
        logger.error("Webapp unavailable: %s", reason)
        runner.webapp_status = {"state": "unavailable", "url": None, "reason": reason}
        try:
            browser_session_token(home, rotate=True)
        except OSError as write_error:
            logger.warning("Could not replace the Webapp's browser credential: %s", write_error)
        runner.session_api = await run_api.start_gateway_api(runner)
    else:
        if webapp is not None:
            runner.webapp_status = {
                "state": "serving",
                "url": dial_origin(host, port),
                "reason": None,
            }

    if getattr(runner, "session_runtime_descriptor", None) is None:
        runner.session_runtime_descriptor = {}
    if runner.session_api is not None:
        runner.session_runtime_descriptor["api_origin"] = runner.session_api.api_origin
