from __future__ import annotations

import hashlib
import os
import stat
from dataclasses import dataclass
from pathlib import Path

from .bounded_walk import ReparsePathError, absolute_path_without_reparse


MAX_DEFINITION_DIRECTORY_ENTRIES = 512
MAX_DEFINITION_FILES = 32
MAX_DEFINITION_FILE_BYTES = 1024 * 1024 * 1024
MAX_DEFINITION_TOTAL_BYTES = 2 * 1024 * 1024 * 1024
DEFINITION_HASH_CHUNK_BYTES = 1024 * 1024

# ClamAV's documented database formats, including signature, configuration,
# allow/ignore, YARA, and auxiliary database files. freshclam.dat is updater
# state and is not a libclamav detection definition.
CLAMAV_DEFINITION_SUFFIXES = frozenset(
    {
        ".cvd", ".cld", ".cfg", ".cat", ".crb", ".ftm", ".ndb", ".ndu",
        ".ldb", ".ldu", ".idb", ".cdb", ".cbc", ".pdb", ".gdb", ".wdb",
        ".hdb", ".hsb", ".hdu", ".hsu", ".mdb", ".msb", ".mdu", ".msu",
        ".yar", ".yara", ".fp", ".sfp", ".ign", ".ign2", ".pwdb", ".info",
        ".imp",
    }
)
CLAMAV_ARCHIVE_SUFFIXES = frozenset({".cvd", ".cld"})
_UPDATER_STATE_NAMES = frozenset({"freshclam.dat"})


class DefinitionInventoryError(ValueError):
    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


@dataclass(frozen=True)
class DefinitionFile:
    path: Path
    name: str
    suffix: str
    size: int
    sha256: str


@dataclass(frozen=True)
class DefinitionInventory:
    root: Path
    files: tuple[DefinitionFile, ...]
    revision: str
    total_bytes: int

    @property
    def archives(self) -> tuple[DefinitionFile, ...]:
        return tuple(item for item in self.files if item.suffix in CLAMAV_ARCHIVE_SUFFIXES)


def _identity(metadata: os.stat_result) -> tuple[int, int, int, int, int]:
    return (
        int(metadata.st_dev),
        int(metadata.st_ino),
        int(metadata.st_size),
        int(metadata.st_mtime_ns),
        int(metadata.st_ctime_ns),
    )


def _directory_identity(metadata: os.stat_result) -> tuple[int, int, int]:
    # On Windows, directory ctime can change as a result of metadata reads.
    # Device, file ID, and mtime still detect replacement and entry changes.
    return (int(metadata.st_dev), int(metadata.st_ino), int(metadata.st_mtime_ns))


def _is_reparse(metadata: os.stat_result) -> bool:
    flag = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0)
    return stat.S_ISLNK(metadata.st_mode) or bool(
        flag and getattr(metadata, "st_file_attributes", 0) & flag
    )


def _definition_digest(path: Path, expected_identity: tuple[int, int, int, int, int]) -> str:
    digest = hashlib.sha256()
    try:
        before = path.stat(follow_symlinks=False)
        if _is_reparse(before) or not stat.S_ISREG(before.st_mode):
            raise DefinitionInventoryError("invalid_definition_file")
        if _identity(before) != expected_identity:
            raise DefinitionInventoryError("definition_changed_during_inventory")
        with path.open("rb") as handle:
            opened = os.fstat(handle.fileno())
            if _is_reparse(opened) or _identity(opened) != expected_identity:
                raise DefinitionInventoryError("definition_changed_during_inventory")
            remaining = int(before.st_size)
            while remaining:
                chunk = handle.read(min(DEFINITION_HASH_CHUNK_BYTES, remaining))
                if not chunk:
                    raise DefinitionInventoryError("definition_changed_during_inventory")
                digest.update(chunk)
                remaining -= len(chunk)
            read_after = os.fstat(handle.fileno())
        after = path.stat(follow_symlinks=False)
    except DefinitionInventoryError:
        raise
    except (OSError, ValueError) as exc:
        raise DefinitionInventoryError("definition_unavailable") from exc
    if any(_identity(item) != expected_identity for item in (read_after, after)):
        raise DefinitionInventoryError("definition_changed_during_inventory")
    return digest.hexdigest()


