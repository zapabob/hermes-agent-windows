"""Web Access routes: Desktop's Web Access pane turns the gateway-served Webapp on and off here.

Thin HTTP over :mod:`hermes_cli.webapp_access`. Adapted for this worktree's single-arg
``late()`` / ``web_server``-owned ``_profile_scope`` (upstream's ``web_server_profiles``
module is not fully closed here). Native Desktop on this computer only
(``native_http_principal``).
"""

from __future__ import annotations

import asyncio
import contextlib
import threading
from contextlib import asynccontextmanager
from typing import Any, Callable, Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel

from hermes_cli import webapp_access
from hermes_cli.web_deps import LateState, late

_restart_gateway_after = late("_restart_gateway_after", "hermes_cli.web_server_gateway")
_gateway_restart_failure = late("gateway_restart_failure", "hermes_cli.web_server_gateway")
_profile_scope = late("_profile_scope")
_config_profile_scope = late("_config_profile_scope")
_CONFIG_MUTATION_LOCK = LateState("_CONFIG_MUTATION_LOCK")

_CHANGE_LOCK = threading.Lock()
_CHANGE_POLL_SECONDS = 0.05


def owner_on_this_machine(request: Request) -> None:
    """Only the Hermes app on this computer may change Web Access.

    Upstream admits a ``native_http_principal`` (gateway private ticket). Until that
    stack is closed here, also admit loopback requests that carry no browser
    ``Origin`` — a normal browser tab cannot forge both at once over the Desktop's
    local backend.
    """
    if getattr(request.state, "native_http_principal", None):
        return
    client = request.client
    host = (client.host if client else "") or ""
    loopback = host in {"127.0.0.1", "::1", "localhost"} or host.startswith("127.")
    origin = (request.headers.get("origin") or "").strip()
    if loopback and not origin:
        return
    raise HTTPException(
        status_code=403,
        detail="Web Access can only be changed from the Hermes app on this computer.",
    )


router = APIRouter(dependencies=[Depends(owner_on_this_machine)])


class StartBody(BaseModel):
    mode: str
    public_url: Optional[str] = None


def destructive_profile(profile: Optional[str], route: str) -> Optional[str]:
    """Require an explicit profile when this backend hosts more than one."""
    if (profile or "").strip():
        return profile
    try:
        from agent.secret_scope import is_multiplex_active
    except Exception:
        return profile
    if is_multiplex_active():
        raise HTTPException(
            status_code=400,
            detail=(
                f"{route} requires an explicit profile: this backend serves several "
                "profiles, so an unnamed target would act on the wrong profile's data."
            ),
        )
    return profile


@contextlib.contextmanager
def config_write_scope(profile: Optional[str]):
    with _profile_scope(profile):
        with _CONFIG_MUTATION_LOCK:
            yield


@contextlib.contextmanager
def _gateway_scope(profile: Optional[str], *, config_write: bool):
    try:
        from hermes_constants import profile_name_for_home
    except ImportError:  # pragma: no cover - older trees without the helper
        profile_name_for_home = lambda _path: None  # type: ignore[assignment]

    with _profile_scope(profile):
        name = profile_name_for_home(webapp_access.gateway_home()) or profile
    with config_write_scope(name) if config_write else _profile_scope(name):
        yield name


async def _scoped(
    profile: Optional[str],
    fn: Callable[[Optional[str]], Any],
    *,
    config_write: bool = False,
) -> Any:
    def _run():
        with _gateway_scope(profile, config_write=config_write) as gateway_profile:
            return fn(gateway_profile)

    try:
        return await asyncio.to_thread(_run)
    except webapp_access.WebappAccessError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


async def config_scoped_to_thread(profile: Optional[str], fn: Callable[[], Any]) -> Any:
    def _run():
        with _config_profile_scope(profile):
            return fn()

    return await asyncio.to_thread(_run)


async def _in_gateway_home(gateway: Optional[str], fn: Callable[[], Any]) -> Any:
    try:
        return await config_scoped_to_thread(gateway, fn)
    except webapp_access.WebappAccessError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@asynccontextmanager
async def _one_change_at_a_time():
    while not _CHANGE_LOCK.acquire(blocking=False):
        await asyncio.sleep(_CHANGE_POLL_SECONDS)
    try:
        yield
    finally:
        _CHANGE_LOCK.release()


async def _restart(gateway: Optional[str], what: str) -> dict:
    restart = await asyncio.to_thread(
        _restart_gateway_after, gateway, what=what, label="Web Access"
    )
    return {**await _in_gateway_home(gateway, webapp_access.access_status), **restart}


@router.get("/api/webapp-access/status")
async def webapp_access_status(profile: Optional[str] = None):
    return await _scoped(
        profile,
        lambda gateway: {
            **webapp_access.access_status(),
            "restart_failure": _gateway_restart_failure(gateway),
        },
    )


@router.post("/api/webapp-access/start")
async def start_webapp_access(body: StartBody, profile: Optional[str] = None):
    profile = destructive_profile(profile, "POST /api/webapp-access/start")
    async with _one_change_at_a_time():
        gateway, (host, port, public_url, callback) = await _scoped(
            profile,
            lambda gateway: (gateway, webapp_access.plan(body.mode, body.public_url)),
            config_write=True,
        )
        await _in_gateway_home(gateway, webapp_access.build_bundle)
        await _in_gateway_home(gateway, lambda: webapp_access.register(callback))
        await _scoped(
            profile,
            lambda _gateway: webapp_access.serve(host, public_url, port),
            config_write=True,
        )
        return await _restart(gateway, "turning on Web Access")


@router.post("/api/webapp-access/stop")
async def stop_webapp_access(profile: Optional[str] = None):
    profile = destructive_profile(profile, "POST /api/webapp-access/stop")

    def _stop(gateway):
        webapp_access.turn_off()
        return gateway

    async with _one_change_at_a_time():
        return await _restart(
            await _scoped(profile, _stop, config_write=True), "turning off Web Access"
        )


@router.post("/api/webapp-access/restart")
async def restart_webapp_access(profile: Optional[str] = None):
    profile = destructive_profile(profile, "POST /api/webapp-access/restart")
    async with _one_change_at_a_time():
        return await _restart(
            await _scoped(profile, lambda gateway: gateway), "applying Web Access"
        )
