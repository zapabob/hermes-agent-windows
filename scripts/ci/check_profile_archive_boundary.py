#!/usr/bin/env python3
"""Reject profile export archives before publication.

``.gitignore`` and ``.dockerignore`` are useful first-line filters, but both
can be bypassed (for example with ``git add -f`` or a non-standard build
context).  This check is the blocking, executable policy at the CI and image
publication boundaries.  It intentionally checks the filesystem rather than
Git's index so a generated archive cannot enter a build after checkout.
"""

from __future__ import annotations

import argparse
import hashlib
import os
from pathlib import Path

_PROFILE_ARCHIVE_SUFFIXES = (".tar.gz", ".tgz")

# Public npm source archive, reviewed alongside its unpacked source and checked
# byte-for-byte by tests-js/node-dependency-security.test.ts. A profile export
# cannot use this path: different bytes, size, directories and symlinks fail closed.
_REVIEWED_VENDOR_ARCHIVES = {
    "website/vendor/hermes-agent-minimatch-compat-1.0.0.tgz": (
        1942,
        "a1c829bac733a04ecffc08fac07c54460b104f960a6e15c983a38e62a7869eef",
    ),
}


def _is_reviewed_vendor_archive(path: Path, root: Path) -> bool:
    expected = _REVIEWED_VENDOR_ARCHIVES.get(path.relative_to(root).as_posix())
    if expected is None or path.is_symlink() or not path.is_file():
        return False
    size, digest = expected
    try:
        if path.stat().st_size != size:
            return False
        with path.open("rb") as archive:
            data = archive.read(size + 1)
        return len(data) == size and hashlib.sha256(data).hexdigest() == digest
    except OSError:
        return False


def find_forbidden_profile_archives(root: Path) -> list[Path]:
    """Return profile archive paths anywhere in the checkout."""
    root = root.resolve()
    if not root.is_dir():
        raise ValueError(f"repository root is not a directory: {root}")

    offenders: list[Path] = []
    for directory, dirnames, filenames in os.walk(root, followlinks=False):
        dirnames[:] = [
            name
            for name in dirnames
            if name not in {".git", ".venv", "venv", "node_modules", "__pycache__"}
        ]
        for name in (*dirnames, *filenames):
            if name.casefold().endswith(_PROFILE_ARCHIVE_SUFFIXES):
                archive = Path(directory) / name
                if not _is_reviewed_vendor_archive(archive, root):
                    offenders.append(archive.relative_to(root))

    return sorted(offenders, key=lambda path: path.as_posix().casefold())


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Reject profile export archives in the checkout."
    )
    parser.add_argument(
        "--root",
        type=Path,
        default=Path.cwd(),
        help="repository root to inspect (default: current directory)",
    )
    args = parser.parse_args(argv)

    try:
        offenders = find_forbidden_profile_archives(args.root)
    except ValueError as exc:
        parser.error(str(exc))

    if not offenders:
        print("No profile export archives detected in the checkout.")
        return 0

    print(
        "::error::profile export archives are forbidden "
        "in source and Docker build contexts"
    )
    for path in offenders:
        print(f"  {path.as_posix()}")
    print(
        "Move the archive outside the checkout or pass an explicit external "
        "output path to the profile export command."
    )
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
