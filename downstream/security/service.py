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
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Iterable, Iterator

from hermes_cli.config import load_config

from .bounded_walk import (
    DirectoryWalkReport,
    MAX_SCAN_FILES,
    MAX_SCAN_ROOTS,
    MAX_WALK_DEPTH,
    MAX_WALK_DIRECTORIES,
    MAX_WALK_ENTRIES,
    ReparsePathError,
    absolute_path_without_reparse,
    iter_regular_files,
)
from .engines import ClamAVEngine, HashReputationEngine, StaticHeuristicsEngine, YaraEngine, engine_versions, versions_cache_key
from .models import EngineHealth, EngineState, ExecutionDecision, Finding, ScanResult, Verdict
from .policy import evaluate
from .snapshot_budget import reserve_snapshot_bytes
from .store import SecurityStore
from .updates import DefinitionUpdater
from .vault import QuarantineVault


FileIdentity = tuple[int, int, int, int, int]
MAX_SCAN_TARGET_BYTES = 1024 * 1024 * 1024
MAX_ACTIVE_SCAN_BYTES = 2 * 1024 * 1024 * 1024
MAX_SCAN_FUTURES_MULTIPLIER = 2
MAX_SCAN_WORKERS = 8
_FAILED_ENGINE_VERSION_STATES = frozenset(
    {
        EngineState.SCAN_TIMEOUT.value,
        EngineState.DATABASE_STALE.value,
        EngineState.DATABASE_ERROR.value,
        EngineState.ENGINE_ERROR.value,
    }
)
_NONCACHEABLE_ENGINE_VERSION_STATES = _FAILED_ENGINE_VERSION_STATES | {
    EngineState.SCANNER_UNAVAILABLE.value,
}


class _FileChangedDuringScan(RuntimeError):
    pass


class _ScanSnapshotUnavailable(RuntimeError):
    pass


class _ScanTargetTooLarge(ValueError):
    pass


_HASH_POLICY = threading.local()


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
def _create_scan_snapshot(
    path: Path,
    root: Path,
    *,
    max_bytes: int = MAX_SCAN_TARGET_BYTES,
    expected_size: int | None = None,
    expected_identity: FileIdentity | None = None,
) -> Iterator[_ScanSnapshot]:
    try:
        _assert_path_has_no_reparse_components(path)
        before = path.stat(follow_symlinks=False)
        source_size = int(before.st_size)
        source_identity = _stat_identity(before)
        if source_size < 0 or source_size > max_bytes:
            raise _ScanTargetTooLarge("scan_target_too_large")
        if expected_size is not None and source_size != expected_size:
            raise _FileChangedDuringScan
        if expected_identity is not None and source_identity != expected_identity:
            raise _FileChangedDuringScan
        if is_reparse_point(path) or not stat.S_ISREG(before.st_mode):
            raise _FileChangedDuringScan
        directory = _create_private_snapshot_directory(root)
        _assert_path_has_no_reparse_components(directory)
    except Exception as exc:
        if isinstance(exc, (_FileChangedDuringScan, _ScanTargetTooLarge)):
            raise
        raise _ScanSnapshotUnavailable from exc

    snapshot_path = directory / path.name
    handle: object | None = None
    try:
        try:
            handle = _create_scan_snapshot_handle(snapshot_path)
            _assert_path_has_no_reparse_components(snapshot_path)
            digest = hashlib.sha256()
            _assert_path_has_no_reparse_components(path)
            with path.open("rb") as source:
                _assert_path_has_no_reparse_components(path)
                opened = os.fstat(source.fileno())
                if _stat_identity(opened) != source_identity:
                    raise _FileChangedDuringScan
                remaining = source_size
                while remaining:
                    chunk = source.read(min(1024 * 1024, remaining))
                    if not chunk:
                        raise _FileChangedDuringScan
                    digest.update(chunk)
                    remaining -= len(chunk)
                    _write_snapshot_chunk(handle, chunk)
                read_after = os.fstat(source.fileno())
            _assert_path_has_no_reparse_components(path)
            after = path.stat(follow_symlinks=False)
            identities = {
                _stat_identity(item)
                for item in (before, opened, read_after, after)
            }
            if len(identities) != 1 or (expected_identity is not None and _stat_identity(after) != expected_identity):
                raise _FileChangedDuringScan
            _flush_snapshot(handle)
            if sys.platform != "win32":
                os.chmod(snapshot_path, 0o400)
            sha256 = digest.hexdigest()
            snapshot_sha256, snapshot_size, snapshot_identity = _hash_with_policy(
                snapshot_path,
                max_bytes=max_bytes,
                expected_size=source_size,
            )
            if (snapshot_sha256, snapshot_size) != (sha256, source_size):
                raise _ScanSnapshotUnavailable
            snapshot = _ScanSnapshot(
                snapshot_path,
                sha256,
                source_size,
                _stat_identity(after),
                snapshot_identity,
            )
        except _FileChangedDuringScan:
            raise
        except Exception as exc:
            raise _ScanSnapshotUnavailable from exc

        yield snapshot

        try:
            snapshot_after = _hash_with_policy(
                snapshot_path,
                max_bytes=max_bytes,
                expected_size=snapshot.size,
            )
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


