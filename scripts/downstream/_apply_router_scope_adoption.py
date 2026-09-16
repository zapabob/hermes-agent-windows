"""One-shot isolated-worktree materializer; not part of the runtime."""
from __future__ import annotations
import ast
from pathlib import Path
import re
import subprocess
import sys

root = Path(sys.argv[1]).resolve()
relative = "plugins/model-providers/router/__init__.py"
blob = subprocess.check_output(["git", "-C", str(root), "rev-parse", "HEAD:" + relative], text=True).strip()
if blob != "6e5b21dc2deceff8481b6d21992e9e1f670b3887":
    raise SystemExit("Refusing an unreviewed Router source blob")
path = root / relative
source = path.read_text(encoding="utf-8")
lines = source.splitlines(keepends=True)
replacements = []
for node in ast.parse(source).body:
    if not isinstance(node, ast.FunctionDef):
        continue
    block = "".join(lines[node.lineno - 1:node.end_lineno])
    if node.name in {"_seed_efforts", "_efforts_cache_only", "_warm_efforts_async"}:
        block, count = re.subn(r"    global [^\n]+\n", "    state = _cache_state()\n", block)
        if count != 1:
            raise SystemExit("Expected one global-state binding in " + node.name)
        block = re.sub(r"(?<![\w.])(_efforts_cache|_disk_checked|_warm_started)\b", r"state.\1", block)
        if node.name == "_warm_efforts_async":
            old = 'target=_refresh, name="router-caps-warm", daemon=True'
            new = 'target=contextvars.copy_context().run, args=(_refresh,),\n            name="router-caps-warm", daemon=True'
            if block.count(old) != 1:
                raise SystemExit("Expected one native warmer thread creation")
            block = block.replace(old, new).replace("at most once per process", "at most once per Hermes home")
        replacements.append((node.lineno - 1, node.end_lineno, block))
    elif node.name == "_base_url":
        block = '''def _base_url() -> str:
    """Resolve the active profile's endpoint before the process fallback."""
    resolvers = []
    try:
        from hermes_cli.config import get_env_value_prefer_dotenv

        resolvers.append(get_env_value_prefer_dotenv)
    except Exception:
        pass
    resolvers.append(os.environ.get)
    for resolve in resolvers:
        try:
            value = str(resolve("RAMP_ROUTER_BASE_URL") or "").strip().rstrip("/")
        except Exception:
            value = ""
        if value:
            return value
    return ROUTER_DEFAULT_BASE_URL
'''
        replacements.append((node.lineno - 1, node.end_lineno, block))
if len(replacements) != 4:
    raise SystemExit("Expected exactly four live Router functions")
for start, end, block in reversed(replacements):
    lines[start:end] = [block.rstrip("\n") + "\n"]
source = "".join(lines)
source = source.replace("import json\n", "import contextvars\nimport json\n", 1)
source = source.replace("import threading\n", "import sys\nimport threading\n", 1)
source = source.replace("from typing import Any, Optional\n", "from types import SimpleNamespace\nfrom typing import Any, Optional\n", 1)
anchor = "_disk_checked = False\n"
helper = '''

# Retain legacy module slots for unscoped callers, but isolate multiplexed
# profiles using the existing Windows-normalized Hermes Home identity.
_cache_by_home: dict[str, SimpleNamespace] = {}


def _cache_state() -> Any:
    from hermes_constants import get_hermes_home_override, hermes_home_key

    if get_hermes_home_override() is None:
        return sys.modules[__name__]
    key = hermes_home_key()
    with _efforts_lock:
        state = _cache_by_home.get(key)
        if state is None:
            state = SimpleNamespace(
                _efforts_cache=None, _warm_started=False, _disk_checked=False
            )
            _cache_by_home[key] = state
        return state
'''
if source.count(anchor) != 1:
    raise SystemExit("Expected one module-level cache-state anchor")
source = source.replace(anchor, anchor + helper, 1)
ast.parse(source)
with path.open("w", encoding="utf-8", newline="\n") as handle:
    handle.write(source)
print("Applied profile isolation inside existing " + relative)
