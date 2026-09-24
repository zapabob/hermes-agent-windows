from __future__ import annotations

import logging
import hashlib
import os
import shutil
import subprocess
import stat
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .bounded_process import BoundedProcessOutputError, run_bounded
from .bounded_walk import stable_file_time_ns
from .clamav_definitions import (
    DefinitionInventoryError,
    MAX_DEFINITION_DIRECTORY_ENTRIES,
    MAX_DEFINITION_FILE_BYTES,
    MAX_DEFINITION_FILES,
    MAX_DEFINITION_TOTAL_BYTES,
    inventory_clamav_definitions,
)
from .engines import MAX_YARA_DIRECTORY_ENTRIES, MAX_YARA_RULE_BYTES, MAX_YARA_RULE_FILES, MAX_YARA_TOTAL_BYTES
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
MAX_UPDATE_TIMEOUT_SECONDS = 900
MAX_UPDATE_OUTPUT_BYTES = 16 * 1024
MAX_SIGTOOL_OUTPUT_BYTES = 8 * 1024
MAX_BUNDLED_YARA_ENTRIES = MAX_YARA_DIRECTORY_ENTRIES
MAX_BUNDLED_YARA_FILES = MAX_YARA_RULE_FILES
MAX_BUNDLED_YARA_FILE_BYTES = MAX_YARA_RULE_BYTES
MAX_BUNDLED_YARA_TOTAL_BYTES = MAX_YARA_TOTAL_BYTES
DEFINITION_INVENTORY_ERRORS = {
    "unknown": "definition_version_unavailable",
    "inventory-limit": "definition_inventory_limit",
    "file-limit": "definition_file_limit",
    "invalid-file": "definition_file_invalid",
}


class DefinitionUpdater:
    def __init__(self, store: SecurityStore, timeout: int = 300) -> None:
        self.store = store
        self.timeout = max(30, min(int(timeout), MAX_UPDATE_TIMEOUT_SECONDS))
        self.root = store.root / "feeds" / "clamav"
        self.root.mkdir(parents=True, exist_ok=True)

    def _validate(self, candidate: Path) -> tuple[bool, str]:
        try:
            inventory = inventory_clamav_definitions(
                candidate,
                max_entries=MAX_DEFINITION_DIRECTORY_ENTRIES,
                max_files=MAX_DEFINITION_FILES,
                max_file_bytes=MAX_DEFINITION_FILE_BYTES,
                max_total_bytes=MAX_DEFINITION_TOTAL_BYTES,
            )
        except DefinitionInventoryError as exc:
            return False, _definition_inventory_validation_error(exc.reason)
        databases = inventory.archives
        if not databases or any(item.size < 512 for item in databases):
            return False, "freshclam produced no valid CVD/CLD database"
        sigtool = shutil.which("sigtool")
        if sigtool:
            for database in databases:
                try:
                    result = run_bounded(
                        [sigtool, "--info", str(database.path)],
                        timeout=30,
                        max_output_bytes_per_stream=MAX_SIGTOOL_OUTPUT_BYTES,
                    )
                except (OSError, subprocess.SubprocessError, BoundedProcessOutputError):
                    return False, f"sigtool could not validate {database.name}"
                if result.returncode != 0 or result.output_truncated:
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
            result = run_bounded(
                [freshclam, f"--datadir={staging}"],
                timeout=self.timeout,
                max_output_bytes_per_stream=MAX_UPDATE_OUTPUT_BYTES,
            )
        except subprocess.TimeoutExpired:
            shutil.rmtree(staging, ignore_errors=True)
            self.store.upsert_feed("clamav", EngineState.SCAN_TIMEOUT.value, "error", {"error": "freshclam timeout"})
            return {"ok": False, "state": EngineState.SCAN_TIMEOUT.value, "error": "freshclam timeout"}
        except (OSError, subprocess.SubprocessError, BoundedProcessOutputError) as exc:
            shutil.rmtree(staging, ignore_errors=True)
            self.store.upsert_feed("clamav", "update_failed", "error", {"error": type(exc).__name__})
            return {"ok": False, "state": "update_failed", "error": "freshclam execution failed"}
        output = "\n".join((result.stdout, result.stderr)).strip()[-2000:]
        if result.output_truncated or result.returncode != 0:
            shutil.rmtree(staging, ignore_errors=True)
            self.store.upsert_feed(
                "clamav",
                "update_failed",
                "error",
                {"exit_code": result.returncode, "output": output, "output_truncated": result.output_truncated},
            )
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
        version = self._definition_version(current)
        if version in DEFINITION_INVENTORY_ERRORS:
            error = DEFINITION_INVENTORY_ERRORS[version]
            details = {
                "activated": True,
                "validation": validation,
                "verification": "incomplete",
                "error": error,
            }
            self.store.upsert_feed("clamav", "activation_unverified", "error", details)
            return {
                "ok": False,
                "state": "activation_unverified",
                "activated": True,
                "version": "unknown",
                "error": error,
            }
        self.store.upsert_feed("clamav", version, "ok", {"validation": validation})
        return {"ok": True, "state": "ok", "version": version, "validation": validation}

    @staticmethod
    def _definition_version(current: Path) -> str:
        try:
            inventory = inventory_clamav_definitions(
                current,
                max_entries=MAX_DEFINITION_DIRECTORY_ENTRIES,
                max_files=MAX_DEFINITION_FILES,
                max_file_bytes=MAX_DEFINITION_FILE_BYTES,
                max_total_bytes=MAX_DEFINITION_TOTAL_BYTES,
            )
        except DefinitionInventoryError as exc:
            return _definition_inventory_version_error(exc.reason)
        return inventory.revision if inventory.archives else "unknown"