def _assert_path_has_no_reparse_components(path: Path) -> None:
    try:
        checked = absolute_path_without_reparse(path)
    except (OSError, RuntimeError, ValueError) as exc:
        raise _FileChangedDuringScan from exc
    if os.path.normcase(str(checked)) != os.path.normcase(str(path)):
        raise _FileChangedDuringScan


def _engine_version_findings(versions: dict[str, str]) -> tuple[list[Finding], set[str]]:
    findings: list[Finding] = []
    unavailable_engines: set[str] = set()
    version_states = _NONCACHEABLE_ENGINE_VERSION_STATES
    states_by_value = {state.value: state for state in EngineState}
    for name, version in versions.items():
        if version not in version_states:
            continue
        state = states_by_value.get(version, EngineState.ENGINE_ERROR)
        unavailable_engines.add(name)
        findings.append(
            Finding(
                name,
                "engine_version_unavailable",
                0,
                state,
                {"reported_state": version},
            )
        )
    return findings, unavailable_engines


def hash_stable_file(path: Path) -> tuple[str, int, FileIdentity]:
    policy = getattr(_HASH_POLICY, "current", None)
    max_bytes, expected_size, expected_identity = policy if policy is not None else (None, None, None)
    _assert_path_has_no_reparse_components(path)
    before = path.stat(follow_symlinks=False)
    size = int(before.st_size)
    if max_bytes is not None and (size < 0 or size > max_bytes):
        raise _ScanTargetTooLarge("scan_target_too_large")
    if expected_size is not None and size != expected_size:
        raise RuntimeError("file changed during scan")
    before_identity = _stat_identity(before)
    if expected_identity is not None and before_identity != expected_identity:
        raise RuntimeError("file changed during scan")
    if is_reparse_point(path) or not stat.S_ISREG(before.st_mode):
        raise RuntimeError("file changed during scan")
    digest = hashlib.sha256()
    _assert_path_has_no_reparse_components(path)
    with path.open("rb") as handle:
        _assert_path_has_no_reparse_components(path)
        opened = os.fstat(handle.fileno())
        if _stat_identity(opened) != before_identity:
            raise RuntimeError("file changed during scan")
        remaining = size
        while remaining:
            chunk = handle.read(min(1024 * 1024, remaining))
            if not chunk:
                raise RuntimeError("file changed during scan")
            digest.update(chunk)
            remaining -= len(chunk)
        read_after = os.fstat(handle.fileno())
    _assert_path_has_no_reparse_components(path)
    after = path.stat(follow_symlinks=False)
    identities = {_stat_identity(item) for item in (before, opened, read_after, after)}
    if len(identities) != 1 or (expected_identity is not None and _stat_identity(after) != expected_identity):
        raise RuntimeError("file changed during scan")
    return digest.hexdigest(), int(after.st_size), _stat_identity(after)


