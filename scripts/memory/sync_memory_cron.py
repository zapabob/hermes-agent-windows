#!/usr/bin/env python3
"""Cron-safe wrapper for ``sync_memory.py`` (must live under ``~/.hermes/scripts/``).

Runs the repo orchestrator with cwd = cron ``--workdir``, then prints a
redacted JSON summary suitable for no-agent delivery.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from typing import Any


def _safe_summary(payload: dict[str, Any]) -> dict[str, Any]:
    social = payload.get("social") or {}
    obsidian = payload.get("obsidian") or {}
    return {
        "success": bool(payload.get("success")),
        "social": {
            "sources": social.get("sources"),
            "sessions_seen": social.get("sessions_seen"),
            "x_events_seen": social.get("x_events_seen"),
            "memories_written": social.get("memories_written"),
            "incremental": social.get("incremental"),
            "index_path": social.get("index_path"),
            "sleep": social.get("sleep"),
        },
        "obsidian": {
            "success": obsidian.get("success"),
            "skipped": obsidian.get("skipped"),
            "dry_run": obsidian.get("dry_run"),
            "items": obsidian.get("items"),
            "groups": obsidian.get("groups"),
            "wiki_root": obsidian.get("wiki_root"),
            "error": obsidian.get("error"),
        },
        "index_updated": payload.get("index_updated"),
    }


def _resolve_sync_script(repo_root):
    """Resolve the sync orchestrator by CLI surface, not by filename.

    The repo root may hold a compatibility shim; the implementation lives in
    ``scripts/standalone/sync_memory.py``. Both are acceptable entrypoints, but the
    canonical file is preferred so the subprocess does not pay shim indirection.
    """
    for cand in (
        repo_root / "scripts" / "standalone" / "sync_memory.py",
        repo_root / "sync_memory.py",
    ):
        if not cand.is_file():
            continue
        try:
            head = cand.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        if "--max-x-events" in head and "json.dumps" in head:
            return cand
    return None


def main() -> int:
    repo_root = Path.cwd()
    sync_script = _resolve_sync_script(repo_root)
    if sync_script is None:
        print(json.dumps({"success": False, "error": f"sync_memory.py not found under {repo_root}"}))
        return 1

    proc = subprocess.run(
        # X/lm-twitterer activity stays in its own ledger; only first-hand
        # session memories are imported (memory source policy 2026-09-26).
        [sys.executable, str(sync_script), "--max-x-events", "0"],
        cwd=repo_root,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    if proc.returncode != 0:
        print(
            json.dumps(
                {
                    "success": False,
                    "error": f"sync_memory exited {proc.returncode}",
                    "stderr_tail": (proc.stderr or "")[-500:],
                },
                ensure_ascii=False,
            )
        )
        return proc.returncode

    try:
        payload = json.loads(proc.stdout)
    except json.JSONDecodeError:
        print(json.dumps({"success": False, "error": "invalid JSON from sync_memory.py"}))
        return 1

    print(json.dumps(_safe_summary(payload), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
