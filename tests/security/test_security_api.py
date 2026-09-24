from __future__ import annotations

import asyncio
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi.routing import APIRoute
from fastapi.testclient import TestClient

from hermes_cli import web_server


def test_security_routes_are_registered() -> None:
    routes = {
        (method, route.path)
        for route in web_server.app.routes
        if isinstance(route, APIRoute)
        for method in route.methods
    }
    assert ("GET", "/api/security/status") in routes
    assert ("POST", "/api/security/scan") in routes
    assert ("POST", "/api/security/update") in routes
    assert ("DELETE", "/api/security/quarantine/{item_id}") in routes


def test_all_security_routes_accept_profile_and_remain_authenticated() -> None:
    from hermes_cli.dashboard_auth.public_paths import PUBLIC_API_PATHS

    security_routes = [
        route
        for route in web_server.app.routes
        if isinstance(route, APIRoute) and route.path.startswith("/api/security/")
    ]

    assert security_routes
    assert all(
        "profile" in {parameter.name for parameter in route.dependant.query_params}
        for route in security_routes
    )
    assert not any(path.startswith("/api/security/") for path in PUBLIC_API_PATHS)


def test_security_status_rejects_unauthenticated_http_request(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(web_server.app.state, "auth_required", False, raising=False)
    monkeypatch.setattr(web_server.app.state, "bound_host", None, raising=False)
    monkeypatch.setattr(
        web_server,
        "_security_service",
        lambda **kwargs: pytest.fail("unauthenticated request reached Security Center"),
    )

    response = TestClient(web_server.app).get("/api/security/status")

    assert response.status_code == 401


def test_backend_startup_runs_one_shot_security_watch_resume(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from downstream.security import cli as security_cli

    resume = SimpleNamespace(calls=0)

    def _resume() -> list[dict[str, object]]:
        resume.calls += 1
        return [{"profile": "default", "ok": True, "enabled": False, "pid": None, "running": False}]

    monkeypatch.setattr(security_cli, "resume_all_profile_watches", _resume)

    web_server._resume_security_watch_on_startup()

    assert resume.calls == 1


def test_scan_with_quarantine_requires_explicit_confirmation() -> None:
    body = web_server.SecurityScanRequest(scope="quick", quarantine=True, confirmed=False)
    with pytest.raises(web_server.HTTPException) as caught:
        asyncio.run(web_server.security_scan(body))
    assert caught.value.status_code == 409


def test_feed_update_requires_explicit_confirmation() -> None:
    body = web_server.SecurityMutationRequest(confirmed=False)
    with pytest.raises(web_server.HTTPException) as caught:
        asyncio.run(web_server.security_update(body))
    assert caught.value.status_code == 409


def test_watch_mutation_requires_explicit_confirmation() -> None:
    body = web_server.SecurityWatchRequest(action="disable", confirmed=False)
    with pytest.raises(web_server.HTTPException) as caught:
        asyncio.run(web_server.security_watch(body))
    assert caught.value.status_code == 409


def test_security_status_uses_requested_profile(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    requested_home = tmp_path / "profiles" / "research"
    requested_home.mkdir(parents=True)
    observed: list[Path] = []

    monkeypatch.setattr(web_server, "_resolve_profile_dir", lambda name: requested_home)

    class FakeService:
        def __init__(self, read_only: bool = False) -> None:
            from hermes_constants import get_hermes_home

            assert read_only is True
            observed.append(get_hermes_home())

        def status(self) -> dict[str, object]:
            return {"profile_home": str(observed[-1])}

    monkeypatch.setitem(__import__("sys").modules, "downstream.security.service", SimpleNamespace(SecurityService=FakeService))

    result = asyncio.run(web_server.security_status(profile="research"))

    assert observed == [requested_home]
    assert result == {"profile_home": str(requested_home)}


def test_security_gets_do_not_materialize_named_profile_state(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    requested_home = tmp_path / "profiles" / "research"
    requested_home.mkdir(parents=True)
    monkeypatch.setattr(web_server, "_resolve_profile_dir", lambda name: requested_home)

    status = asyncio.run(web_server.security_status(profile="research"))
    quarantine = asyncio.run(web_server.security_quarantine_list(profile="research"))

    assert status["summary"]["files_scanned"] == 0
    assert quarantine == {"items": []}
    assert not (requested_home / "security").exists()


def test_security_status_does_not_create_vault_for_existing_profile_state(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    from downstream.security.store import SecurityStore

    requested_home = tmp_path / "profiles" / "research"
    requested_home.mkdir(parents=True)
    root = requested_home / "security"
    SecurityStore(root)
    monkeypatch.setattr(web_server, "_resolve_profile_dir", lambda _name: requested_home)

    status = asyncio.run(web_server.security_status(profile="research"))

    assert status["summary"]["files_scanned"] == 0
    assert not (root / "quarantine").exists()
    assert not (root / "vault-key.dpapi").exists()


def test_security_status_rejects_invalid_profile_before_service_creation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    created = False

    def _unexpected_service(*, read_only: bool = False):
        nonlocal created
        created = True
        raise AssertionError("service must not be created")

    monkeypatch.setattr(web_server, "_security_service", _unexpected_service)

    with pytest.raises(web_server.HTTPException) as caught:
        asyncio.run(web_server.security_status(profile="../escape"))

    assert caught.value.status_code == 400
    assert created is False


def test_security_quarantine_delete_uses_requested_profile(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    requested_home = tmp_path / "profiles" / "research"
    requested_home.mkdir(parents=True)
    observed: list[tuple[Path, str]] = []

    monkeypatch.setattr(web_server, "_resolve_profile_dir", lambda name: requested_home)

    class FakeVault:
        def delete(self, item_id: str) -> None:
            from hermes_constants import get_hermes_home

            observed.append((get_hermes_home(), item_id))

    class FakeService:
        vault = FakeVault()

        def __init__(self, read_only: bool = False) -> None:
            assert read_only is False

    monkeypatch.setitem(__import__("sys").modules, "downstream.security.service", SimpleNamespace(SecurityService=FakeService))

    result = asyncio.run(
        web_server.security_quarantine_delete("item-7", confirmed=True, profile="research")
    )

    assert observed == [(requested_home, "item-7")]
    assert result == {"ok": True, "id": "item-7", "deleted": True}
