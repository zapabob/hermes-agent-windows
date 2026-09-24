from __future__ import annotations

import hashlib
import importlib
import os
import shutil
import stat
import subprocess
import sys
import threading
import uuid
from contextlib import contextmanager
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Iterable, Iterator

from hermes_cli.config import load_config

from .engines import ClamAVEngine, HashReputationEngine, StaticHeuristicsEngine, YaraEngine, engine_versions, versions_cache_key
from .models import ExecutionDecision, Finding, ScanResult, Verdict
from .policy import evaluate
from .store import SecurityStore
from .updates import DefinitionUpdater
from .vault import QuarantineVault


FileIdentity = tuple[int, int, int, int, int]


class _FileChangedDuringScan(RuntimeError):
    pass


class _ScanSnapshotUnavailable(RuntimeError):
    pass


@dataclass(frozen=True)
class _ScanSnapshot:
    path: Path
    sha256: str
    size: int
    source_identity: FileIdentity
    snapshot_identity: FileIdentity


def _create_private_snapshot_directory(root: Path) -> Path:
    directory = root / f".scan-{uuid.uuid4().hex}"
    if sys.platform != "win32":
        directory.mkdir(mode=0o700)
        os.chmod(directory, 0o700)
        return directory

    ntsecuritycon = importlib.import_module("ntsecuritycon")
    win32api = importlib.import_module("win32api")
    win32file = importlib.import_module("win32file")
    win32security = importlib.import_module("win32security")

    owner_name = win32api.GetUserNameEx(2)
    owner_sid, _, _ = win32security.LookupAccountName(None, owner_name)
    system_sid = win32security.CreateWellKnownSid(win32security.WinLocalSystemSid, None)
    acl = win32security.ACL()
    inheritance = win32security.CONTAINER_INHERIT_ACE | win32security.OBJECT_INHERIT_ACE
    acl.AddAccessAllowedAceEx(
        win32security.ACL_REVISION, inheritance, ntsecuritycon.FILE_ALL_ACCESS, owner_sid
    )
    acl.AddAccessAllowedAceEx(
        win32security.ACL_REVISION, inheritance, ntsecuritycon.FILE_ALL_ACCESS, system_sid
    )
    descriptor = win32security.SECURITY_DESCRIPTOR()
    descriptor.SetSecurityDescriptorOwner(owner_sid, False)
    descriptor.SetSecurityDescriptorDacl(1, acl, 0)
    descriptor.SetSecurityDescriptorControl(
        win32security.SE_DACL_PROTECTED, win32security.SE_DACL_PROTECTED
    )
    attributes = win32security.SECURITY_ATTRIBUTES()
    attributes.SECURITY_DESCRIPTOR = descriptor
    win32file.CreateDirectory(str(directory), attributes)
    # Protect the DACL at creation so the directory is never briefly exposed
    # through inherited permissions from the security-store parent.
    return directory


def _create_scan_snapshot_handle(path: Path) -> object:
    if sys.platform == "win32":
        win32con = importlib.import_module("win32con")
        win32file = importlib.import_module("win32file")

        # Keep this handle open while engines scan. FILE_SHARE_READ permits
        # their read-only opens and denies writes, replacement, and deletion.
        return win32file.CreateFile(
            str(path),
            win32con.GENERIC_READ | win32con.GENERIC_WRITE,
            win32con.FILE_SHARE_READ,
            None,
            win32con.CREATE_NEW,
            win32con.FILE_ATTRIBUTE_NORMAL,
            None,
        )
    descriptor = os.open(path, os.O_CREAT | os.O_EXCL | os.O_RDWR, 0o600)
    return os.fdopen(descriptor, "r+b")


def _write_snapshot_chunk(handle: object, chunk: bytes) -> None:
    if sys.platform == "win32":
        win32file = importlib.import_module("win32file")

        error, written = win32file.WriteFile(handle, chunk)
        if error != 0 or written != len(chunk):
            raise OSError("scan snapshot write failed")
        return
    written = handle.write(chunk)
    if written != len(chunk):
        raise OSError("scan snapshot write failed")


