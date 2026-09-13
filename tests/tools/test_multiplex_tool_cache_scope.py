"""Multiplexed gateway: module-level tool caches must not hand profile A's value to B.

Downstream COMPOSE of upstream 4b8c01 (SR-20260913-004e subset: camofox VNC memo +
tirith path cache). Full upstream suite (aux semaphore, image token cost, MCP lock)
remains tracked as remaining.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from agent.secret_scope import build_profile_secret_scope, reset_secret_scope, set_secret_scope
from hermes_constants import reset_hermes_home_override, set_hermes_home_override


def _make_home(root: Path, cfg: dict, env: str = "") -> Path:
    root.mkdir(parents=True, exist_ok=True)
    (root / "config.yaml").write_text(yaml.safe_dump(cfg), encoding="utf-8")
    (root / ".env").write_text(env, encoding="utf-8")
    (root / "cache").mkdir(exist_ok=True)
    return root


class _scoped:
    def __init__(self, home: Path):
        self.home = home

    def __enter__(self):
        self._t1 = set_hermes_home_override(str(self.home))
        self._t2 = set_secret_scope(build_profile_secret_scope(self.home))

    def __exit__(self, *_):
        reset_secret_scope(self._t2)
        reset_hermes_home_override(self._t1)


@pytest.fixture
def two_homes(tmp_path, monkeypatch):
    a = _make_home(tmp_path / "A", {}, "CAMOFOX_URL=http://camofox-a:9377\n")
    b = _make_home(tmp_path / "A" / "profiles" / "B", {}, "CAMOFOX_URL=http://camofox-b:9377\n")
    monkeypatch.setenv("HERMES_HOME", str(a))
    monkeypatch.delenv("CAMOFOX_URL", raising=False)
    return a, b


def test_camofox_vnc_memo_is_keyed_by_the_profiles_server_url(two_homes, monkeypatch):
    """The one-shot VNC probe must not answer B with A's server address."""
    import tools.browser_camofox as cam

    class _Resp:
        status_code = 200

        def __init__(self, url):
            self._port = 6001 if "camofox-a" in url else 6002

        def json(self):
            return {"ok": True, "vncPort": self._port}

    monkeypatch.setattr(cam.requests, "get", lambda url, *a, **k: _Resp(url))
    a, b = two_homes
    with _scoped(a):
        assert cam.check_camofox_available() is True
        assert cam.get_vnc_url() == "http://camofox-a:6001"
    with _scoped(b):
        assert cam.get_vnc_url() == "http://camofox-b:6002"
    with _scoped(a):
        assert cam.get_vnc_url() == "http://camofox-a:6001"


def test_tirith_resolved_path_is_keyed_by_profile_home(tmp_path, monkeypatch):
    bin_a, bin_b = tmp_path / "binA" / "tirith", tmp_path / "binB" / "tirith"
    for p in (bin_a, bin_b):
        p.parent.mkdir(parents=True)
        p.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    a = _make_home(tmp_path / "A", {"security": {"tirith_path": str(bin_a)}})
    b = _make_home(tmp_path / "A" / "profiles" / "B", {"security": {"tirith_path": str(bin_b)}})
    monkeypatch.setenv("HERMES_HOME", str(a))

    import tools.tirith_security as tir

    monkeypatch.setattr(tir, "_resolved_path", None)
    monkeypatch.setattr(tir, "_resolved_path_by_home", {})
    monkeypatch.setattr(tir, "is_platform_supported", lambda: True)

    with _scoped(a):
        path_a = tir._resolve_tirith_path(str(bin_a))
    with _scoped(b):
        path_b = tir._resolve_tirith_path(str(bin_b))
    with _scoped(a):
        path_a2 = tir._resolve_tirith_path(str(bin_a))

    assert Path(path_a).resolve() == bin_a.resolve()
    assert Path(path_b).resolve() == bin_b.resolve()
    assert Path(path_a2).resolve() == bin_a.resolve()
