"""Windows ConPTY bridge for the `hermes dashboard` chat tab.

Drop-in counterpart to ``hermes_cli.pty_bridge.PtyBridge`` for native
Windows. Mirrors the exact public surface the ``/api/pty`` WebSocket
handler in ``hermes_cli.web_server`` consumes: ``spawn``, ``read``,
``write``, ``resize``, ``close``, ``is_available``, plus the
``PtyUnavailableError`` type.

Backed by ``pywinpty`` (already a declared win32 dependency in
pyproject.toml) instead of ``ptyprocess``/``fcntl``/``termios``, none of
which exist on native Windows. The read/write/terminate calls here match
the working winpty usage already shipping in ``tools/process_registry.py``.
"""

from __future__ import annotations

import asyncio
import logging
import sys
import time
from typing import Optional, Sequence

try:
    from winpty import PtyProcess  # type: ignore
    _PTY_AVAILABLE = sys.platform.startswith("win")
except ImportError:  # pragma: no cover - non-Windows or pywinpty missing
    PtyProcess = None  # type: ignore
    _PTY_AVAILABLE = False

_log = logging.getLogger(__name__)


__all__ = [
    "PTY_HOST_DASHBOARD",
    "PTY_HOST_ENV",
    "WinPtyBridge",
    "PtyUnavailableError",
]


# Same clamp ceiling as the POSIX bridge: a broken winsize probe must never
# reach the resize call. ConPTY tolerates large values better than ioctl,
# but we keep parity to avoid layout surprises.
_MIN_DIMENSION = 1
_MAX_COLS = 2000
_MAX_ROWS = 1000
_WRITE_SHUTDOWN_GRACE = 1.0

# Mirrored in hermes_cli/pty_bridge.py and ui-tui hermes-ink termio/host.ts.
PTY_HOST_ENV = "HERMES_PTY_HOST"
PTY_HOST_DASHBOARD = "dashboard"


def _clamp(value: int, maximum: int) -> int:
    try:
        n = int(value)
    except (TypeError, ValueError, OverflowError):
        return _MIN_DIMENSION
    if n < _MIN_DIMENSION:
        return _MIN_DIMENSION
    if n > maximum:
        return maximum
    return n


class PtyUnavailableError(RuntimeError):
    """Raised when a PTY cannot be created on this platform."""


