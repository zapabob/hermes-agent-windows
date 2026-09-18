from __future__ import annotations

import logging
import os
import shutil
import subprocess
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .models import EngineState
from .store import SecurityStore

logger = logging.getLogger(__name__)

#:一日一回自動更新の既定間隔(時間)。起動時チェックで最終ok更新から
#:この時間を経過していたら自動更新を実行する。
DEFAULT_AUTO_UPDATE_INTERVAL_HOURS = 24

#:同時freshclam実行を抑止するロックファイル名(プロファイル毎)。
AUTO_UPDATE_LOCK_NAME = ".auto-update.lock"

#:ロックを stale とみなす秒数(前回実行がクラッシュしても次回起動で回復)。
AUTO_UPDATE_LOCK_STALE_SECONDS = 3600.0


class DefinitionUpdater:
    def __init__(self, store: SecurityStore, timeout: int = 300) -> None:
        self.store = store
        self.timeout = max(30, timeout)
        self.root = store.root / "feeds" / "clamav"
        self.root.mkdir(parents=True, exist_ok=True)

    def _validate(self, candidate: Path) -> tuple[bool, str]:
        databases = sorted(candidate.glob("*.cvd")) + sorted(candidate.glob("*.cld"))
        if not databases or any(path.stat().st_size < 512 for path in databases):
            return False, "freshclam produced no valid CVD/CLD database"
        sigtool = shutil.which("sigtool")
        if sigtool:
            for database in databases:
                result = subprocess.run(
                    [sigtool, "--info", str(database)], capture_output=True, text=True,
                    encoding="utf-8", errors="replace", timeout=30, check=False,
                    stdin=subprocess.DEVNULL,
                )
                if result.returncode != 0:
                    return False, f"sigtool rejected {database.name}"
        return True, f"{len(databases)} databases validated"

    def _activate(self, staging: Path) -> None:
        current = self.root / "current"
        previous = self.root / "previous"
        discard = self.root / f".previous-{uuid.uuid4().hex}"
        moved_current = False
        if previous.exists():
            os.replace(previous, discard)
        try:
            if current.exists():
                os.replace(current, previous)
                moved_current = True
            os.replace(staging, current)
        except Exception:
            if moved_current and previous.exists() and not current.exists():
                os.replace(previous, current)
            if discard.exists() and not previous.exists():
                os.replace(discard, previous)
            raise
        if discard.exists():
            shutil.rmtree(discard)

    def update_clamav(self) -> dict[str, Any]:
        freshclam = shutil.which("freshclam")
        if not freshclam:
            self.store.upsert_feed("clamav", EngineState.SCANNER_UNAVAILABLE.value, "error", {"error": "freshclam unavailable"})
            return {"ok": False, "state": EngineState.SCANNER_UNAVAILABLE.value, "error": "freshclam unavailable"}
        staging = self.root / f".staging-{uuid.uuid4().hex}"
        staging.mkdir()
        try:
            result = subprocess.run(
                [freshclam, f"--datadir={staging}"], capture_output=True, text=True,
                encoding="utf-8", errors="replace", timeout=self.timeout, check=False,
                stdin=subprocess.DEVNULL,
            )
        except subprocess.TimeoutExpired:
            shutil.rmtree(staging, ignore_errors=True)
            self.store.upsert_feed("clamav", EngineState.SCAN_TIMEOUT.value, "error", {"error": "freshclam timeout"})
            return {"ok": False, "state": EngineState.SCAN_TIMEOUT.value, "error": "freshclam timeout"}
        output = "\n".join((result.stdout, result.stderr)).strip()[-2000:]
        if result.returncode != 0:
            shutil.rmtree(staging, ignore_errors=True)
            self.store.upsert_feed("clamav", "update_failed", "error", {"exit_code": result.returncode, "output": output})
            return {"ok": False, "state": "update_failed", "error": output, "exit_code": result.returncode}
        valid, validation = self._validate(staging)
        if not valid:
            shutil.rmtree(staging, ignore_errors=True)
            self.store.upsert_feed("clamav", "validation_failed", "error", {"error": validation})
            return {"ok": False, "state": "validation_failed", "error": validation}
        try:
            self._activate(staging)
        except OSError as exc:
            shutil.rmtree(staging, ignore_errors=True)
            self.store.upsert_feed("clamav", "activation_failed", "error", {"error": str(exc)})
            return {"ok": False, "state": "activation_failed", "error": str(exc)}
        current = self.root / "current"
        version = str(max((path.stat().st_mtime_ns for path in current.iterdir()), default=0))
        self.store.upsert_feed("clamav", version, "ok", {"validation": validation})
        return {"ok": True, "state": "ok", "version": version, "validation": validation}