def _definition_inventory_version_error(reason: str) -> str:
    if reason == "definition_entry_limit":
        return "inventory-limit"
    if reason == "definition_file_limit":
        return "file-limit"
    if reason in {"unsupported_definition_entry", "invalid_definition_file", "definition_reparse_point"}:
        return "invalid-file"
    if reason in {"definition_file_size_limit", "definition_total_size_limit"}:
        return "file-limit"
    return "unknown"


def _definition_inventory_validation_error(reason: str) -> str:
    if reason == "definition_entry_limit":
        return "definition inventory limit exceeded"
    if reason == "definition_file_limit":
        return "too many definition files"
    if reason == "definition_file_size_limit":
        return "definition file size limit exceeded"
    if reason == "definition_total_size_limit":
        return "definition total size limit exceeded"
    if reason in {"unsupported_definition_entry", "invalid_definition_file", "definition_reparse_point"}:
        return "invalid definition file"
    return "definition directory unavailable"


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
        bundled = Path(__file__).parent / "rules"
        try:
            rule_files, version, validation_error = _inventory_bundled_yara_rules(bundled)
        except OSError:
            return {"ok": False, "error": "bundled rule directory unavailable", "synced_files": 0}
        if validation_error is not None:
            return {"ok": False, "error": validation_error, "synced_files": 0}
        yara_dir = store.root / "feeds" / "yara"
        yara_dir.mkdir(parents=True, exist_ok=True)
        copied = 0
        for source, source_bytes, source_mtime_ns in rule_files:
            destination = yara_dir / source.name
            try:
                current = _read_existing_yara_rule(destination)
                if current == source_bytes:
                    continue
                temporary = yara_dir / f".{source.name}.{uuid.uuid4().hex}.tmp"
                temporary.write_bytes(source_bytes)
                os.utime(temporary, ns=(source_mtime_ns, source_mtime_ns))
                os.replace(temporary, destination)
                copied += 1
            except OSError:
                logger.debug("auto-update: yara sync failed for %s", source.name, exc_info=True)
                return {"ok": False, "error": "bundled rule sync failed", "synced_files": copied}
        try:
            store.upsert_feed("yara", version, "ok", {"synced_files": copied})
        except Exception:
            logger.debug("auto-update: yara feed upsert failed", exc_info=True)
            return {"ok": False, "error": "feed upsert failed", "synced_files": copied}
        return {"ok": True, "version": version, "synced_files": copied}
    except Exception as exc:
        logger.debug("auto-update: yara sync failed", exc_info=True)
        return {"ok": False, "error": str(exc)}