class WinPtyBridge:
    """pywinpty-backed bridge with the same interface as ``PtyBridge``.

    ``web_server`` calls :meth:`read` inside ``run_in_executor``, so a
    blocking/polling read here never stalls the event loop. ConPTY exposes
    no selectable fd, so we poll with a short sleep instead of ``select``.
    """

    def __init__(self, proc: "PtyProcess") -> None:  # type: ignore[name-defined]
        self._proc = proc
        self._closed = False

    # -- lifecycle --------------------------------------------------------

    @classmethod
    def is_available(cls) -> bool:
        return bool(_PTY_AVAILABLE)

    @classmethod
    def spawn(
        cls,
        argv: Sequence[str],
        *,
        cwd: Optional[str] = None,
        env: Optional[dict] = None,
        cols: int = 80,
        rows: int = 24,
    ) -> "WinPtyBridge":
        if not _PTY_AVAILABLE:
            if PtyProcess is None:
                raise PtyUnavailableError(
                    "pywinpty is not installed. Install with: pip install pywinpty"
                )
            raise PtyUnavailableError("ConPTY is unavailable on this platform.")
        # See pty_bridge.py: exact-preservation factory for the env=None fallback.
        from tools.environments.local import build_subprocess_env
        spawn_env = (
            build_subprocess_env(scrub_secrets=False, inherit_profile_home=False)
            if env is None else dict(env)
        )
        if not spawn_env.get("TERM"):
            spawn_env["TERM"] = "xterm-256color"
        # Dashboard-hosted TUI: skip native-emulator focus-in erase+repaint.
        spawn_env[PTY_HOST_ENV] = PTY_HOST_DASHBOARD
        # pywinpty mirrors ptyprocess: dimensions=(rows, cols).
        # This call shape is the one already used in tools/process_registry.py.
        proc = PtyProcess.spawn(  # type: ignore[union-attr]
            list(argv),
            cwd=cwd,
            env=spawn_env,
            dimensions=(rows, cols),
        )
        return cls(proc)

    @property
    def pid(self) -> int:
        return int(self._proc.pid)

    def is_alive(self) -> bool:
        if self._closed:
            return False
        try:
            return bool(self._proc.isalive())
        except Exception:
            return False

    # -- I/O --------------------------------------------------------------

    def read(self, timeout: float = 0.2) -> Optional[bytes]:
        """Up to 64 KiB of child output.

        Returns bytes, ``b""`` when nothing is available this tick, or
        ``None`` once the child has exited (EOF).
        """
        if self._closed:
            return None
        try:
            data = self._proc.read(65536)  # pywinpty returns str
        except EOFError:
            return None
        except Exception:
            return None
        if not data:
            # No fd to select on; poll politely so the executor thread
            # doesn't pin a core while the TUI is idle.
            time.sleep(min(timeout, 0.02))
            return b""
        if isinstance(data, bytes):
            return data
        # NOTE: pywinpty decodes internally, so a multibyte UTF-8 sequence
        # can in theory split across reads. xterm.js tolerates the rare
        # replacement char; this is the one fidelity tradeoff vs the POSIX
        # raw-fd path.
        return data.encode("utf-8", errors="replace")

    def _write_blocking(self, data: bytes) -> bool:
        if self._closed:
            return False
        if not data:
            return True
        try:
            # Dashboard sends raw keystroke bytes; pywinpty.write wants text.
            self._proc.write(data.decode("utf-8", errors="replace"))
        except Exception:
            return False
        return True

    async def write(self, data: bytes, *, timeout: float = 10.0) -> bool:
        """Write off-loop; tear down ConPTY only when its input pipe wedges.

        ``wait_for(to_thread(...))`` alone only cancels the asyncio wrapper;
        the worker can remain blocked inside pywinpty. Keep the worker future,
        force-close ConPTY on timeout, and wait briefly for that close to
        release the blocked write before returning.

        Cancellation (owning socket went away mid-write) is not evidence of a
        wedged child: the PTY outlives its socket by design, so give the
        in-flight write the shutdown grace window and only terminate if it
        never lands. Socket lifetime ≠ PTY lifetime.
        """
        if self._closed:
            return False
        if not data:
            return True
        loop = asyncio.get_running_loop()
        write_future = loop.run_in_executor(None, self._write_blocking, data)
        try:
            return await asyncio.wait_for(
                asyncio.shield(write_future),
                timeout=max(0.0, timeout),
            )
        except asyncio.TimeoutError:
            await self._stop_stalled_write(write_future)
            return False
        except asyncio.CancelledError:
            await asyncio.shield(self._settle_or_stop_write(write_future))
            raise

    async def _settle_or_stop_write(self, write_future: asyncio.Future) -> None:
        """Let a cancelled write finish within grace; terminate only if stalled."""
        try:
            await asyncio.wait_for(
                asyncio.shield(write_future),
                timeout=_WRITE_SHUTDOWN_GRACE,
            )
            return
        except asyncio.TimeoutError:
            pass
        except Exception:
            return
        await self._stop_stalled_write(write_future)

    async def _stop_stalled_write(self, write_future: asyncio.Future) -> None:
        """Close ConPTY and reap the worker that was blocked in ``write``."""
        await asyncio.to_thread(self.close)
        try:
            await asyncio.wait_for(
                asyncio.shield(write_future),
                timeout=_WRITE_SHUTDOWN_GRACE,
            )
        except asyncio.TimeoutError:
            _log.warning(
                "ConPTY write worker did not exit within %.1fs of terminate(); thread leaked",
                _WRITE_SHUTDOWN_GRACE,
            )
        except Exception:
            pass

    def resize(self, cols: int, rows: int) -> None:
        if self._closed:
            return
        cols = _clamp(cols, _MAX_COLS)
        rows = _clamp(rows, _MAX_ROWS)
        try:
            self._proc.setwinsize(rows, cols)  # pywinpty: (rows, cols)
        except Exception:
            pass

    # -- teardown ---------------------------------------------------------

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        try:
            self._proc.terminate(force=True)
        except Exception:
            pass

    def __enter__(self) -> "WinPtyBridge":
        return self

    def __exit__(self, *_exc) -> None:
        self.close()
