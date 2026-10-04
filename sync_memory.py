#!/usr/bin/env python3
"""Compatibility shim for the unified social-memory sync orchestrator.

The implementation lives in one place: ``scripts/standalone/sync_memory.py``
(canonical -- see that directory's AGENTS.md). This root entrypoint is retained
because it is a documented public surface (AGENTS.md section 17.4) and because the
cron wrapper historically resolved it by name.

Re-exported rather than duplicated, so the two can never drift. Three rules:

1. Importing this module has NO side effects. ``tests/scripts/test_sync_memory.py``
   imports helpers directly, so the canonical module is loaded (not executed).
2. The stdout JSON contract stays byte-identical to running the canonical file
   directly, because the cron wrapper parses it with ``json.loads``.
3. Every module-level name is re-exported, private ones included. Tests
   monkeypatch ``sync_memory._export_obsidian``; re-exporting only the public
   surface would break that, and a plain alias cannot bridge a private name.
"""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

_CANONICAL = Path(__file__).resolve().parent / "scripts" / "standalone" / "sync_memory.py"
_MODULE_NAME = "sync_memory_standalone_impl"


def _load_canonical():
    if not _CANONICAL.is_file():
        raise ImportError(f"canonical sync_memory.py not found at {_CANONICAL}")
    spec = importlib.util.spec_from_file_location(_MODULE_NAME, _CANONICAL)
    if spec is None or spec.loader is None:
        raise ImportError(f"cannot load canonical module from {_CANONICAL}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[_MODULE_NAME] = module
    spec.loader.exec_module(module)
    return module


_impl = _load_canonical()

# Re-export every module-level name (including _private) so this shim is a
# drop-in for the old root module. A name that does not exist is skipped rather
# than raising, so a future canonical rename cannot break import here.
for _name in dir(_impl):
    if _name not in globals():
        globals()[_name] = getattr(_impl, _name)


if __name__ == "__main__":
    raise SystemExit(main())
