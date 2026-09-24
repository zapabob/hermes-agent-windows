from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import re
import shutil
import subprocess
import stat
from pathlib import Path
from typing import Any, Iterable

from hermes_constants import get_hermes_home

from .bounded_process import BoundedProcessOutputError, run_bounded
from .bounded_walk import ReparsePathError, absolute_path_without_reparse
from .clamav_definitions import (
    DefinitionInventory,
    DefinitionInventoryError,
    MAX_DEFINITION_DIRECTORY_ENTRIES,
    MAX_DEFINITION_FILE_BYTES,
    MAX_DEFINITION_FILES,
    MAX_DEFINITION_TOTAL_BYTES,
    inventory_clamav_definitions,
)
from .models import EngineState, Finding
from .store import SecurityStore


MAX_CLAMAV_TIMEOUT_SECONDS = 120
MAX_SCANNER_OUTPUT_BYTES = 16 * 1024
MAX_CLAMAV_DATABASE_ENTRIES = MAX_DEFINITION_DIRECTORY_ENTRIES
MAX_CLAMAV_DATABASE_FILES = MAX_DEFINITION_FILES
MAX_CLAMAV_DATABASE_FILE_BYTES = MAX_DEFINITION_FILE_BYTES
MAX_CLAMAV_DATABASE_TOTAL_BYTES = MAX_DEFINITION_TOTAL_BYTES
MAX_YARA_RULE_FILES = 128
MAX_YARA_MATCHES = 128
MAX_YARA_DIRECTORY_ENTRIES = 512
MAX_YARA_RULE_BYTES = 256 * 1024
MAX_YARA_TOTAL_BYTES = 4 * 1024 * 1024


class HashReputationEngine:
    name = "hash_reputation"

    def __init__(self, store: SecurityStore) -> None:
        self.store = store

    def version(self) -> str:
        return self.store.feed_versions().get("hash_reputation", "empty")

    def scan(self, _path: Path, sha256: str) -> list[Finding]:
        row = self.store.lookup_hash(sha256)
        if row is None:
            return []
        family = row["malware_family"] or row["label"]
        return [
            Finding(
                self.name,
                family,
                100,
                details={"source": row["source"], "confidence": int(row["confidence"])},
            )
        ]


