"""Dashboard-mediated callback bridge for MCP OAuth.

The MCP SDK remains responsible for discovery, DCR, PKCE, state validation and
token exchange. This module only moves the two human/browser callbacks from a
loopback listener into the already-authenticated dashboard session.
"""

from __future__ import annotations

import asyncio
import copy
import contextvars
import secrets
import threading
import time
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterator
from urllib.parse import parse_qs, urlparse
from tools.mcp_oauth_state import oauth_state_lock


class McpOAuthConfigChangedError(RuntimeError):
    """The saved MCP entry no longer authorizes an in-flight OAuth grant."""


@contextmanager
def _config_lock(home=None):
    # Resolve the module attribute for every acquisition. Tests and embedded
    # hosts replace this lock, so a captured alias would split the lock domain.
    from hermes_cli import config as config_module

    from hermes_constants import get_hermes_home
    with config_module._CONFIG_LOCK, oauth_state_lock(home or get_hermes_home()):
        yield config_module


def _read_raw_config(config_module, home: str) -> tuple[Path, dict]:
    """Read only the saved YAML document, without defaults or env expansion."""
    path = Path(home) / "config.yaml"
    try:
        with path.open("r", encoding="utf-8") as stream:
            document = config_module.fast_safe_load(stream)
    except FileNotFoundError:
        document = {}
    except Exception:
        raise McpOAuthConfigChangedError(
            "MCP OAuth configuration changed; start a new authorization."
        ) from None
    if not isinstance(document, dict):
        raise McpOAuthConfigChangedError(
            "MCP OAuth configuration changed; start a new authorization."
        )
    return path, document


@dataclass
class SavedMcpConfigBinding:
    """Process-local authority for one raw ``mcp_servers.<name>`` entry."""

    hermes_home: str
    server_name: str
    expected_entry: dict
    needs_auth_commit: bool
    owner: object = field(default_factory=object, repr=False)
    sealed: bool = False
    revision: int = 0
    # Bytes live only while rollback may need to identify a grant created by
    # this flow. The path-generation scalar itself lives in mcp_oauth.py.
    owned_effects: dict[str, tuple[int, bytes | None]] = field(
        default_factory=dict, repr=False
    )
    rollback_baselines: dict[str, int] = field(default_factory=dict, repr=False)
    rollback_blocked_paths: set[str] = field(default_factory=set, repr=False)

    @classmethod
    def capture(cls, hermes_home: str, server_name: str) -> "SavedMcpConfigBinding":
        home = str(Path(hermes_home).expanduser().resolve(strict=False))
        with _config_lock(home) as config_module, oauth_state_lock(home) as state:
            _, document = _read_raw_config(config_module, home)
            servers = document.get("mcp_servers")
            entry = servers.get(server_name) if isinstance(servers, dict) else None
            if not isinstance(entry, dict) or entry.get("enabled") is False:
                raise McpOAuthConfigChangedError(
                    "MCP OAuth configuration changed; start a new authorization."
                )
            return cls(
                hermes_home=home,
                server_name=server_name,
                expected_entry=copy.deepcopy(entry),
                needs_auth_commit=("auth" not in entry or entry.get("auth") is None),
                revision=state.generation("config", server_name),
            )

    def _current_entry_locked(self, config_module) -> tuple[Path, dict, dict]:
        with oauth_state_lock(self.hermes_home):
            return self._read_current_entry_locked(config_module)

    def _read_current_entry_locked(self, config_module) -> tuple[Path, dict, dict]:
        path, document = _read_raw_config(config_module, self.hermes_home)
        servers = document.get("mcp_servers")
        entry = servers.get(self.server_name) if isinstance(servers, dict) else None
        if not isinstance(entry, dict) or entry.get("enabled") is False:
            raise McpOAuthConfigChangedError(
                "MCP OAuth configuration changed; start a new authorization."
            )
        with oauth_state_lock(self.hermes_home) as state:
            revision = state.generation("config", self.server_name)
        if entry != self.expected_entry or revision != self.revision:
            raise McpOAuthConfigChangedError(
                "MCP OAuth configuration changed; start a new authorization."
            )
        return path, document, entry

    def assert_current_locked(self, config_module) -> None:
        self._current_entry_locked(config_module)

    def assert_current(self) -> None:
        with _config_lock(self.hermes_home) as config_module:
            self.assert_current_locked(config_module)

    def commit_auth_locked(self, config_module) -> None:
        """Persist implicit OAuth selection from raw YAML and seal authority."""
        with oauth_state_lock(self.hermes_home):
            self._commit_auth_locked(config_module)

    def _commit_auth_locked(self, config_module) -> None:
        path, document, current = self._current_entry_locked(config_module)
        if self.needs_auth_commit:
            if config_module.is_managed():
                raise RuntimeError("MCP OAuth settings are managed and cannot be saved.")
            from hermes_cli import managed_scope

            managed_auth_key = f"mcp_servers.{self.server_name}.auth"
            if managed_scope.is_key_managed(managed_auth_key):
                raise RuntimeError("MCP OAuth auth setting is managed and cannot be saved.")
            entry = copy.deepcopy(current)
            entry["auth"] = "oauth"
            document["mcp_servers"][self.server_name] = entry
            from utils import atomic_yaml_write

            atomic_yaml_write(path, document, sort_keys=False)
            _, saved = _read_raw_config(config_module, self.hermes_home)
            servers = saved.get("mcp_servers")
            persisted = servers.get(self.server_name) if isinstance(servers, dict) else None
            if persisted != entry:
                raise McpOAuthConfigChangedError(
                    "MCP OAuth configuration changed; start a new authorization."
                )
            self.expected_entry = copy.deepcopy(entry)
            with oauth_state_lock(self.hermes_home) as state:
                self.revision = state.generation("config", self.server_name)
            self.needs_auth_commit = False
        elif current.get("auth") not in (None, "oauth"):
            raise McpOAuthConfigChangedError(
                "MCP OAuth configuration changed; start a new authorization."
            )
        self.sealed = True

    def begin_rollback_window(self, generations: dict[str, int]) -> None:
        self.owned_effects.clear()
        self.rollback_baselines = dict(generations)
        self.rollback_blocked_paths.clear()

    def record_effect(
        self,
        path: str,
        generation: int,
        contents: bytes | None,
        previous_generation: int,
    ) -> None:
        if self.sealed:
            return
        baseline = self.rollback_baselines.get(path)
        if baseline is not None:
            previous = self.owned_effects.get(path)
            expected_previous = previous[0] if previous is not None else baseline
            if previous_generation != expected_previous or generation != previous_generation + 1:
                self.rollback_blocked_paths.add(path)
        self.owned_effects[path] = (generation, contents)

    def fail_effect(self, path: str) -> None:
        self.owned_effects.pop(path, None)
        if path in self.rollback_baselines:
            self.rollback_blocked_paths.add(path)

    def clear_effects(self) -> None:
        self.owned_effects.clear()
        self.rollback_baselines.clear()
        self.rollback_blocked_paths.clear()