def _hash_with_policy(
    path: Path,
    *,
    max_bytes: int,
    expected_size: int | None = None,
    expected_identity: FileIdentity | None = None,
) -> tuple[str, int, FileIdentity]:
    previous = getattr(_HASH_POLICY, "current", None)
    _HASH_POLICY.current = (max_bytes, expected_size, expected_identity)
    try:
        return hash_stable_file(path)
    finally:
        if previous is None:
            del _HASH_POLICY.current
        else:
            _HASH_POLICY.current = previous


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
        self.engines = (
            HashReputationEngine(self.store),
            ClamAVEngine(timeout, self.store.root / "feeds" / "clamav" / "current"),
            YaraEngine(yara_rules, timeout=timeout),
            StaticHeuristicsEngine(),
        )
        self._vault: QuarantineVault | None = None
        self._vault_lock = threading.Lock()
        self._scan_identity = threading.local()

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
        expected_identity = getattr(self._scan_identity, "identity", None)
        return _hash_with_policy(
            path,
            max_bytes=MAX_SCAN_TARGET_BYTES,
            expected_identity=expected_identity,
        )

    @staticmethod
    def _boundary_failure(path: Path, error: str, size: int = 0) -> ScanResult:
        return ScanResult(
            str(path),
            "",
            max(0, size),
            Verdict.SCAN_ERROR,
            0,
            "blocked_pending_review",
            (),
            {},
            error=error,
        )

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
        try:
            path = absolute_path_without_reparse(candidate)
        except ReparsePathError:
            return self._boundary_failure(Path(candidate), "reparse_point_rejected")
        except (OSError, RuntimeError, ValueError):
            return self._boundary_failure(Path(candidate), "candidate_unresolved")
        try:
            metadata = path.stat(follow_symlinks=False)
        except OSError:
            return self._boundary_failure(path, "candidate_unavailable")
        if is_reparse_point(path):
            return self._boundary_failure(path, "reparse_point_rejected")
        if not stat.S_ISREG(metadata.st_mode):
            return self._boundary_failure(path, "scan_target_not_file")
        size_hint = int(metadata.st_size)
        if size_hint < 0 or size_hint > MAX_SCAN_TARGET_BYTES:
            return self._boundary_failure(path, "scan_target_too_large", size_hint)
        identity_hint = _stat_identity(metadata)
        reservation = reserve_snapshot_bytes(size_hint, MAX_ACTIVE_SCAN_BYTES)
        if reservation is None:
            return self._boundary_failure(path, "scan_budget_exceeded", size_hint)
        previous_identity = getattr(self._scan_identity, "identity", None)
        self._scan_identity.identity = identity_hint
        try:
            with reservation:
                return self._scan_file_reserved(
                    path,
                    quarantine=quarantine,
                    use_cache=use_cache,
                    size_hint=size_hint,
                    identity_hint=identity_hint,
                )
        finally:
            if previous_identity is None:
                del self._scan_identity.identity
            else:
                self._scan_identity.identity = previous_identity

    def _scan_file_reserved(
        self,
        path: Path,
        *,
        quarantine: bool,
        use_cache: bool,
        size_hint: int,
        identity_hint: FileIdentity,
    ) -> ScanResult:
        try:
            sha256, size, identity = self._hash_stable(path)
        except _ScanTargetTooLarge:
            return self._boundary_failure(path, "scan_target_too_large", size_hint)
        except (OSError, RuntimeError) as exc:
            error = "file_changed_during_scan" if isinstance(exc, RuntimeError) else str(exc)
            return replace(self._boundary_failure(path, error, size_hint), engine_versions=self.versions())
        if size != size_hint or identity != identity_hint:
            return replace(self._boundary_failure(path, "file_changed_during_scan", size_hint), engine_versions=self.versions())
        snapshot = (sha256, size, identity)
        versions = self.versions()
        cache_key = versions_cache_key(versions)
        if use_cache and not _engine_version_findings(versions)[1]:
            cached = self.store.cache_get(sha256, cache_key)
            if cached is not None and cached.engine_health == EngineHealth.HEALTHY:
                try:
                    after_cache_read = self._hash_stable(path)
                except (OSError, RuntimeError, ValueError):
                    return self._changed_file_result(path, versions)
                if after_cache_read != snapshot or cached.sha256 != sha256:
                    return self._changed_file_result(path, versions)
                verified_versions = self.versions()
                if verified_versions == versions and not _engine_version_findings(verified_versions)[1]:
                    decision = evaluate(list(cached.findings), self.store.is_allowed(sha256, str(path)))
                    cached = replace(
                        cached,
                        path=str(path),
                        verdict=decision.verdict,
                        score=decision.score,
                        action=decision.action,
                        error=decision.error,
                        engine_versions=verified_versions,
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
                versions = verified_versions
                cache_key = versions_cache_key(versions)
        findings, unavailable_engines = _engine_version_findings(versions)
        try:
            with _create_scan_snapshot(
                path,
                self.store.root,
                max_bytes=MAX_SCAN_TARGET_BYTES,
                expected_size=size_hint,
                expected_identity=identity_hint,
            ) as scan_snapshot:
                if (
                    scan_snapshot.sha256,
                    scan_snapshot.size,
                    scan_snapshot.source_identity,
                ) != snapshot:
                    raise _FileChangedDuringScan
                for engine in self.engines:
                    if engine.name in unavailable_engines:
                        continue
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
        except _ScanTargetTooLarge:
            return self._boundary_failure(path, "scan_target_too_large", size_hint)
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
        if decision.engine_health == EngineHealth.HEALTHY:
            self.store.record_scan(result, cache_key)
        else:
            self.store.event(
                "detection",
                result.path,
                result.verdict.value,
                result.action,
                {
                    "sha256": result.sha256,
                    "score": result.score,
                    "findings": [
                        {"source": item.source, "name": item.name, "state": item.state.value}
                        for item in result.findings
                    ],
                },
            )
        return result

    def scan_paths(self, paths: Iterable[Path | str], workers: int | None = None, quarantine: bool = True) -> list[ScanResult]:
        files: list[Path] = []
        requested_paths: list[str] = []
        incomplete_paths: list[Path] = []
        inventory = DirectoryWalkReport()
        root_count = 0
        for item in paths:
            if root_count >= MAX_SCAN_ROOTS:
                inventory.mark("root_limit")
                incomplete_paths.append(Path(item))
                break
            root_count += 1
            try:
                path = absolute_path_without_reparse(item)
            except ReparsePathError:
                requested_paths.append(str(item))
                inventory.mark("root_reparse_point")
                incomplete_paths.append(Path(item))
                continue
            except OSError:
                requested_paths.append(str(item))
                inventory.mark("root_stat_error", error=True)
                incomplete_paths.append(Path(item))
                continue
            requested_paths.append(str(path))
            try:
                metadata = path.stat(follow_symlinks=False)
            except OSError:
                inventory.mark("root_stat_error", error=True)
                incomplete_paths.append(path)
                continue
            if is_reparse_point(path):
                inventory.mark("root_reparse_point")
                incomplete_paths.append(path)
            elif stat.S_ISREG(metadata.st_mode):
                if len(files) >= MAX_SCAN_FILES:
                    inventory.mark("file_limit")
                    incomplete_paths.append(path)
                else:
                    files.append(path)
                    inventory.files += 1
                continue
            elif not stat.S_ISDIR(metadata.st_mode):
                continue
            if len(files) >= MAX_SCAN_FILES:
                inventory.mark("file_limit")
                incomplete_paths.append(path)
                continue
            root_inventory = DirectoryWalkReport()
            remaining = MAX_SCAN_FILES - len(files)
            discovered = iter_regular_files(
                path,
                root_inventory,
                max_files=remaining,
                max_entries=max(0, MAX_WALK_ENTRIES - inventory.entries),
                max_directories=max(0, MAX_WALK_DIRECTORIES - inventory.directories),
                max_depth=MAX_WALK_DEPTH,
                is_reparse=is_reparse_point,
            )
            files.extend(discovered)
            inventory.entries += root_inventory.entries
            inventory.files += root_inventory.files
            inventory.directories += root_inventory.directories
            inventory.errors += root_inventory.errors
            for reason in root_inventory.reasons:
                inventory.mark(reason)
            if not root_inventory.complete:
                incomplete_paths.append(path)
        self.store.event(
            "scan_requested",
            f"{len(requested_paths)} path(s)",
            None,
            "requested",
            {
                "paths": requested_paths,
                "files_discovered": len(files),
                "quarantine": quarantine,
                "inventory_complete": inventory.complete,
                "inventory_reason": inventory.truncated_reason,
            },
        )
        maximum = max(1, min(int(workers or self.config.get("max_workers", 4)), MAX_SCAN_WORKERS))
        results: list[ScanResult] = []
        with ThreadPoolExecutor(max_workers=maximum, thread_name_prefix="hermes-security") as pool:
            file_iterator = iter(files)
            futures = {}
            max_pending = max(1, maximum * MAX_SCAN_FUTURES_MULTIPLIER)
            while len(futures) < max_pending:
                try:
                    path = next(file_iterator)
                except StopIteration:
                    break
                futures[pool.submit(self.scan_file, path, quarantine)] = path
            while futures:
                completed, _pending = wait(tuple(futures), return_when=FIRST_COMPLETED)
                for future in completed:
                    path = futures.pop(future)
                    try:
                        results.append(future.result())
                    except Exception as exc:
                        results.append(ScanResult(str(path), "", 0, Verdict.SCAN_ERROR, 0, "blocked_pending_review", (), self.versions(), error=str(exc)))
                try:
                    while len(futures) < max_pending:
                        path = next(file_iterator)
                        futures[pool.submit(self.scan_file, path, quarantine)] = path
                except StopIteration:
                    pass
        for path in incomplete_paths:
            results.append(self._boundary_failure(path, "directory_scan_incomplete"))
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