class ClamAVEngine:
    name = "clamav"

    def __init__(
        self,
        timeout: int = 30,
        database_dir: Path | None = None,
        database_revision: str = "empty",
    ) -> None:
        self.timeout = max(1, min(int(timeout), MAX_CLAMAV_TIMEOUT_SECONDS))
        self.clamscan_command = shutil.which("clamscan")
        # Use clamscan so the explicit managed database identity is the database scanned.
        self.command = self.clamscan_command
        self.database_revision = str(database_revision)[:128]
        configured = os.environ.get("CLAMAV_DATABASE_DIR")
        configured_dir = Path(configured) if configured else None
        if database_dir is not None:
            self.database_dir = database_dir
        elif configured_dir is not None:
            self.database_dir = configured_dir
        else:
            self.database_dir = None

    def version(self) -> str:
        if not self.command:
            return EngineState.SCANNER_UNAVAILABLE.value
        try:
            executable = Path(self.command).stat(follow_symlinks=False)
        except OSError:
            return EngineState.ENGINE_ERROR.value
        if not stat.S_ISREG(executable.st_mode) or self._metadata_is_reparse(executable):
            return EngineState.ENGINE_ERROR.value
        database_identity = self._database_identity()
        if database_identity.startswith("database-"):
            return EngineState.ENGINE_ERROR.value
        identity = "\0".join(
            (
                os.path.normcase(os.path.abspath(self.command)),
                str(executable.st_size),
                str(executable.st_mtime_ns),
                str(getattr(executable, "st_dev", 0)),
                str(getattr(executable, "st_ino", 0)),
                str(getattr(executable, "st_ctime_ns", 0)),
                self.database_revision,
                database_identity,
            )
        )
        return f"binary-id-{hashlib.sha256(identity.encode('utf-8')).hexdigest()[:20]}"

    @staticmethod
    def _metadata_is_reparse(metadata: os.stat_result) -> bool:
        reparse_flag = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0)
        return stat.S_ISLNK(metadata.st_mode) or bool(
            reparse_flag and getattr(metadata, "st_file_attributes", 0) & reparse_flag
        )

    def _definition_inventory(self) -> DefinitionInventory:
        if self.database_dir is None:
            raise DefinitionInventoryError("definition_directory_missing")
        return inventory_clamav_definitions(
            self.database_dir,
            max_entries=MAX_CLAMAV_DATABASE_ENTRIES,
            max_files=MAX_CLAMAV_DATABASE_FILES,
            max_file_bytes=MAX_CLAMAV_DATABASE_FILE_BYTES,
            max_total_bytes=MAX_CLAMAV_DATABASE_TOTAL_BYTES,
        )

    def _database_identity(self) -> str:
        try:
            inventory = self._definition_inventory()
        except DefinitionInventoryError as exc:
            return f"database-{exc.reason}"
        return f"{os.path.normcase(str(inventory.root))}:{inventory.revision}"

    def scan(self, path: Path, _sha256: str) -> list[Finding]:
        if not self.command:
            return [Finding(self.name, "ClamAV unavailable", 0, EngineState.SCANNER_UNAVAILABLE)]
        try:
            database_inventory = self._definition_inventory()
        except DefinitionInventoryError as exc:
            reason_map = {
                "definition_entry_limit": "database-entry-limit",
                "definition_file_limit": "database-file-limit",
                "definition_file_size_limit": "database-file-limit",
                "definition_total_size_limit": "database-total-limit",
                "definition_reparse_point": "database-reparse-point",
            }
            return [
                Finding(
                    self.name,
                    "ClamAV definitions unavailable",
                    0,
                    EngineState.ENGINE_ERROR,
                    {"reason": reason_map.get(exc.reason, "database-invalid-entry")},
                )
            ]
        arguments = [
            self.command,
            f"--database={database_inventory.root}",
            "--max-filesize=1024M",
            "--max-scansize=2048M",
            "--max-files=10000",
            "--max-recursion=17",
            "--alert-exceeds-max=yes",
            "--no-summary",
            str(path),
        ]
        try:
            result = run_bounded(
                arguments,
                timeout=self.timeout,
                max_output_bytes_per_stream=MAX_SCANNER_OUTPUT_BYTES,
            )
        except subprocess.TimeoutExpired:
            return [Finding(self.name, "ClamAV timeout", 0, EngineState.SCAN_TIMEOUT)]
        except BoundedProcessOutputError as exc:
            return [Finding(self.name, "ClamAV output incomplete", 0, EngineState.ENGINE_ERROR, {"reason": exc.reason})]
        except (OSError, subprocess.SubprocessError) as exc:
            return [Finding(self.name, "ClamAV error", 0, EngineState.ENGINE_ERROR, {"error": type(exc).__name__})]
        if result.output_truncated:
            return [Finding(self.name, "ClamAV output incomplete", 0, EngineState.ENGINE_ERROR)]
        try:
            current_inventory = self._definition_inventory()
        except DefinitionInventoryError:
            return [Finding(self.name, "ClamAV definitions changed during scan", 0, EngineState.ENGINE_ERROR)]
        if current_inventory != database_inventory:
            return [Finding(self.name, "ClamAV definitions changed during scan", 0, EngineState.ENGINE_ERROR)]
        output = "\n".join(part for part in (result.stdout, result.stderr) if part)
        if "Heuristics.Limits.Exceeded" in output:
            return [Finding(self.name, "ClamAV scan limit exceeded", 0, EngineState.ENGINE_ERROR)]
        if result.returncode == 0:
            return [Finding(self.name, "no_detection", 0)]
        if result.returncode == 1:
            match = re.search(r":\s*(.+?)\s+FOUND\s*$", output, re.MULTILINE)
            return [Finding(self.name, match.group(1)[:160] if match else "ClamAV detection", 90)]
        return [Finding(self.name, "ClamAV scan error", 0, EngineState.ENGINE_ERROR, {"exit_code": result.returncode})]