def _parse_updated_at(value: object) -> float | None:
    """feed_state.updated_at(ISO8601)をepoch秒へ変換する。失敗時はNone。"""
    if not isinstance(value, str) or not value:
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    try:
        return parsed.timestamp()
    except (OverflowError, OSError, ValueError):
        return None


def last_ok_update_time(store: SecurityStore) -> float | None:
    """最終ok更新時刻(epoch秒)を返す。ok行が無ければNone(=初回:要更新)。"""
    try:
        summary = store.status_summary()
    except Exception:
        logger.debug("auto-update: status_summary failed", exc_info=True)
        return None
    return _parse_updated_at(summary.get("last_signature_update"))


def is_auto_update_due(store: SecurityStore, interval_hours: float = DEFAULT_AUTO_UPDATE_INTERVAL_HOURS) -> bool:
    """最終ok更新からinterval_hours経過していたらTrue。判定失敗時は安全側でFalse。"""
    try:
        interval = float(interval_hours)
    except (TypeError, ValueError):
        return False
    if not interval or interval <= 0:
        return False
    try:
        last = last_ok_update_time(store)
    except Exception:
        return False
    if last is None:
        return True
    return (time.time() - last) >= interval * 3600.0


def _auto_update_lock_path(store: SecurityStore) -> Path:
    return store.root / "feeds" / "clamav" / AUTO_UPDATE_LOCK_NAME


def _try_acquire_auto_update_lock(store: SecurityStore) -> bool:
    """プロファイル毎の簡易ロックを取得する。取得できればTrue。

    Windowsでも動作するよう排他作成(os.O_CREAT|os.O_EXCL)で実装し、
    stale(1h超)は前所有者のクラッシュとみなして引き継ぐ。
    """
    try:
        path = _auto_update_lock_path(store)
        path.parent.mkdir(parents=True, exist_ok=True)
        flags = os.O_CREAT | os.O_EXCL | os.O_WRONLY
        try:
            fd = os.open(str(path), flags)
        except FileExistsError:
            try:
                age = time.time() - path.stat().st_mtime
            except OSError:
                return False
            if age < AUTO_UPDATE_LOCK_STALE_SECONDS:
                return False
            try:
                path.unlink()
            except OSError:
                return False
            try:
                fd = os.open(str(path), flags)
            except FileExistsError:
                return False
        try:
            os.write(fd, str(os.getpid()).encode("ascii", "replace"))
        finally:
            os.close(fd)
        return True
    except Exception:
        logger.debug("auto-update: lock acquire failed", exc_info=True)
        return False


def _release_auto_update_lock(store: SecurityStore) -> None:
    try:
        _auto_update_lock_path(store).unlink(missing_ok=True)
    except Exception:
        logger.debug("auto-update: lock release failed", exc_info=True)


def _resolve_auto_update_config(config: dict[str, Any] | None) -> tuple[bool, float, int]:
    malware = ((config or {}).get("security") or {}).get("malware") or {}
    if not isinstance(malware, dict):
        malware = {}
    enabled = malware.get("auto_update_enabled", True)
    interval = malware.get("auto_update_interval_hours", DEFAULT_AUTO_UPDATE_INTERVAL_HOURS)
    try:
        interval_hours = float(interval)
    except (TypeError, ValueError):
        interval_hours = float(DEFAULT_AUTO_UPDATE_INTERVAL_HOURS)
    if interval_hours <= 0:
        interval_hours = float(DEFAULT_AUTO_UPDATE_INTERVAL_HOURS)
    try:
        timeout = int(malware.get("update_timeout", 300))
    except (TypeError, ValueError):
        timeout = 300
    return bool(enabled), interval_hours, timeout