def inventory_clamav_definitions(
    directory: Path,
    *,
    max_entries: int | None = None,
    max_files: int | None = None,
    max_file_bytes: int | None = None,
    max_total_bytes: int | None = None,
) -> DefinitionInventory:
    """Build a bounded content identity for every supported ClamAV database file."""
    entry_limit = MAX_DEFINITION_DIRECTORY_ENTRIES if max_entries is None else max_entries
    file_limit = MAX_DEFINITION_FILES if max_files is None else max_files
    per_file_limit = MAX_DEFINITION_FILE_BYTES if max_file_bytes is None else max_file_bytes
    total_limit = MAX_DEFINITION_TOTAL_BYTES if max_total_bytes is None else max_total_bytes
    try:
        root = absolute_path_without_reparse(directory)
        root_before = root.stat(follow_symlinks=False)
    except FileNotFoundError as exc:
        raise DefinitionInventoryError("definition_directory_missing") from exc
    except (OSError, ReparsePathError) as exc:
        raise DefinitionInventoryError("definition_directory_unavailable") from exc
    if _is_reparse(root_before) or not stat.S_ISDIR(root_before.st_mode):
        raise DefinitionInventoryError("invalid_definition_directory")

    try:
        entries = os.scandir(root)
    except OSError as exc:
        raise DefinitionInventoryError("definition_directory_unavailable") from exc

    candidates: list[tuple[Path, str, str, int, tuple[int, int, int, int, int]]] = []
    seen_entries = 0
    total_bytes = 0
    try:
        with entries:
            for entry in entries:
                seen_entries += 1
                if seen_entries > entry_limit:
                    raise DefinitionInventoryError("definition_entry_limit")
                path = root / entry.name
                try:
                    entry_metadata = entry.stat(follow_symlinks=False)
                    path_metadata = path.stat(follow_symlinks=False)
                except OSError as exc:
                    raise DefinitionInventoryError("definition_unavailable") from exc
                if _is_reparse(entry_metadata) or _is_reparse(path_metadata):
                    raise DefinitionInventoryError("definition_reparse_point")
                if not stat.S_ISREG(path_metadata.st_mode):
                    raise DefinitionInventoryError("unsupported_definition_entry")
                if entry.name.casefold() in _UPDATER_STATE_NAMES:
                    continue
                suffix = path.suffix.casefold()
                if suffix not in CLAMAV_DEFINITION_SUFFIXES:
                    raise DefinitionInventoryError("unsupported_definition_entry")
                if len(candidates) >= file_limit:
                    raise DefinitionInventoryError("definition_file_limit")
                size = int(path_metadata.st_size)
                if size < 0 or size > per_file_limit:
                    raise DefinitionInventoryError("definition_file_size_limit")
                total_bytes += size
                if total_bytes > total_limit:
                    raise DefinitionInventoryError("definition_total_size_limit")
                candidates.append((path, entry.name, suffix, size, _identity(path_metadata)))
    except DefinitionInventoryError:
        raise
    except OSError as exc:
        raise DefinitionInventoryError("definition_directory_unavailable") from exc

    try:
        root_after = root.stat(follow_symlinks=False)
    except OSError as exc:
        raise DefinitionInventoryError("definition_directory_unavailable") from exc
    if _directory_identity(root_after) != _directory_identity(root_before):
        raise DefinitionInventoryError("definition_directory_changed")

    files: list[DefinitionFile] = []
    for path, name, suffix, size, identity in sorted(candidates, key=lambda item: item[1].casefold()):
        files.append(DefinitionFile(path, name, suffix, size, _definition_digest(path, identity)))

    revision_digest = hashlib.sha256()
    for item in files:
        revision_digest.update(item.name.casefold().encode("utf-8"))
        revision_digest.update(b"\0")
        revision_digest.update(str(item.size).encode("ascii"))
        revision_digest.update(b"\0")
        revision_digest.update(item.sha256.encode("ascii"))
        revision_digest.update(b"\n")
    return DefinitionInventory(root, tuple(files), revision_digest.hexdigest(), total_bytes)
