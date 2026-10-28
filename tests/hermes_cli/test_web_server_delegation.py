"""PUT/GET /api/delegation atomic Apply contracts."""

from __future__ import annotations

from pathlib import Path

import pytest


@pytest.fixture
def delegation_client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    try:
        from starlette.testclient import TestClient
    except ImportError:
        pytest.skip("fastapi/starlette not installed")

    home = tmp_path / ".hermes"
    home.mkdir()
    (home / "config.yaml").write_text(
        "delegation:\n  model: old-model\n  max_spawn_depth: 1\n  api_key: secret-disk\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("HERMES_HOME", str(home))
    monkeypatch.setattr(Path, "home", lambda: tmp_path)

    # Import after HERMES_HOME so loaders see the fixture.
    from hermes_cli import web_server

    client = TestClient(web_server.app)
    client.headers[web_server._SESSION_HEADER_NAME] = web_server._SESSION_TOKEN
    return client, home


def test_put_delegation_rejects_invalid_and_keeps_disk(delegation_client) -> None:
    client, home = delegation_client
    before = (home / "config.yaml").read_text(encoding="utf-8")
    res = client.put(
        "/api/delegation",
        json={"delegation": {"max_spawn_depth": 0}},
    )
    assert res.status_code == 400
    assert (home / "config.yaml").read_text(encoding="utf-8") == before


def test_put_delegation_applies_full_draft_and_preserves_secret(delegation_client) -> None:
    client, home = delegation_client
    res = client.put(
        "/api/delegation",
        json={
            "delegation": {
                "provider": "openai",
                "model": "gpt-test",
                "max_spawn_depth": 2,
                "max_concurrent_children": 3,
                "fallback_providers": [],
            }
        },
    )
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["ok"] is True
    assert body["delegation"]["model"] == "gpt-test"
    assert "api_key" not in body["delegation"]
    assert body["schema_affecting_changed"] == ["max_concurrent_children", "max_spawn_depth"]
    assert body["applies_on"] == "new_session"

    disk = (home / "config.yaml").read_text(encoding="utf-8")
    assert "secret-disk" in disk
    assert "gpt-test" in disk


def test_get_delegation_strips_api_key(delegation_client) -> None:
    client, _home = delegation_client
    res = client.get("/api/delegation")
    assert res.status_code == 200
    body = res.json()
    assert body["has_api_key"] is True
    assert "api_key" not in body["delegation"]
