from __future__ import annotations

import hashlib
import os
import shutil
import stat
import subprocess
import sys
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import replace
from pathlib import Path
from typing import Iterable

from hermes_cli.config import load_config

from .engines import ClamAVEngine, HashReputationEngine, StaticHeuristicsEngine, YaraEngine, engine_versions, versions_cache_key
from .models import ExecutionDecision, Finding, ScanResult, Verdict
from .policy import evaluate
from .store import SecurityStore
from .updates import DefinitionUpdater
from .vault import QuarantineVault


FileIdentity = tuple[int, int, int, int, int]


def _stat_identity(metadata: os.stat_result) -> FileIdentity:
    return (
        int(metadata.st_dev),
        int(metadata.st_ino),
        int(metadata.st_size),
        int(metadata.st_mtime_ns),
        int(metadata.st_ctime_ns),
    )


def hash_stable_file(path: Path) -> tuple[str, int, FileIdentity]:
    before = path.stat()
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        opened = os.fstat(handle.fileno())
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
        read_after = os.fstat(handle.fileno())
    after = path.stat()
    identities = {_stat_identity(item) for item in (before, opened, read_after, after)}
    if len(identities) != 1:
        raise RuntimeError("file changed during scan")
    return digest.hexdigest(), int(after.st_size), _stat_identity(after)


def is_reparse_point(path: Path) -> bool:
    try:
        attributes = getattr(path.stat(follow_symlinks=False), "st_file_attributes", 0)
    except OSError:
        return True
    return path.is_symlink() or bool(attributes & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0))


