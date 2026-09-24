from __future__ import annotations

import os
import stat
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Iterator


MAX_SCAN_ROOTS = 64
MAX_SCAN_FILES = 10_000
MAX_WALK_ENTRIES = 50_000
MAX_WALK_DIRECTORIES = 10_000
MAX_WALK_DEPTH = 64
MAX_WATCH_FILES = 10_000


class ReparsePathError(ValueError):
    """A requested path crosses a symlink or other reparse point."""


def stable_file_time_ns(metadata: os.stat_result, *, windows: bool = os.name == "nt") -> int:
    """Return the file timestamp that path stat and handle stat report identically."""
    # st_ctime is deprecated on Windows since Python 3.12 (os.stat_result docs):
    # path stat reports creation time while fstat reports metadata change time,
    # so only st_birthtime_ns is comparable across the two calls.
    if windows:
        birth = getattr(metadata, "st_birthtime_ns", None)
        if birth is not None:
            return int(birth)
    return int(metadata.st_ctime_ns)


def absolute_path_without_reparse(candidate: Path | str) -> Path:
    """Return a lexical absolute path after checking every existing component without following it."""
    path = Path(candidate).expanduser()
    if not path.is_absolute():
        path = Path.cwd() / path
    if ".." in path.parts:
        raise ReparsePathError("parent path components are not accepted")

    current = Path(path.anchor)
    parts = path.parts[1:]
    reparse_attribute = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0)
    for part in parts:
        if part in {"", "."}:
            continue
        current = current / part
        metadata = current.stat(follow_symlinks=False)
        attributes = getattr(metadata, "st_file_attributes", 0)
        if stat.S_ISLNK(metadata.st_mode) or (reparse_attribute and attributes & reparse_attribute):
            raise ReparsePathError("path crosses a reparse point")
    return current


@dataclass
class DirectoryWalkReport:
    entries: int = 0
    files: int = 0
    directories: int = 0
    errors: int = 0
    truncated_reason: str | None = None
    reasons: set[str] = field(default_factory=set)

    @property
    def complete(self) -> bool:
        return self.truncated_reason is None and self.errors == 0

    def mark(self, reason: str, *, error: bool = False) -> None:
        if error:
            self.errors += 1
        if self.truncated_reason is None:
            self.truncated_reason = reason
        if len(self.reasons) < 8:
            self.reasons.add(reason)


def iter_regular_files(
    root: Path,
    report: DirectoryWalkReport,
    *,
    max_files: int,
    max_entries: int = MAX_WALK_ENTRIES,
    max_directories: int = MAX_WALK_DIRECTORIES,
    max_depth: int = MAX_WALK_DEPTH,
    is_reparse: Callable[[Path], bool] | None = None,
) -> Iterator[Path]:
    """Yield regular files with explicit global limits and incomplete reporting."""
    try:
        root = absolute_path_without_reparse(root)
        root_metadata = root.stat(follow_symlinks=False)
    except ReparsePathError:
        report.mark("root_reparse_point")
        return
    except OSError:
        report.mark("root_stat_error", error=True)
        return
    root_attributes = getattr(root_metadata, "st_file_attributes", 0)
    if stat.S_ISLNK(root_metadata.st_mode) or root_attributes & getattr(
        stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0
    ):
        report.mark("root_reparse_point")
        return
    if not stat.S_ISDIR(root_metadata.st_mode):
        return
    pending: list[tuple[Path, int]] = [(root, 0)]
    report.directories += 1
    if max_directories < 1:
        report.mark("directory_limit")
        return

    while pending:
        directory, depth = pending.pop()
        try:
            directory = absolute_path_without_reparse(directory)
            entries = os.scandir(directory)
        except ReparsePathError:
            report.mark("reparse_point_skipped")
            continue
        except OSError:
            report.mark("directory_read_error", error=True)
            continue
        try:
            with entries:
                for entry in entries:
                    if report.entries >= max_entries:
                        report.mark("entry_limit")
                        return
                    report.entries += 1
                    path = Path(entry.path)
                    try:
                        metadata = entry.stat(follow_symlinks=False)
                    except OSError:
                        report.mark("entry_stat_error", error=True)
                        continue
                    attributes = getattr(metadata, "st_file_attributes", 0)
                    is_reparse_point = bool(
                        attributes & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0)
                    ) or stat.S_ISLNK(metadata.st_mode)
                    if not is_reparse_point and is_reparse is not None:
                        try:
                            is_reparse_point = bool(is_reparse(path))
                        except OSError:
                            report.mark("entry_stat_error", error=True)
                            continue
                    if is_reparse_point:
                        report.mark("reparse_point_skipped")
                        continue
                    if stat.S_ISDIR(metadata.st_mode):
                        if depth >= max_depth:
                            report.mark("depth_limit")
                            continue
                        if report.directories >= max_directories:
                            report.mark("directory_limit")
                            return
                        report.directories += 1
                        pending.append((path, depth + 1))
                        continue
                    if not stat.S_ISREG(metadata.st_mode):
                        continue
                    if report.files >= max_files:
                        report.mark("file_limit")
                        return
                    report.files += 1
                    yield path
        except OSError:
            report.mark("directory_read_error", error=True)
