"""Ebbinghaus plugin store_backend selection: hakua-memory and builtin fallback."""

from __future__ import annotations

import json
import logging
import sys
from pathlib import Path

import pytest

_repo_root = str(Path(__file__).resolve().parents[2])
if _repo_root not in sys.path:
    sys.path.insert(0, _repo_root)

import plugins.memory.ebbinghaus as ebbinghaus_plugin  # noqa: E402
from plugins.memory.ebbinghaus import EbbinghausMemoryProvider  # noqa: E402


def _remember_and_recall(provider: EbbinghausMemoryProvider) -> list[dict]:
    remembered = json.loads(
        provider.handle_tool_call(
            "ebbinghaus_memory",
            {
                "action": "remember",
                "content": "The user prefers uv for Python dependency management.",
                "tags": "tooling,python",
                "salience": 0.9,
            },
        )
    )
    assert remembered.get("memory_id") is not None, remembered
    recalled = json.loads(
        provider.handle_tool_call(
            "ebbinghaus_memory",
            {"action": "recall", "query": "Python dependency management uv"},
        )
    )
    return recalled["results"]


def test_default_backend_is_builtin(tmp_path):
    provider = EbbinghausMemoryProvider({"db_path": str(tmp_path / "memory.db")})
    provider.initialize("session-1", hermes_home=str(tmp_path))
    try:
        assert provider.store_backend == "builtin"
        assert type(provider._store).__module__.startswith("plugins.memory.ebbinghaus")  # noqa: SLF001
        assert _remember_and_recall(provider)
    finally:
        provider.shutdown()


def test_hakua_backend_uses_hakua_memory_store(tmp_path, monkeypatch):
    pytest.importorskip("hakua_memory.ebbinghaus.store")
    ensured: list[str] = []
    monkeypatch.setattr(
        "tools.lazy_deps.ensure",
        lambda feature, prompt=True: ensured.append(feature),
    )
    db_path = tmp_path / "memory.db"

    provider = EbbinghausMemoryProvider({"db_path": str(db_path), "store_backend": "hakua"})
    provider.initialize("session-1", hermes_home=str(tmp_path))
    try:
        assert ensured == ["memory.hakua"]
        assert provider.store_backend == "hakua"
        assert type(provider._store).__module__.startswith("hakua_memory.")  # noqa: SLF001
        results = _remember_and_recall(provider)
        assert any("uv" in item["content"] for item in results)
    finally:
        provider.shutdown()

    # Shared schema: the builtin store reads what the hakua store wrote.
    builtin = EbbinghausMemoryProvider({"db_path": str(db_path)})
    builtin.initialize("session-2", hermes_home=str(tmp_path))
    try:
        assert builtin.store_backend == "builtin"
        listed = json.loads(builtin.handle_tool_call("ebbinghaus_memory", {"action": "list"}))
        assert any("uv" in item["content"] for item in listed["memories"])
    finally:
        builtin.shutdown()


def test_hakua_backend_falls_back_to_builtin_when_unavailable(tmp_path, monkeypatch, caplog):
    def _unavailable():
        raise ImportError("No module named 'hakua_memory'")

    monkeypatch.setattr(ebbinghaus_plugin, "_load_hakua_store_backend", _unavailable)
    provider = EbbinghausMemoryProvider(
        {"db_path": str(tmp_path / "memory.db"), "store_backend": "hakua"}
    )
    with caplog.at_level(logging.WARNING, logger="plugins.memory.ebbinghaus"):
        provider.initialize("session-1", hermes_home=str(tmp_path))
    try:
        assert provider.store_backend == "builtin"
        assert "hakua-memory backend unavailable" in caplog.text
        assert _remember_and_recall(provider)
    finally:
        provider.shutdown()


def test_hakua_backend_falls_back_when_lazy_install_is_refused(tmp_path, monkeypatch):
    from tools.lazy_deps import FeatureUnavailable

    def _refuse(feature, prompt=True):
        raise FeatureUnavailable(feature, ("hakua-memory==0.3.5",), "lazy installs disabled")

    monkeypatch.setattr("tools.lazy_deps.ensure", _refuse)
    provider = EbbinghausMemoryProvider(
        {"db_path": str(tmp_path / "memory.db"), "store_backend": "hakua"}
    )
    provider.initialize("session-1", hermes_home=str(tmp_path))
    try:
        assert provider.store_backend == "builtin"
        assert _remember_and_recall(provider)
    finally:
        provider.shutdown()


def test_unknown_backend_uses_builtin(tmp_path):
    provider = EbbinghausMemoryProvider(
        {"db_path": str(tmp_path / "memory.db"), "store_backend": "nonexistent"}
    )
    provider.initialize("session-1", hermes_home=str(tmp_path))
    try:
        assert provider.store_backend == "builtin"
    finally:
        provider.shutdown()


def test_config_schema_offers_store_backend_choices():
    schema = {item["key"]: item for item in EbbinghausMemoryProvider({}).get_config_schema()}
    assert schema["store_backend"]["default"] == "builtin"
    assert set(schema["store_backend"]["choices"]) == set(ebbinghaus_plugin.STORE_BACKENDS)
