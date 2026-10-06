"""Comparable file generations for path stat and open-handle fstat."""
from __future__ import annotations

import os
import sys

_IS_WINDOWS = sys.platform == "win32"


def stable_stat_identity(metadata: os.stat_result) -> tuple[int, int, int, int, int]:
    # Python 3.12 deprecates Windows ctime's creation-time meaning. Path
    # stat and fstat can already expose different ctime meanings; birthtime
    # is the explicit creation-time field. POSIX keeps metadata-change time.
    generation_time = (
        getattr(metadata, "st_birthtime_ns", metadata.st_ctime_ns)
        if _IS_WINDOWS else metadata.st_ctime_ns
    )
    return (int(metadata.st_dev), int(metadata.st_ino), int(metadata.st_size),
            int(metadata.st_mtime_ns), int(generation_time))
