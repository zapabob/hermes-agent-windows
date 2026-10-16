"""Cross-process fencing for the existing MCP config and credential owners.

The journal contains counters only, never config values or credentials. All
participating writers serialize on a stable OS lock; counters are fsynced before
the protected effect. Failed effects therefore revoke conservatively, and a
process crash cannot make an old authorization current again.
"""
from __future__ import annotations

from contextlib import contextmanager
import hashlib
import json
import os
from pathlib import Path
import tempfile
import threading
import time

_locks: dict[str, threading.RLock] = {}
_locks_guard = threading.Lock()
_active = threading.local()


class StaleOAuthCommitError(RuntimeError):
    """An OAuth operation lost its provider, configuration or disk generation."""


class OAuthState:
    def __init__(self, directory: Path):
        self.path = directory / "generations.json"
        try:
            self.values = json.loads(self.path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            self.values = {}
        if not isinstance(self.values, dict) or any(
            not isinstance(k, str) or type(v) is not int or v < 0
            for k, v in self.values.items()
        ):
            raise RuntimeError("Invalid MCP OAuth generation journal")

    @staticmethod
    def key(kind: str, name: str) -> str:
        return hashlib.sha256(f"{kind}:{name}".encode("utf-8")).hexdigest()

    def generation(self, kind: str, name: str) -> int:
        return self.values.get(self.key(kind, name), 0)

    def advance(self, kind: str, name: str) -> int:
        key = self.key(kind, name)
        self.values[key] = self.values.get(key, 0) + 1
        fd, temporary = tempfile.mkstemp(dir=self.path.parent, suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as stream:
                json.dump(self.values, stream, sort_keys=True)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, self.path)
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)
        return self.values[key]


@contextmanager
def oauth_state_lock(home: str | Path):
    """A bounded, reentrant thread + native process lock for one physical home."""
    home = Path(home).expanduser().resolve(strict=False)
    key = os.path.normcase(str(home))
    with _locks_guard:
        lock = _locks.setdefault(key, threading.RLock())
    with lock:
        active = getattr(_active, "homes", None)
        if active is None:
            active = _active.homes = {}
        if key in active:
            yield active[key]
            return
        directory = home / ".mcp-oauth-state"
        directory.mkdir(parents=True, exist_ok=True, mode=0o700)
        # Never replace or unlink the lock inode while a process may own it.
        with (directory / "lock").open("a+b") as stream:
            stream.seek(0, os.SEEK_END)
            if stream.tell() == 0:
                stream.write(b"\0")
                stream.flush()
            deadline = time.monotonic() + 10
            while True:
                try:
                    stream.seek(0)
                    if os.name == "nt":
                        import msvcrt
                        msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
                    else:
                        import fcntl
                        fcntl.flock(stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                    break
                except OSError:
                    if time.monotonic() >= deadline:
                        raise TimeoutError("MCP OAuth state is busy") from None
                    time.sleep(0.01)
            try:
                state = OAuthState(directory)
                active[key] = state
                try:
                    yield state
                finally:
                    del active[key]
            finally:
                stream.seek(0)
                if os.name == "nt":
                    import msvcrt
                    msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)
                else:
                    import fcntl
                    fcntl.flock(stream.fileno(), fcntl.LOCK_UN)


def config_entry(home: str | Path, name: str):
    """Read raw saved authority; a missing entry permits initial CLI setup."""
    import yaml
    try:
        document = yaml.safe_load((Path(home) / "config.yaml").read_text(encoding="utf-8"))
    except FileNotFoundError:
        return None
    if not isinstance(document, dict):
        raise StaleOAuthCommitError("Invalid saved MCP configuration")
    servers = document.get("mcp_servers", {})
    return servers.get(name) if isinstance(servers, dict) else None


@contextmanager
def config_replace_guard(temporary: str | Path, target: str | Path):
    """Fence every existing atomic config serializer, including round-trip YAML."""
    target = Path(target)
    if os.path.normcase(target.parent.name) == os.path.normcase("mcp-tokens"):
        with oauth_state_lock(target.parent.parent) as state:
            state.advance("path", os.path.normcase(str(target.resolve(strict=False))))
            yield
        return
    if os.path.normcase(target.name) != os.path.normcase("config.yaml"):
        yield
        return
    import yaml
    with oauth_state_lock(target.parent) as state:
        try:
            previous = yaml.safe_load(target.read_text(encoding="utf-8")) or {}
        except (FileNotFoundError, yaml.YAMLError):
            # A restore may repair malformed YAML. Every entry in the valid
            # replacement is still fenced; the existing journal is never reset.
            previous = {}
        candidate = yaml.safe_load(Path(temporary).read_text(encoding="utf-8")) or {}
        old = previous.get("mcp_servers", {}) if isinstance(previous, dict) else {}
        new = candidate.get("mcp_servers", {}) if isinstance(candidate, dict) else {}
        old = old if isinstance(old, dict) else {}
        new = new if isinstance(new, dict) else {}
        for name in old.keys() | new.keys():
            if old.get(name) != new.get(name):
                state.advance("config", name)
        yield