def _inventory_bundled_yara_rules(
    bundled: Path,
) -> tuple[list[tuple[Path, bytes, int]], str, str | None]:
    files: list[tuple[Path, bytes, int]] = []
    total_bytes = 0
    version_digest = hashlib.sha256()
    try:
        entries = os.scandir(bundled)
    except FileNotFoundError:
        return files, "bundled", None
    with entries:
        for index, entry in enumerate(entries):
            if index >= MAX_BUNDLED_YARA_ENTRIES:
                return [], "", "bundled rule inventory limit exceeded"
            path = Path(entry.path)
            if path.suffix.casefold() not in {".yar", ".yara"}:
                continue
            if len(files) >= MAX_BUNDLED_YARA_FILES:
                return [], "", "too many bundled rule files"
            try:
                metadata = path.stat(follow_symlinks=False)
            except OSError:
                return [], "", "bundled rule file unavailable"
            reparse_flag = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0)
            if (
                stat.S_ISLNK(metadata.st_mode)
                or (reparse_flag and getattr(metadata, "st_file_attributes", 0) & reparse_flag)
                or not stat.S_ISREG(metadata.st_mode)
            ):
                return [], "", "invalid bundled rule file"
            if metadata.st_size < 0 or metadata.st_size > MAX_BUNDLED_YARA_FILE_BYTES:
                return [], "", "bundled rule size limit exceeded"
            total_bytes += int(metadata.st_size)
            if total_bytes > MAX_BUNDLED_YARA_TOTAL_BYTES:
                return [], "", "bundled rule total size limit exceeded"
            try:
                with path.open("rb") as handle:
                    opened = os.fstat(handle.fileno())
                    if _file_identity(opened) != _file_identity(metadata):
                        return [], "", "bundled rule changed during inventory"
                    content = handle.read(MAX_BUNDLED_YARA_FILE_BYTES + 1)
                    after_handle = os.fstat(handle.fileno())
                after_path = path.stat(follow_symlinks=False)
            except OSError:
                return [], "", "bundled rule file unavailable"
            if (
                len(content) != metadata.st_size
                or len(content) > MAX_BUNDLED_YARA_FILE_BYTES
                or _file_identity(after_handle) != _file_identity(metadata)
                or _file_identity(after_path) != _file_identity(metadata)
            ):
                return [], "", "bundled rule changed during inventory"
            try:
                content.decode("utf-8")
            except UnicodeDecodeError:
                return [], "", "bundled rule is not UTF-8"
            files.append((path, content, int(metadata.st_mtime_ns)))
            version_digest.update(path.name.casefold().encode("utf-8"))
            version_digest.update(b"\0")
            version_digest.update(hashlib.sha256(content).digest())
    version = version_digest.hexdigest() if files else "bundled"
    return sorted(files, key=lambda item: item[0].name.casefold()), version, None


def _file_identity(metadata: os.stat_result) -> tuple[int, int, int, int, int]:
    return (
        int(metadata.st_dev),
        int(metadata.st_ino),
        int(metadata.st_size),
        int(metadata.st_mtime_ns),
        stable_file_time_ns(metadata),
    )


def _read_existing_yara_rule(path: Path) -> bytes | None:
    try:
        before = path.stat(follow_symlinks=False)
    except OSError:
        return None
    reparse_flag = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0)
    if (
        stat.S_ISLNK(before.st_mode)
        or (reparse_flag and getattr(before, "st_file_attributes", 0) & reparse_flag)
        or not stat.S_ISREG(before.st_mode)
        or before.st_size > MAX_BUNDLED_YARA_FILE_BYTES
    ):
        return None
    try:
        with path.open("rb") as handle:
            opened = os.fstat(handle.fileno())
            if _file_identity(opened) != _file_identity(before):
                return None
            content = handle.read(MAX_BUNDLED_YARA_FILE_BYTES + 1)
            after_handle = os.fstat(handle.fileno())
        after_path = path.stat(follow_symlinks=False)
    except OSError:
        return None
    if (
        len(content) != before.st_size
        or len(content) > MAX_BUNDLED_YARA_FILE_BYTES
        or _file_identity(after_handle) != _file_identity(before)
        or _file_identity(after_path) != _file_identity(before)
    ):
        return None
    return content


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