class YaraEngine:
    name = "yara"

    def __init__(self, rules_dir: Path | None = None, timeout: int = 30) -> None:
        self.rules_dir = rules_dir or (get_hermes_home() / "security" / "feeds" / "yara")
        self.timeout = max(1, timeout)
        self._compiled = None
        self._compile_errors: list[str] = []
        self._files: list[Path] = []
        self._inventory_error: str | None = None
        self._inventory_revision: str | None = None
        self._compiled_revision: str | None = None

    @staticmethod
    def _identity(metadata: os.stat_result) -> tuple[int, int, int, int, int]:
        return (
            int(metadata.st_dev),
            int(metadata.st_ino),
            int(metadata.st_size),
            int(metadata.st_mtime_ns),
            int(metadata.st_ctime_ns),
        )

    @staticmethod
    def _metadata_is_reparse(metadata: os.stat_result) -> bool:
        reparse_flag = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0)
        return stat.S_ISLNK(metadata.st_mode) or bool(
            reparse_flag and getattr(metadata, "st_file_attributes", 0) & reparse_flag
        )

    def _read_inventory(self) -> tuple[dict[str, str], str | None, str | None]:
        sources: dict[str, str] = {}
        revision = hashlib.sha256()
        total_bytes = 0
        self._files = []
        try:
            rules_root = absolute_path_without_reparse(self.rules_dir)
            root_metadata = rules_root.stat(follow_symlinks=False)
            if self._metadata_is_reparse(root_metadata) or not stat.S_ISDIR(root_metadata.st_mode):
                return sources, "rule_directory_invalid", None
            entries = os.scandir(rules_root)
        except FileNotFoundError:
            return sources, None, None
        except ReparsePathError:
            return sources, "rule_directory_invalid", None
        except OSError:
            return sources, "rule_directory_error", None
        try:
            with entries:
                for index, entry in enumerate(entries):
                    if index >= MAX_YARA_DIRECTORY_ENTRIES:
                        return {}, "rule_inventory_limit", None
                    suffix = Path(entry.name).suffix.casefold()
                    if suffix not in {".yar", ".yara"}:
                        continue
                    if len(self._files) >= MAX_YARA_RULE_FILES:
                        return {}, "rule_file_limit", None
                    path = rules_root / entry.name
                    try:
                        metadata = path.stat(follow_symlinks=False)
                    except OSError:
                        return {}, "rule_file_error", None
                    if self._metadata_is_reparse(metadata) or not stat.S_ISREG(metadata.st_mode):
                        return {}, "rule_file_invalid", None
                    size = int(metadata.st_size)
                    if size < 0 or size > MAX_YARA_RULE_BYTES:
                        return {}, "rule_size_limit", None
                    total_bytes += size
                    if total_bytes > MAX_YARA_TOTAL_BYTES:
                        return {}, "rule_total_size_limit", None
                    try:
                        digest = hashlib.sha256()
                        content = bytearray()
                        with path.open("rb") as handle:
                            opened = os.fstat(handle.fileno())
                            if self._identity(opened) != self._identity(metadata):
                                return {}, "rule_file_changed", None
                            remaining = size
                            while remaining:
                                chunk = handle.read(min(64 * 1024, remaining))
                                if not chunk:
                                    return {}, "rule_file_changed", None
                                content.extend(chunk)
                                digest.update(chunk)
                                remaining -= len(chunk)
                            after_handle = os.fstat(handle.fileno())
                        after_path = path.stat(follow_symlinks=False)
                    except (OSError, ValueError):
                        return {}, "rule_file_error", None
                    expected_identity = self._identity(metadata)
                    if any(
                        self._identity(item) != expected_identity
                        for item in (after_handle, after_path)
                    ):
                        return {}, "rule_file_changed", None
                    try:
                        source = bytes(content).decode("utf-8")
                    except UnicodeDecodeError:
                        return {}, "rule_encoding_error", None
                    self._files.append(path)
                    key = path.stem
                    if key.casefold() in {existing.casefold() for existing in sources}:
                        return {}, "rule_name_collision", None
                    sources[key] = source
                    revision.update(path.name.casefold().encode("utf-8"))
                    revision.update(b"\0")
                    revision.update(str(size).encode("ascii"))
                    revision.update(b"\0")
                    revision.update(digest.hexdigest().encode("ascii"))
                    revision.update(b"\n")
        except OSError:
            return {}, "rule_directory_error", None
        return sources, None, revision.hexdigest() if sources else None

    def _compile(self, sources: dict[str, str], revision: str) -> None:
        self._compile_errors = []
        self._compiled = None
        self._compiled_revision = None
        try:
            yara = importlib.import_module("yara")
        except Exception as exc:
            self._compile_errors.append(type(exc).__name__)
            self._compiled = None
            return
        valid_sources: dict[str, str] = {}
        for name, source in sources.items():
            try:
                yara.compile(source=source)
                valid_sources[name] = source
            except Exception as exc:
                self._compile_errors.append(f"{name}: {type(exc).__name__}")
        if not valid_sources:
            self._compiled = None
            return
        try:
            self._compiled = yara.compile(sources=valid_sources)
            self._compiled_revision = revision
        except Exception as exc:
            self._compile_errors.append(type(exc).__name__)
            self._compiled = None
            self._compiled_revision = None

    def version(self) -> str:
        sources, error, revision = self._read_inventory()
        self._inventory_error = error
        self._inventory_revision = revision
        if error is not None:
            self._compiled = None
            self._compiled_revision = None
            return EngineState.ENGINE_ERROR.value
        if not sources or importlib.util.find_spec("yara") is None:
            self._compiled = None
            self._compiled_revision = None
            return EngineState.SCANNER_UNAVAILABLE.value
        if self._compiled is not None and self._compiled_revision != revision:
            self._compiled = None
            self._compiled_revision = None
        return f"rules-{len(sources)}-{revision}"

    def scan(self, path: Path, _sha256: str) -> list[Finding]:
        sources, error, revision = self._read_inventory()
        if error is not None:
            self._compiled = None
            self._compiled_revision = None
            return [Finding(self.name, "YARA rule inventory incomplete", 0, EngineState.ENGINE_ERROR, {"reason": error})]
        if not sources:
            self._compiled = None
            self._compiled_revision = None
            return [Finding(self.name, "YARA unavailable", 0, EngineState.SCANNER_UNAVAILABLE)]
        if self._inventory_revision is not None and self._inventory_revision != revision:
            self._compiled = None
            self._compiled_revision = None
            return [Finding(self.name, "YARA rules changed during scan setup", 0, EngineState.ENGINE_ERROR)]
        if self._compiled is None or self._compiled_revision != revision:
            if importlib.util.find_spec("yara") is None:
                self._compiled = None
                self._compiled_revision = None
                return [Finding(self.name, "YARA unavailable", 0, EngineState.SCANNER_UNAVAILABLE)]
            self._compile(sources, revision)
        if self._compiled is None:
            details = {"compile_errors": self._compile_errors[:5]} if self._compile_errors else {}
            state = EngineState.ENGINE_ERROR if self._compile_errors else EngineState.SCANNER_UNAVAILABLE
            return [Finding(self.name, "YARA unavailable", 0, state, details)]
        try:
            matches = self._compiled.match(str(path), timeout=self.timeout)
        except Exception as exc:
            return [Finding(self.name, "YARA scan error", 0, EngineState.ENGINE_ERROR, {"error": type(exc).__name__})]
        findings: list[Finding] = []
        overflow = len(matches) > MAX_YARA_MATCHES
        for match in matches[:MAX_YARA_MATCHES]:
            meta = dict(match.meta or {})
            tier = str(meta.get("hermes_tier", "core")).lower()
            score = 60 if tier == "extended" else 80
            findings.append(Finding(self.name, str(match.rule), score, details={"tier": tier, "tags": list(match.tags)}))
        if not findings:
            findings.append(Finding(self.name, "no_detection", 0))
        if overflow:
            findings.append(
                Finding(
                    self.name,
                    "YARA result limit exceeded",
                    0,
                    EngineState.ENGINE_ERROR,
                    {"result_limit": MAX_YARA_MATCHES},
                )
            )
        if self._compile_errors:
            findings.append(
                Finding(
                    self.name,
                    "YARA rule compilation incomplete",
                    0,
                    EngineState.ENGINE_ERROR,
                    {"compile_errors": self._compile_errors[:5]},
                )
            )
        return findings


