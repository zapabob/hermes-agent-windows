"""CLI/GUI plugin update must share scan / disable / consent gates."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest


@pytest.fixture
def plugin_tree(tmp_path: Path) -> Path:
    root = tmp_path / "plugins"
    target = root / "demo"
    target.mkdir(parents=True)
    (target / ".git").mkdir()
    (target / "plugin.yaml").write_text(
        "name: demo\nversion: 0.0.1\n", encoding="utf-8"
    )
    return target


def test_dashboard_update_disables_on_dangerous_scan(plugin_tree: Path, monkeypatch) -> None:
    from hermes_cli import plugins_cmd as pc

    monkeypatch.setattr(pc, "_plugins_dir", lambda: plugin_tree.parent)
    monkeypatch.setattr(pc, "_user_installed_plugin_dir", lambda name: plugin_tree)
    monkeypatch.setattr(pc, "_read_install_metadata", lambda: {})
    monkeypatch.setattr(pc, "_git_pull_plugin_dir", lambda _t: (True, "Updated"))
    monkeypatch.setattr(pc, "_clear_plugin_bytecode", lambda _t: 0)
    monkeypatch.setattr(pc, "_copy_example_files", lambda *_a, **_k: None)
    monkeypatch.setattr(pc, "_read_manifest", lambda _t: {"name": "demo", "capabilities": []})
    monkeypatch.setattr(pc, "_scan_on_install_enabled", lambda: True)

    scan = MagicMock()
    scan.verdict = "dangerous"
    monkeypatch.setattr(
        "tools.plugin_guard.scan_plugin",
        lambda *_a, **_k: scan,
    )
    monkeypatch.setattr(
        "tools.plugin_guard.should_allow_plugin_install",
        lambda *_a, **_k: (False, "dangerous fixture"),
    )
    monkeypatch.setattr(
        "tools.plugin_guard.format_scan_report",
        lambda *_a, **_k: "report",
    )

    enabled: set[str] = {"demo"}
    disabled: set[str] = set()
    monkeypatch.setattr(pc, "_get_enabled_set", lambda: set(enabled))
    monkeypatch.setattr(pc, "_get_disabled_set", lambda: set(disabled))

    def _save_enabled(values):
        enabled.clear()
        enabled.update(values)

    def _save_disabled(values):
        disabled.clear()
        disabled.update(values)

    monkeypatch.setattr(pc, "_save_enabled_set", _save_enabled)
    monkeypatch.setattr(pc, "_save_disabled_set", _save_disabled)

    result = pc.dashboard_update_user_plugin("demo")
    assert result["ok"] is True or result.get("status") == "disabled"
    assert "demo" in disabled
    assert "demo" not in enabled
    assert result.get("status") in {"disabled", "updated", "needs_consent"} or result.get(
        "disabled"
    ) is True


def test_update_core_rejects_pinned_without_pull(plugin_tree: Path, monkeypatch) -> None:
    from hermes_cli import plugins_cmd as pc

    monkeypatch.setattr(pc, "_plugins_dir", lambda: plugin_tree.parent)
    monkeypatch.setattr(pc, "_user_installed_plugin_dir", lambda name: plugin_tree)
    monkeypatch.setattr(
        pc,
        "_read_install_metadata",
        lambda: {"demo": {"pinned": True, "revision": "abc", "source": "x"}},
    )
    pulled = {"n": 0}

    def _pull(_t):
        pulled["n"] += 1
        return True, "Updated"

    monkeypatch.setattr(pc, "_git_pull_plugin_dir", _pull)
    result = pc.update_user_plugin_core("demo", interactive_consent=False)
    assert result.ok is False
    assert result.status == "pinned"
    assert pulled["n"] == 0