def sync_bundled_yara_rules(store: SecurityStore) -> dict[str, Any]:
    """同梱YARAルールをfeeds/yaraへ同期し、feed_stateへ版情報を記録する。

    起動時チェックから呼ばれる想定。新規・更新分のみコピーし、失敗しても
    例外を投げず結果dictを返す。
    """
    try:
        yara_dir = store.root / "feeds" / "yara"
        yara_dir.mkdir(parents=True, exist_ok=True)
        bundled = Path(__file__).parent / "rules"
        copied = 0
        newest_ns = 0
        for source in sorted(bundled.glob("*.yar")):
            try:
                destination = yara_dir / source.name
                source_stat = source.stat()
                newest_ns = max(newest_ns, source_stat.st_mtime_ns)
                if not destination.exists() or destination.stat().st_mtime_ns < source_stat.st_mtime_ns:
                    shutil.copy2(source, destination)
                    copied += 1
            except OSError:
                logger.debug("auto-update: yara sync failed for %s", source.name, exc_info=True)
        version = str(newest_ns) if newest_ns else "bundled"
        try:
            store.upsert_feed("yara", version, "ok", {"synced_files": copied})
        except Exception:
            logger.debug("auto-update: yara feed upsert failed", exc_info=True)
            return {"ok": False, "error": "feed upsert failed", "synced_files": copied}
        return {"ok": True, "version": version, "synced_files": copied}
    except Exception as exc:
        logger.debug("auto-update: yara sync failed", exc_info=True)
        return {"ok": False, "error": str(exc)}


def maybe_auto_update(
    store: SecurityStore,
    config: dict[str, Any] | None = None,
    *,
    force: bool = False,
) -> dict[str, Any]:
    """一日一回自動更新の本体。起動時チェックから呼ぶ想定。

    - configのsecurity.malware.auto_update_enabled=falseなら何もしない
    - force=false時は最終ok更新からinterval経過後のみ実行
    - 同時実行はプロファイル毎ロックで抑止(staleは1h)
    - ClamAV更新 + 同梱YARA同期を行い、失敗しても例外を投げない
    - read-onlyストアでは何もしない
    """
    try:
        if getattr(store, "read_only", False):
            return {"ok": True, "skipped": "read-only"}
        enabled, interval_hours, timeout = _resolve_auto_update_config(config)
        if not enabled and not force:
            return {"ok": True, "skipped": "disabled"}
        if not force and not is_auto_update_due(store, interval_hours):
            return {"ok": True, "skipped": "not-due"}
        if not _try_acquire_auto_update_lock(store):
            return {"ok": True, "skipped": "locked"}
        try:
            yara_result = sync_bundled_yara_rules(store)
            updater = DefinitionUpdater(store, timeout)
            clamav_result = updater.update_clamav()
            ok = bool(clamav_result.get("ok")) and bool(yara_result.get("ok"))
            logger.info(
                "security auto-update finished ok=%s clamav=%s yara=%s",
                ok, clamav_result.get("state"), yara_result.get("ok"),
            )
            return {"ok": ok, "clamav": clamav_result, "yara": yara_result}
        finally:
            _release_auto_update_lock(store)
    except Exception as exc:
        logger.warning("security auto-update failed: %s", exc, exc_info=True)
        try:
            _release_auto_update_lock(store)
        except Exception:
            pass
        return {"ok": False, "error": str(exc)}


def maybe_auto_update_all_profiles(config: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    """全プロファイルの定義を一日一回条件で自動更新する。起動時専用。

    各プロファイルで例外が出ても他に波及させず、結果リストを返す。
    存在しない/削除済みプロファイルはskipする。
    """
    results: list[dict[str, Any]] = []
    try:
        from hermes_cli.profiles import get_profile_dir, list_profile_names
    except Exception as exc:
        logger.debug("auto-update: profiles module unavailable: %s", exc)
        return results
    try:
        names = list_profile_names()
    except Exception as exc:
        logger.debug("auto-update: list_profile_names failed: %s", exc)
        return results
    for name in names:
        try:
            home = get_profile_dir(name)
        except Exception:
            results.append({"profile": name, "ok": True, "skipped": "resolve-failed"})
            continue
        try:
            if not home.is_dir():
                continue
            security_root = home / "security"
            # 未利用プロファイルで空のSecurity Centerを作らない: security
            # ディレクトリもwatch-stateも無ければ対象外。
            if not security_root.is_dir():
                results.append({"profile": name, "ok": True, "skipped": "no-security-state"})
                continue
            from .store import SecurityStore as _Store

            result = maybe_auto_update(_Store(security_root), config)
            result["profile"] = name
            results.append(result)
        except Exception as exc:
            logger.debug("auto-update: profile %s failed", name, exc_info=True)
            results.append({"profile": name, "ok": False, "error": str(exc)})
    return results