class StaticHeuristicsEngine:
    name = "static_heuristics"
    executable_suffixes = {".bat", ".cmd", ".com", ".cpl", ".dll", ".exe", ".hta", ".js", ".jse", ".lnk", ".msi", ".ps1", ".scr", ".vbe", ".vbs", ".wsf"}
    document_suffixes = {".doc", ".docm", ".docx", ".pdf", ".ppt", ".pptm", ".pptx", ".rtf", ".txt", ".xls", ".xlsm", ".xlsx"}
    macro_suffixes = {".docm", ".dotm", ".pptm", ".ppam", ".xlsm", ".xlam"}

    def version(self) -> str:
        return "heuristics-1"

    def scan(
        self,
        path: Path,
        _sha256: str,
        *,
        original_path: Path | None = None,
    ) -> list[Finding]:
        heuristic_path = original_path or path
        suffixes = [item.lower() for item in heuristic_path.suffixes]
        findings: list[Finding] = []
        if len(suffixes) >= 2 and suffixes[-2] in self.document_suffixes and suffixes[-1] in self.executable_suffixes:
            findings.append(Finding(self.name, "executable_double_extension", 20))
        if suffixes and suffixes[-1] in self.macro_suffixes:
            findings.append(Finding(self.name, "macro_enabled_document", 20))
        path_parts = {part.lower() for part in heuristic_path.parts}
        if suffixes and suffixes[-1] in self.executable_suffixes and ({"temp", "tmp", "downloads"} & path_parts):
            findings.append(Finding(self.name, "executable_in_transient_location", 20))
        try:
            with path.open("rb") as handle:
                header = handle.read(4)
        except OSError as exc:
            return [Finding(self.name, "static_read_error", 0, EngineState.ENGINE_ERROR, {"error": str(exc)})]
        if header.startswith(b"MZ") and (not suffixes or suffixes[-1] not in self.executable_suffixes):
            findings.append(Finding(self.name, "pe_disguised_as_non_executable", 20))
        return findings


def engine_versions(engines: Iterable[Any]) -> dict[str, str]:
    return {str(engine.name): str(engine.version()) for engine in engines}


def versions_cache_key(versions: dict[str, str]) -> str:
    return json.dumps(versions, sort_keys=True, separators=(",", ":"))