class SecurityService:
    def __init__(
        self,
        store: SecurityStore | None = None,
        config: dict | None = None,
        *,
        read_only: bool = False,
    ) -> None:
        self.store = store or SecurityStore(read_only=read_only)
        self.read_only = read_only or self.store.read_only
        root_config = config if config is not None else load_config()
        self.config = dict((root_config.get("security") or {}).get("malware") or {})
        timeout = int(self.config.get("scanner_timeout", 30))
        yara_rules = self.store.root / "feeds" / "yara"
        if not self.read_only:
            yara_rules.mkdir(parents=True, exist_ok=True)
            bundled_rules = Path(__file__).parent / "rules"
            for bundled in bundled_rules.glob("*.yar"):
                destination = yara_rules / bundled.name
                if not destination.exists():
                    shutil.copy2(bundled, destination)
        self.engines = (
            HashReputationEngine(self.store),
            ClamAVEngine(timeout, self.store.root / "feeds" / "clamav" / "current"),
            YaraEngine(yara_rules, timeout=timeout),
            StaticHeuristicsEngine(),
        )
        self._vault: QuarantineVault | None = None
        self._vault_lock = threading.Lock()

    @property
    def vault(self) -> QuarantineVault:
        if self._vault is None:
            with self._vault_lock:
                if self._vault is None:
                    self._vault = QuarantineVault(self.store, read_only=self.read_only)
        return self._vault

    def versions(self) -> dict[str, str]:
        return engine_versions(self.engines)

    def status(self) -> dict[str, object]:
        versions = self.versions()
        return {
            "enabled": bool(self.config.get("enabled", True)),
            "auto_quarantine": bool(self.config.get("auto_quarantine", True)),
            "vault_key_protection": "windows_dpapi" if sys.platform == "win32" else "filesystem_permissions",
            "summary": self.store.status_summary(),
            "engines": versions,
            "feeds": self.store.status_rows("feed_state"),
            "watch": self.watch_status(),
            "recent_events": self.store.status_rows("detection_events", 25),
            "quarantine": self.store.status_rows("quarantine_items", 25),
        }

    def _hash_stable(self, path: Path) -> tuple[str, int, FileIdentity]:
        return hash_stable_file(path)

    @staticmethod
    def _changed_file_result(
        path: Path,
        versions: dict[str, str],
    ) -> ScanResult:
        return ScanResult(
            str(path),
            "",
            0,
            Verdict.SCAN_ERROR,
            0,
            "blocked_pending_review",
            (),
            versions,
            error="file_changed_during_scan",
        )

    def scan_file(self, candidate: Path | str, quarantine: bool = True, use_cache: bool = True) -> ScanResult:
        path = Path(candidate).resolve(strict=True)
        if not path.is_file():
            raise ValueError("scan target must be a regular file")
        try:
            sha256, size, identity = self._hash_stable(path)
        except (OSError, RuntimeError) as exc:
            error = "file_changed_during_scan" if isinstance(exc, RuntimeError) else str(exc)
            return ScanResult(str(path), "", 0, Verdict.SCAN_ERROR, 0, "blocked_pending_review", (), self.versions(), error=error)
        snapshot = (sha256, size, identity)
        versions = self.versions()
        cache_key = versions_cache_key(versions)
        if use_cache:
            cached = self.store.cache_get(sha256, cache_key)
            if cached is not None:
                decision = evaluate(list(cached.findings), self.store.is_allowed(sha256, str(path)))
                try:
                    after_cache_read = self._hash_stable(path)
                except (OSError, RuntimeError):
                    return self._changed_file_result(path, versions)
                if after_cache_read != snapshot or cached.sha256 != sha256:
                    return self._changed_file_result(path, versions)
                cached = replace(
                    cached,
                    path=str(path),
                    verdict=decision.verdict,
                    score=decision.score,
                    action=decision.action,
                    error=decision.error,
                    quarantine_id=None,
                    file_identity=identity,
                )
                if (
                    decision.execution_decision == ExecutionDecision.BLOCK
                    and decision.action == "quarantine"
                    and quarantine
                    and bool(self.config.get("auto_quarantine", True))
                ):
                    try:
                        item_id = self.vault.quarantine(path, cached)
                        cached = replace(cached, action="quarantined", quarantine_id=item_id)
                    except Exception:
                        cached = replace(cached, action="quarantine_failed", error="quarantine failed")
                self.store.record_scan(cached, cache_key)
                return cached
        findings: list[Finding] = []
        for engine in self.engines:
            findings.extend(engine.scan(path, sha256))
        allowed = self.store.is_allowed(sha256, str(path))
        decision = evaluate(findings, allowed)
        try:
            after_scan = self._hash_stable(path)
        except (OSError, RuntimeError):
            return self._changed_file_result(path, versions)
        if after_scan != snapshot:
            return self._changed_file_result(path, versions)
        result = ScanResult(
            str(path),
            sha256,
            size,
            decision.verdict,
            decision.score,
            decision.action,
            tuple(findings),
            versions,
            error=decision.error,
            file_identity=identity,
        )
        if (
            quarantine
            and decision.execution_decision == ExecutionDecision.BLOCK
            and decision.action == "quarantine"
            and bool(self.config.get("auto_quarantine", True))
        ):
            try:
                item_id = self.vault.quarantine(path, result)
                result = replace(result, action="quarantined", quarantine_id=item_id)
            except Exception:
                result = replace(result, action="quarantine_failed", error="quarantine failed")
        self.store.record_scan(result, cache_key)
        return result

    def scan_paths(self, paths: Iterable[Path | str], workers: int | None = None, quarantine: bool = True) -> list[ScanResult]:
        files: list[Path] = []
        requested_paths: list[str] = []
        for item in paths:
            path = Path(item).resolve(strict=True)
            requested_paths.append(str(path))
            if path.is_file():
                files.append(path)
                continue
            for root, dirnames, names in os.walk(path, followlinks=False):
                dirnames[:] = [name for name in dirnames if not is_reparse_point(Path(root) / name)]
                files.extend(Path(root) / name for name in names if not is_reparse_point(Path(root) / name))
        self.store.event(
            "scan_requested",
            f"{len(requested_paths)} path(s)",
            None,
            "requested",
            {"paths": requested_paths, "files_discovered": len(files), "quarantine": quarantine},
        )
        maximum = max(1, min(int(workers or self.config.get("max_workers", 4)), 8))
        results: list[ScanResult] = []
        with ThreadPoolExecutor(max_workers=maximum, thread_name_prefix="hermes-security") as pool:
            futures = {pool.submit(self.scan_file, path, quarantine): path for path in files}
            for future in as_completed(futures):
                try:
                    results.append(future.result())
                except Exception as exc:
                    results.append(ScanResult(str(futures[future]), "", 0, Verdict.SCAN_ERROR, 0, "blocked_pending_review", (), self.versions(), error=str(exc)))
        counts = {verdict.value: 0 for verdict in Verdict}
        for result in results:
            counts[result.verdict.value] += 1
        self.store.event(
            "scan_completed",
            f"{len(results)} file(s)",
            None,
            "completed",
            {"counts": counts, "files_scanned": len(results)},
        )
        return results

    def quick_paths(self) -> list[Path]:
        home = Path.home()
        candidates = [
            home / "Downloads",
            home / "Desktop",
            self.store.root.parent / "plugins",
            self.store.root.parent / "skills",
        ]
        temporary = os.environ.get("TEMP")
        if temporary:
            candidates.append(Path(temporary))
        app_data = os.environ.get("APPDATA")
        if app_data:
            candidates.append(Path(app_data) / "Microsoft" / "Windows" / "Start Menu" / "Programs" / "Startup")
        local_app_data = os.environ.get("LOCALAPPDATA")
        if local_app_data:
            candidates.append(Path(local_app_data) / "Temp")
        existing: list[Path] = []
        seen: set[str] = set()
        for path in candidates:
            key = str(path.resolve()) if path.exists() else str(path)
            if path.exists() and key not in seen:
                existing.append(path)
                seen.add(key)
        return existing

    def full_paths(self) -> list[Path]:
        if sys.platform == "win32":
            return [Path(f"{letter}:\\") for letter in "CDEFGHIJKLMNOPQRSTUVWXYZ" if Path(f"{letter}:\\").exists()]
        return [Path.home()]

    def update(self) -> dict[str, object]:
        return DefinitionUpdater(self.store, int(self.config.get("update_timeout", 300))).update_clamav()

    def watch_status(self) -> dict[str, object]:
        from .watch_state import read_watch_status

        return read_watch_status(self.store.root)