def _flush_snapshot(handle: object) -> None:
    if sys.platform == "win32":
        win32file = importlib.import_module("win32file")

        win32file.FlushFileBuffers(handle)
        return
    handle.flush()
    os.fsync(handle.fileno())


def _close_snapshot_handle(handle: object | None) -> None:
    if handle is None:
        return
    if sys.platform == "win32":
        getattr(handle, "Close")()
    else:
        getattr(handle, "close")()


@contextmanager
def _create_scan_snapshot(path: Path, root: Path) -> Iterator[_ScanSnapshot]:
    try:
        directory = _create_private_snapshot_directory(root)
    except Exception as exc:
        raise _ScanSnapshotUnavailable from exc

    snapshot_path = directory / path.name
    handle: object | None = None
    try:
        try:
            handle = _create_scan_snapshot_handle(snapshot_path)
            digest = hashlib.sha256()
            size = 0
            before = path.stat()
            with path.open("rb") as source:
                opened = os.fstat(source.fileno())
                for chunk in iter(lambda: source.read(1024 * 1024), b""):
                    digest.update(chunk)
                    size += len(chunk)
                    _write_snapshot_chunk(handle, chunk)
                read_after = os.fstat(source.fileno())
            after = path.stat()
            identities = {
                _stat_identity(item)
                for item in (before, opened, read_after, after)
            }
            if len(identities) != 1:
                raise _FileChangedDuringScan
            _flush_snapshot(handle)
            if sys.platform != "win32":
                os.chmod(snapshot_path, 0o400)
            sha256 = digest.hexdigest()
            snapshot_sha256, snapshot_size, snapshot_identity = hash_stable_file(snapshot_path)
            if (snapshot_sha256, snapshot_size) != (sha256, size):
                raise _ScanSnapshotUnavailable
            snapshot = _ScanSnapshot(
                snapshot_path,
                sha256,
                size,
                _stat_identity(after),
                snapshot_identity,
            )
        except _FileChangedDuringScan:
            raise
        except Exception as exc:
            raise _ScanSnapshotUnavailable from exc

        yield snapshot

        try:
            snapshot_after = hash_stable_file(snapshot_path)
        except (OSError, RuntimeError, ValueError) as exc:
            raise _ScanSnapshotUnavailable from exc
        if snapshot_after != (snapshot.sha256, snapshot.size, snapshot.snapshot_identity):
            raise _ScanSnapshotUnavailable
    finally:
        cleanup_failed = False
        try:
            _close_snapshot_handle(handle)
        except Exception:
            cleanup_failed = True
        try:
            shutil.rmtree(directory)
        except OSError:
            cleanup_failed = True
        if cleanup_failed:
            raise _ScanSnapshotUnavailable


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

    @staticmethod
    def _snapshot_unavailable_result(
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
            error="scan_snapshot_unavailable",
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
        try:
            with _create_scan_snapshot(path, self.store.root) as scan_snapshot:
                if (
                    scan_snapshot.sha256,
                    scan_snapshot.size,
                    scan_snapshot.source_identity,
                ) != snapshot:
                    raise _FileChangedDuringScan
                for engine in self.engines:
                    if isinstance(engine, StaticHeuristicsEngine):
                        findings.extend(
                            engine.scan(
                                scan_snapshot.path,
                                sha256,
                                original_path=path,
                            )
                        )
                    else:
                        findings.extend(engine.scan(scan_snapshot.path, sha256))
                try:
                    after_scan = self._hash_stable(path)
                except (OSError, RuntimeError, ValueError) as exc:
                    raise _FileChangedDuringScan from exc
                if after_scan != snapshot:
                    raise _FileChangedDuringScan
        except _FileChangedDuringScan:
            return self._changed_file_result(path, versions)
        except _ScanSnapshotUnavailable:
            return self._snapshot_unavailable_result(path, versions)
        allowed = self.store.is_allowed(sha256, str(path))
        decision = evaluate(findings, allowed)
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
