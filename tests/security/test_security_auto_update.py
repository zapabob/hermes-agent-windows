from __future__ import annotations

import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

from downstream.security.store import SecurityStore
from downstream.security.updates import (
    DEFAULT_AUTO_UPDATE_INTERVAL_HOURS,
    is_auto_update_due,
    last_ok_update_time,
    maybe_auto_update,
    maybe_auto_update_all_profiles,
    sync_bundled_yara_rules,
)


def _store(tmp_path: Path) -> SecurityStore:
    return SecurityStore(tmp_path / "security")


def _config(enabled: bool = True, interval_hours: float = 24) -> dict:
    return {"security": {"malware": {"auto_update_enabled": enabled, "auto_update_interval_hours": interval_hours, "update_timeout": 300}}}


def test_defaults_are_daily_and_enabled() -> None:
    assert DEFAULT_AUTO_UPDATE_INTERVAL_HOURS == 24


def test_config_defaults_contain_auto_update_keys() -> None:
    from hermes_cli.config_defaults import DEFAULT_CONFIG

    malware = DEFAULT_CONFIG["security"]["malware"]
    assert malware["auto_update_enabled"] is True
    assert malware["auto_update_interval_hours"] == 24


def test_no_ok_feed_is_due(tmp_path: Path) -> None:
    store = _store(tmp_path)
    assert last_ok_update_time(store) is None
    assert is_auto_update_due(store, 24) is True


def test_recent_ok_feed_is_not_due(tmp_path: Path) -> None:
    store = _store(tmp_path)
    store.upsert_feed("clamav", "v1", "ok", {})
    assert is_auto_update_due(store, 24) is False


def test_old_ok_feed_is_due(tmp_path: Path) -> None:
    store = _store(tmp_path)
    store.upsert_feed("clamav", "v1", "ok", {})
    with store.connection() as con:
        old = (datetime.now(timezone.utc) - timedelta(hours=25)).isoformat()
        con.execute("UPDATE feed_state SET updated_at=? WHERE name='clamav'", (old,))
    assert is_auto_update_due(store, 24) is True


def test_invalid_interval_is_not_due(tmp_path: Path) -> None:
    store = _store(tmp_path)
    assert is_auto_update_due(store, 0) is False
    assert is_auto_update_due(store, -1) is False
    assert is_auto_update_due(store, "bad") is False  # type: ignore[arg-type]


def test_maybe_auto_update_respects_disabled(tmp_path: Path) -> None:
    store = _store(tmp_path)
    result = maybe_auto_update(store, _config(enabled=False))
    assert result == {"ok": True, "skipped": "disabled"}


def test_maybe_auto_update_skips_when_not_due(tmp_path: Path) -> None:
    store = _store(tmp_path)
    store.upsert_feed("clamav", "v1", "ok", {})
    result = maybe_auto_update(store, _config())
    assert result == {"ok": True, "skipped": "not-due"}


def test_maybe_auto_update_skips_read_only(tmp_path: Path) -> None:
    store = _store(tmp_path)
    readonly = SecurityStore(store.root, read_only=False)
    # create state first, then open read-only view
    readonly.upsert_feed("clamav", "v1", "error", {})
    ro_view = SecurityStore(store.root, read_only=True)
    result = maybe_auto_update(ro_view, _config(), force=True)
    assert result == {"ok": True, "skipped": "read-only"}


def test_maybe_auto_update_runs_clamav_and_yara_when_due(tmp_path: Path) -> None:
    store = _store(tmp_path)
    with patch("downstream.security.updates.DefinitionUpdater") as updater_cls:
        updater_cls.return_value.update_clamav.return_value = {"ok": True, "state": "ok", "version": "v2"}
        result = maybe_auto_update(store, _config())
    assert result["ok"] is True
    assert result["clamav"]["state"] == "ok"
    assert result["yara"]["ok"] is True
    assert "yara" in store.feed_versions()
    # lock released
    assert not (store.root / "feeds" / "clamav" / ".auto-update.lock").exists()


def test_maybe_auto_update_never_raises_on_engine_failure(tmp_path: Path) -> None:
    store = _store(tmp_path)
    with patch("downstream.security.updates.DefinitionUpdater") as updater_cls:
        updater_cls.return_value.update_clamav.side_effect = RuntimeError("boom")
        result = maybe_auto_update(store, _config())
    assert result["ok"] is False
    assert "boom" in result["error"]


def test_concurrent_auto_update_is_suppressed_by_lock(tmp_path: Path) -> None:
    store = _store(tmp_path)
    lock = store.root / "feeds" / "clamav" / ".auto-update.lock"
    lock.parent.mkdir(parents=True, exist_ok=True)
    lock.write_text("1234", encoding="utf-8")
    result = maybe_auto_update(store, _config(), force=True)
    assert result == {"ok": True, "skipped": "locked"}


def test_stale_lock_is_recovered(tmp_path: Path) -> None:
    store = _store(tmp_path)
    lock = store.root / "feeds" / "clamav" / ".auto-update.lock"
    lock.parent.mkdir(parents=True, exist_ok=True)
    lock.write_text("99999", encoding="utf-8")
    old = time.time() - 7200.0
    import os

    os.utime(lock, (old, old))
    with patch("downstream.security.updates.DefinitionUpdater") as updater_cls:
        updater_cls.return_value.update_clamav.return_value = {"ok": True, "state": "ok"}
        result = maybe_auto_update(store, _config(), force=True)
    assert result["ok"] is True


def test_sync_bundled_yara_rules_records_feed(tmp_path: Path) -> None:
    store = _store(tmp_path)
    result = sync_bundled_yara_rules(store)
    assert result["ok"] is True
    assert store.feed_versions()["yara"] == result["version"]
    assert (store.root / "feeds" / "yara").is_dir()


def test_maybe_auto_update_all_profiles_skips_empty_profiles(tmp_path: Path, monkeypatch) -> None:
    from downstream.security import updates as updates_mod

    homes = {"default": tmp_path / "default", "empty": tmp_path / "profiles" / "empty"}
    homes["default"].mkdir(parents=True)
    (homes["default"] / "security").mkdir(parents=True)
    homes["empty"].mkdir(parents=True)

    monkeypatch.setattr(updates_mod, "maybe_auto_update", lambda store, config=None, force=False: {"ok": True, "skipped": "not-due"})

    import hermes_cli.profiles as profiles

    monkeypatch.setattr(profiles, "list_profile_names", lambda: ["default", "empty"])
    monkeypatch.setattr(profiles, "get_profile_dir", lambda name: homes[name])

    results = maybe_auto_update_all_profiles({})
    by_profile = {r["profile"]: r for r in results}
    assert by_profile["default"]["skipped"] == "not-due"
    assert by_profile["empty"]["skipped"] == "no-security-state"
