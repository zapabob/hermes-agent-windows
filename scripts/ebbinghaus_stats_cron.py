"""Minimal Ebbinghaus memory CLI runner used by scheduled stats jobs.

Usage:
    .venv/Scripts/python.exe scripts/ebbinghaus_stats_cron.py stats
    .venv/Scripts/python.exe scripts/ebbinghaus_stats_cron.py sleep '{"limit": 200}'
"""

import json
import os
import sys
from pathlib import Path

REPO = os.environ.get("HERMES_REPO", str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, REPO)

from hermes_constants import get_hermes_home  # noqa: E402
from plugins.memory.ebbinghaus import EbbinghausMemoryProvider  # noqa: E402


def main() -> int:
    action = sys.argv[1] if len(sys.argv) > 1 else "stats"
    args = json.loads(sys.argv[2]) if len(sys.argv) > 2 else {}

    provider = EbbinghausMemoryProvider()
    provider.initialize("ebbinghaus-cron-stats", hermes_home=str(get_hermes_home()))
    try:
        result = provider.handle_tool_call("ebbinghaus_memory", {"action": action, **args})
    finally:
        shutdown = getattr(provider, "shutdown", None)
        if callable(shutdown):
            shutdown()

    if isinstance(result, str):
        try:
            result = json.loads(result)
        except json.JSONDecodeError:
            pass
    print(json.dumps(result, ensure_ascii=False, indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())