@dataclass
class DashboardOAuthFlow:
    flow_id: str
    server_name: str
    profile: str | None
    hermes_home: str
    redirect_uri: str
    reconnect_live: bool = False
    config_binding: SavedMcpConfigBinding | None = None
    created_at: float = field(default_factory=time.time)
    status: str = "starting"
    authorization_url: str | None = None
    error: str | None = None
    tools: list[dict] = field(default_factory=list)
    expected_state: str | None = field(default=None, init=False)
    _callback: tuple[str, str | None, str | None] | None = field(default=None, init=False, repr=False)
    _callback_error: str | None = field(default=None, init=False, repr=False)
    _cancelled: bool = field(default=False, init=False, repr=False)
    _provider_entry: object | None = field(default=None, init=False, repr=False)
    _provider_object: object | None = field(default=None, init=False, repr=False)
    _provider_identity_conflict: bool = field(default=False, init=False, repr=False)
    _authorization_ready: threading.Event = field(default_factory=threading.Event, init=False, repr=False)
    _callback_ready: threading.Event = field(default_factory=threading.Event, init=False, repr=False)
    _worker_done: threading.Event = field(default_factory=threading.Event, init=False, repr=False)
    _lock: threading.Lock = field(default_factory=threading.Lock, init=False, repr=False)

    async def publish_authorization_url(self, url: str) -> None:
        state = parse_qs(urlparse(url).query).get("state", [None])[0]
        if not state:
            raise ValueError("OAuth authorization URL did not include state")
        with self._lock:
            if self.status in {"approved", "error"}:
                raise RuntimeError("OAuth flow already ended")
            self.expected_state = state
            self.authorization_url = url
            self.status = "authorization_required"
            self._authorization_ready.set()

    async def wait_for_authorization_url(self, timeout: float = 30.0) -> str:
        ready = await asyncio.to_thread(self._authorization_ready.wait, timeout)
        if not ready:
            raise TimeoutError("Timed out waiting for MCP authorization URL")
        if not self.authorization_url:
            raise RuntimeError(self.error or "MCP OAuth flow ended before authorization")
        return self.authorization_url

    def deliver_callback(
        self,
        *,
        code: str | None,
        state: str | None,
        error: str | None,
        iss: str | None = None,
    ) -> None:
        with self._lock:
            if self._callback_ready.is_set():
                raise ValueError("OAuth callback already received")
            if (
                self.expected_state is None
                or state is None
                or not secrets.compare_digest(self.expected_state, state)
            ):
                raise ValueError("OAuth callback state mismatch")
            if self.config_binding is not None:
                try:
                    self.config_binding.assert_current()
                except McpOAuthConfigChangedError as exc:
                    self._mark_error_locked(str(exc))
                    raise ValueError("OAuth callback configuration changed") from None
            if error:
                self._callback_error = error
            elif code:
                self._callback = (code, state, iss)
            else:
                self._callback_error = "OAuth callback did not include code or error"
            self._callback_ready.set()

    async def wait_for_callback(self, timeout: float = 300.0) -> tuple[str, str | None, str | None]:
        ready = await asyncio.to_thread(self._callback_ready.wait, timeout)
        if not ready:
            raise TimeoutError("Timed out waiting for MCP OAuth callback")
        if self._callback_error:
            raise RuntimeError(f"OAuth authorization failed: {self._callback_error}")
        if self._callback is None:
            raise RuntimeError("OAuth callback did not include an authorization code")
        return self._callback

    def mark_approved(self) -> None:
        with self._lock:
            if self.status == "error":
                raise RuntimeError("OAuth flow already ended")
            self.status = "approved"
            self.error = None

    def record_provider_identity(self, entry: object, provider: object) -> None:
        """Remember the exact cache entry used by this in-flight grant."""
        with self._lock:
            if self._worker_done.is_set() or provider is None:
                return
            if self._provider_entry is None and self._provider_object is None:
                self._provider_entry = entry
                self._provider_object = provider
                return
            if self._provider_entry is not entry or self._provider_object is not provider:
                self._provider_identity_conflict = True

    def _clear_provider_identity_locked(self) -> None:
        self._provider_entry = None
        self._provider_object = None
        self._provider_identity_conflict = False

    def provider_settlement_identity(self) -> tuple[object | None, object | None, bool]:
        """Keep cancellation/error independent of the worker's rollback evidence."""
        with self._lock:
            return self._provider_entry, self._provider_object, self._provider_identity_conflict

    def release_provider_settlement(self) -> None:
        """Release references only after the worker's manager settlement."""
        with self._lock:
            self._clear_provider_identity_locked()

    def adopt_approved(
        self,
        storage,
        tools: list[dict],
        *,
        provider_entry: object | None = None,
        provider_object: object | None = None,
    ) -> None:
        """Atomically recheck saved authority and synchronously adopt tokens."""
        with self._lock:
            if self.status == "error":
                raise RuntimeError("OAuth flow already ended")
            if provider_entry is not None and (
                self._provider_identity_conflict
                or self._provider_entry is not provider_entry
                or self._provider_object is not provider_object
            ):
                raise McpOAuthConfigChangedError(
                    "MCP OAuth configuration changed; start a new authorization."
                )
            if self.config_binding is None:
                if not storage.has_cached_tokens():
                    raise RuntimeError("No OAuth token was obtained")
                self.tools = tools
                self.status = "approved"
                self.error = None
                return
            with _config_lock(self.hermes_home) as config_module:
                self.config_binding.assert_current_locked(config_module)
                if not storage.has_cached_tokens():
                    raise RuntimeError("No OAuth token was obtained")
                self.config_binding.commit_auth_locked(config_module)
                self.config_binding.clear_effects()
                self.tools = tools
                self.status = "approved"
                self.error = None

    def mark_error(self, error: str) -> None:
        with self._lock:
            self._mark_error_locked(error)

    def _mark_error_locked(self, error: str) -> None:
        if self.status in {"approved", "error"}:
            return
        self.status = "error"
        self.error = error
        if self._callback is None and self._callback_error is None:
            self._callback_error = error
        self._authorization_ready.set()
        self._callback_ready.set()

    def cancel_pending(self) -> bool:
        """Cancel before callback admission; admitted exchanges retain their result.

        Delivery and cancellation share the lock. A consumed provider callback
        belongs to the SDK/worker until its real approval or error; reporting it
        as cancelled would misrepresent token/config writes already in progress.
        """
        with self._lock:
            if self.status in {"approved", "error"}:
                return self._cancelled
            if self._callback_ready.is_set():
                return False
            self._cancelled = True
            self.status = "error"
            self.error = "Cancelled by user"
            self._callback_error = self.error
            self._authorization_ready.set()
            self._callback_ready.set()
            return True

    def snapshot(self) -> dict:
        with self._lock:
            return {
                "flow_id": self.flow_id,
                "server_name": self.server_name,
                "status": self.status,
                "authorization_url": self.authorization_url,
                "error": self.error,
            }

    def mark_worker_done(self) -> None:
        self._worker_done.set()

    @property
    def worker_done(self) -> bool:
        return self._worker_done.is_set()

    @property
    def cancelled(self) -> bool:
        with self._lock:
            return self._cancelled

    def wait_worker_done(self, timeout: float) -> bool:
        return self._worker_done.wait(max(0.0, timeout))


_current_dashboard_flow: contextvars.ContextVar[DashboardOAuthFlow | None] = (
    contextvars.ContextVar("mcp_dashboard_oauth_flow", default=None)
)


@contextmanager
def dashboard_oauth_flow(flow: DashboardOAuthFlow) -> Iterator[None]:
    token = _current_dashboard_flow.set(flow)
    try:
        yield
    finally:
        _current_dashboard_flow.reset(token)


def get_dashboard_oauth_flow() -> DashboardOAuthFlow | None:
    return _current_dashboard_flow.get()
