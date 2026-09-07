"""Dashboard managed-files and /api/fs path policy helpers.

Extracted from hermes_cli.web_server for cohesion. HTTP routes remain in
web_server; that module re-exports these names for monkeypatch compatibility.
"""

from __future__ import annotations

import mimetypes
import os
import stat
import subprocess
import sys
import urllib.parse
import urllib.request
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any, Dict, Optional

from fastapi import HTTPException, Request

from hermes_cli._subprocess_compat import windows_hide_flags
from hermes_cli.config import load_config

_MANAGED_FILES_ROOT_ENV = "HERMES_DASHBOARD_FILES_ROOT"
_MANAGED_FILE_MAX_BYTES = 100 * 1024 * 1024
_STREAMABLE_MEDIA_EXTENSIONS = frozenset(
    {
        ".avi",
        ".flac",
        ".m4a",
        ".mkv",
        ".mov",
        ".mp3",
        ".mp4",
        ".ogg",
        ".opus",
        ".wav",
        ".webm",
    }
)
_HOSTED_MANAGED_FILES_ROOT = Path("/opt/data")
_HOSTED_MANAGED_FILES_ROOT_TEXT = "/opt/data"


@dataclass(frozen=True)
class ManagedFilesPolicy:
    default_path: Path | PurePosixPath
    locked_root: Path | PurePosixPath | None
    can_change_path: bool


_FS_READDIR_HIDDEN = {
    ".git",
    ".hg",
    ".svn",
    ".cache",
    ".next",
    ".turbo",
    ".venv",
    "__pycache__",
    "build",
    "dist",
    "node_modules",
    "target",
    "venv",
}

# Filenames that must never be listed, read, or downloaded through the
# managed-files API.  These typically contain credentials (API keys, tokens)
# and exposing them through the dashboard file browser is a security leak —
# see issue #57505. The set mirrors the credential-file basenames of the two
# canonical credential guards elsewhere in the codebase
# (agent.file_safety.get_read_block_error and
# gateway.platforms.base._ROOT_CREDENTIAL_FILES) so the dashboard Files tab
# doesn't lag behind them — an operator can point the managed root at
# HERMES_HOME itself, at which point every one of these basenames is a live
# secret store sitting in the browsable tree.
_SENSITIVE_MANAGED_FILE_BASENAMES = frozenset({
    "auth.json",
    "auth.lock",
    "credentials",
    "config.yaml",
    ".anthropic_oauth.json",
    "google_token.json",
    "google_oauth_pending.json",
    "google_oauth.json",
    "webhook_subscriptions.json",
    "bws_cache.json",
    "bws_cache.enc.json",
    # git's credential-store helper cache (agent.file_safety blocks this too).
    ".git-credentials",
})

# Directory names whose entire subtree is credential material. Both canonical
# guards deny these as directory trees, not basenames:
#   * gateway.platforms.base._ROOT_CREDENTIAL_DIRS = {"pairing", "mcp-tokens"}
#   * agent.file_safety.get_read_block_error (mcp-tokens/ prefix match)
# The managed-files API lets the browser descend into subdirs, so a
# basename-only guard would still expose e.g. ``mcp-tokens/<server>.json``
# (live MCP OAuth tokens) and ``pairing/<x>``. We match on ANY path component
# so these trees are blocked wherever they appear under the browsable root,
# without needing to resolve them relative to HERMES_HOME.
_SENSITIVE_MANAGED_DIR_NAMES = frozenset({
    "mcp-tokens",
    "pairing",
})


def _is_sensitive_filename(name: str) -> bool:
    """Return True for a basename the managed-files API must never expose.

    Covers ``.env`` / ``.env.<suffix>`` / ``.envrc`` variants plus the
    canonical Hermes credential-store basenames (see
    ``_SENSITIVE_MANAGED_FILE_BASENAMES`` above).

    Case-insensitive so ``.ENV`` / ``.Env.local`` / ``Auth.JSON`` on
    case-insensitive filesystems (macOS/Windows mounts) can't slip past
    the guard.

    Basename-only: for the directory-tree credential stores
    (``mcp-tokens/``, ``pairing/``) that the canonical guards also deny,
    use :func:`_is_sensitive_path`, which the API call sites route through.
    """
    lowered = name.lower()
    if lowered == ".env" or lowered.startswith(".env.") or lowered == ".envrc":
        return True
    return lowered in _SENSITIVE_MANAGED_FILE_BASENAMES


def _is_sensitive_path(path: Path) -> bool:
    """Return True for any path the managed-files API must never expose.

    Combines the basename denylist (:func:`_is_sensitive_filename`) with a
    credential-directory-tree check: a path is sensitive if its own basename
    is sensitive OR any of its path components is a credential directory
    (``mcp-tokens`` / ``pairing``). The component match is case-insensitive
    and needs no HERMES_HOME resolution, so it blocks these trees wherever
    they sit under the operator-configured managed root — closing the gap
    the canonical guards cover as directory trees but a basename-only check
    would miss.

    Read-side only: this guards list/read/download (the #57505 exfil surface).
    The write endpoints (upload/mkdir/delete) are a separate threat class
    handled by the write-path checks; extending this guard to them is out of
    scope for this fix.
    """
    if _is_sensitive_filename(path.name):
        return True
    return any(part.lower() in _SENSITIVE_MANAGED_DIR_NAMES for part in path.parts)


_FS_DATA_URL_MAX_BYTES = 16 * 1024 * 1024
_FS_TEXT_SOURCE_MAX_BYTES = 64 * 1024 * 1024
_FS_TEXT_PREVIEW_MAX_BYTES = 512 * 1024
# Upper bound for the in-app spot editor's save. The editor only opens
# non-truncated text (<= the preview cap), so this is a safety ceiling against
# a pasted-in megablob, not the expected payload size.
_FS_TEXT_WRITE_MAX_BYTES = 8 * 1024 * 1024
_FS_PREVIEW_LANGUAGE_BY_EXT = {
    ".c": "c",
    ".conf": "ini",
    ".cpp": "cpp",
    ".css": "css",
    ".csv": "csv",
    ".go": "go",
    ".graphql": "graphql",
    ".h": "c",
    ".hpp": "cpp",
    ".html": "html",
    ".java": "java",
    ".js": "javascript",
    ".json": "json",
    ".jsx": "jsx",
    ".kt": "kotlin",
    ".lua": "lua",
    ".md": "markdown",
    ".mjs": "javascript",
    ".py": "python",
    ".rb": "ruby",
    ".rs": "rust",
    ".sh": "shell",
    ".sql": "sql",
    ".svg": "xml",
    ".toml": "toml",
    ".ts": "typescript",
    ".tsx": "tsx",
    ".txt": "text",
    ".xml": "xml",
    ".yaml": "yaml",
    ".yml": "yaml",
    ".zsh": "shell",
}
_FS_MIME_TYPES = {
    ".avi": "video/x-msvideo",
    ".bmp": "image/bmp",
    ".flac": "audio/flac",
    ".gif": "image/gif",
    ".jpeg": "image/jpeg",
    ".jpg": "image/jpeg",
    ".m4a": "audio/mp4",
    ".mkv": "video/x-matroska",
    ".mov": "video/quicktime",
    ".mp3": "audio/mpeg",
    ".mp4": "video/mp4",
    ".ogg": "audio/ogg",
    ".opus": "audio/ogg; codecs=opus",
    ".png": "image/png",
    ".svg": "image/svg+xml",
    ".wav": "audio/wav",
    ".webm": "video/webm",
    ".webp": "image/webp",
}


def _fs_path(raw_path: str, *, cwd: str | None = None) -> Path:
    raw = str(raw_path or "").strip()
    if not raw:
        raise HTTPException(status_code=400, detail="Path is required")
    if "\0" in raw:
        raise HTTPException(status_code=400, detail="Invalid path")
    try:
        if raw.lower().startswith("file:"):
            parsed = urllib.parse.urlparse(raw)
            if parsed.netloc and parsed.netloc not in {"", "localhost"}:
                raise PermissionError("remote file URL authority")
            raw = urllib.request.url2pathname(urllib.parse.unquote(parsed.path))
        # Reject raw and decoded UNC/network-share spellings before Path or any
        # endpoint can stat, scan, open, or stream the target.  This remains
        # OS-neutral so Windows backslashes cannot bypass the POSIX test path.
        normalized = raw.replace("\\", "/")
        if normalized.startswith("//") and len(normalized) > 2 and normalized.lstrip("/"):
            raise PermissionError("network share path")
        candidate = Path(raw).expanduser()
        if not candidate.is_absolute():
            base = Path(cwd).expanduser() if cwd is not None else Path.cwd()
            if not base.is_absolute():
                raise HTTPException(
                    status_code=400,
                    detail="Session working directory is unavailable",
                )
            candidate = base / candidate
        return candidate.resolve(strict=False)
    except PermissionError:
        raise HTTPException(status_code=403, detail="Network share paths are not allowed")
    except (OSError, RuntimeError, ValueError):
        raise HTTPException(status_code=400, detail="Invalid path")


def _fs_mime_type(path: Path) -> str:
    suffix = path.suffix.lower()
    if suffix in _FS_MIME_TYPES:
        return _FS_MIME_TYPES[suffix]
    guessed, _ = mimetypes.guess_type(str(path))
    return guessed or "application/octet-stream"


def _fs_looks_binary(data: bytes) -> bool:
    if not data:
        return False
    if b"\0" in data:
        return True
    suspicious = sum(1 for byte in data if byte < 32 and byte not in {9, 10, 13})
    return suspicious / len(data) > 0.12


def _fs_regular_file(path: Path) -> tuple[Path, os.stat_result]:
    target = _fs_path(str(path))
    try:
        st = target.stat()
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="File not found")
    except NotADirectoryError:
        raise HTTPException(status_code=404, detail="File not found")
    except PermissionError:
        raise HTTPException(status_code=403, detail="File is not readable")
    except OSError as exc:
        raise HTTPException(status_code=400, detail=str(exc) or "Invalid path")
    if stat.S_ISDIR(st.st_mode):
        raise HTTPException(status_code=400, detail="Path points to a directory")
    if not stat.S_ISREG(st.st_mode):
        raise HTTPException(status_code=400, detail="Only regular files can be read")
    return target, st


def _fs_find_git_root(start: Path) -> str | None:
    directory = start
    for _ in range(50):
        try:
            if (directory / ".git").exists():
                return str(directory)
        except OSError:
            return None
        parent = directory.parent
        if parent == directory:
            return None
        directory = parent
    return None


def _fs_default_cwd() -> str:
    cfg_terminal = load_config().get("terminal") or {}
    raw = str(cfg_terminal.get("cwd") or os.environ.get("TERMINAL_CWD") or "").strip()
    if raw and raw not in {".", "auto", "cwd"}:
        try:
            candidate = Path(raw).expanduser().resolve(strict=False)
            if candidate.is_dir():
                return str(candidate)
        except (OSError, RuntimeError):
            pass
    return str(Path.cwd())


def _fs_git_branch(cwd: str) -> str:
    try:
        run_kwargs: Dict[str, Any] = {
            "capture_output": True,
            "text": True,
            "timeout": 2,
            "check": False,
        }
        if sys.platform == "win32":
            run_kwargs["creationflags"] = windows_hide_flags()
        result = subprocess.run(
            ["git", "-C", cwd, "branch", "--show-current"],
            **run_kwargs,
        )
        return result.stdout.strip() if result.returncode == 0 else ""
    except Exception:
        return ""


def _canonical_path(path: Path, *, require_exists: bool = False) -> Path:
    try:
        return path.expanduser().resolve(strict=require_exists)
    except FileNotFoundError:
        if require_exists:
            raise HTTPException(status_code=404, detail="Path not found")
        raise
    except (OSError, RuntimeError):
        raise HTTPException(status_code=400, detail="Invalid path")


def _ensure_managed_root(raw_path: str | Path) -> Path:
    root = Path(raw_path).expanduser()
    try:
        root.mkdir(parents=True, exist_ok=True)
        resolved = root.resolve()
    except (OSError, RuntimeError) as exc:
        raise HTTPException(status_code=500, detail=f"Managed files root is unavailable: {exc}")
    if not resolved.is_dir():
        raise HTTPException(status_code=500, detail="Managed files root is not a directory")
    return resolved


def _path_is_under(root: Path, target: Path) -> bool:
    return target == root or root in target.parents


def _path_text(raw_path: str | None) -> str:
    text = str(raw_path or "").strip()
    if "\x00" in text:
        raise HTTPException(status_code=400, detail="Invalid path")
    return text


def _local_dashboard_request(request: Request) -> bool:
    if getattr(request.app.state, "auth_required", False):
        return False
    host = (request.url.hostname or "").lower()
    client_host = (request.client.host if request.client else "").lower()
    local_hosts = {"", "localhost", "127.0.0.1", "::1", "testserver", "testclient"}
    return host in local_hosts or client_host in local_hosts


def _default_hermes_root_is_opt_data() -> bool:
    raw = os.environ.get("HERMES_HOME", "").strip()
    if not raw:
        return False
    normalized = raw.replace("\\", "/").rstrip("/")
    if normalized == _HOSTED_MANAGED_FILES_ROOT_TEXT:
        return True
    try:
        root = Path(raw).expanduser().resolve(strict=False)
    except (OSError, RuntimeError):
        return False
    try:
        hosted_root = _HOSTED_MANAGED_FILES_ROOT.expanduser().resolve(strict=False)
    except (OSError, RuntimeError):
        hosted_root = _HOSTED_MANAGED_FILES_ROOT
    return root == hosted_root


def _dashboard_home_path() -> Path:
    raw_home = os.environ.get("HOME", "").strip()
    if raw_home:
        return _canonical_path(Path(raw_home))
    return _canonical_path(Path.home())


def _managed_files_policy(request: Request, *, create_root: bool = True) -> ManagedFilesPolicy:
    raw_forced_root = os.environ.get(_MANAGED_FILES_ROOT_ENV, "").strip()
    if raw_forced_root:
        root = _ensure_managed_root(raw_forced_root) if create_root else _canonical_path(Path(raw_forced_root))
        return ManagedFilesPolicy(default_path=root, locked_root=root, can_change_path=False)

    # Remote/OAuth access does not imply a hosted container. Users can expose a
    # local dashboard through the auth gate (for example a macOS launchd install)
    # and still expect the Files page to browse their local home directory. Lock
    # to /opt/data only when the installation's Hermes root is actually /opt/data
    # (the container/hosted layout) or when HERMES_DASHBOARD_FILES_ROOT is set.
    if _default_hermes_root_is_opt_data():
        if create_root:
            root = _ensure_managed_root(_HOSTED_MANAGED_FILES_ROOT)
        else:
            raw_home = os.environ.get("HERMES_HOME", "").strip()
            if raw_home.replace("\\", "/").rstrip("/") == _HOSTED_MANAGED_FILES_ROOT_TEXT:
                root = PurePosixPath(_HOSTED_MANAGED_FILES_ROOT_TEXT)
            else:
                root = _HOSTED_MANAGED_FILES_ROOT
        return ManagedFilesPolicy(default_path=root, locked_root=root, can_change_path=False)

    home = _dashboard_home_path()
    return ManagedFilesPolicy(default_path=home, locked_root=None, can_change_path=True)


def _resolve_managed_path(
    raw_path: str | None,
    request: Request,
    *,
    for_write: bool = False,
) -> tuple[ManagedFilesPolicy, Path, str]:
    policy = _managed_files_policy(request)
    text = _path_text(raw_path)
    root = policy.locked_root

    if root is not None and (not text or text in {".", "/"}):
        candidate = root
    elif not text:
        candidate = policy.default_path
    else:
        candidate = Path(text).expanduser()
        if root is not None and not candidate.is_absolute():
            if any(part == ".." for part in candidate.parts):
                raise HTTPException(status_code=400, detail="Path cannot contain '..'")
            candidate = root / candidate
        elif not candidate.is_absolute():
            raise HTTPException(status_code=400, detail="Path must be absolute")

    if ".." in candidate.parts:
        raise HTTPException(status_code=400, detail="Path cannot contain '..'")

    if for_write and not candidate.exists():
        parent = _canonical_path(candidate.parent)
        resolved = parent / candidate.name
    else:
        resolved = _canonical_path(candidate, require_exists=not for_write)

    if root is not None and not _path_is_under(root, resolved):
        raise HTTPException(status_code=403, detail="Path outside managed files root")

    return policy, resolved, str(resolved)


def _managed_response_meta(policy: ManagedFilesPolicy) -> Dict[str, Any]:
    locked_root = str(policy.locked_root) if policy.locked_root is not None else None
    return {
        "root": locked_root,
        "locked_root": locked_root,
        "can_change_path": policy.can_change_path,
    }


def _managed_file_entry(policy: ManagedFilesPolicy, target: Path) -> Dict[str, Any]:
    try:
        resolved = target.resolve()
    except (OSError, RuntimeError):
        raise HTTPException(status_code=400, detail="Invalid path")
    if policy.locked_root is not None and not _path_is_under(policy.locked_root, resolved):
        raise HTTPException(status_code=403, detail="Path outside managed files root")

    try:
        st = resolved.stat()
    except OSError as exc:
        raise HTTPException(status_code=500, detail=f"Could not stat path: {exc}")

    is_dir = resolved.is_dir()
    mime_type = None if is_dir else (mimetypes.guess_type(resolved.name)[0] or "application/octet-stream")
    return {
        "name": target.name or resolved.name or str(resolved),
        "path": str(resolved),
        "is_directory": is_dir,
        "size": None if is_dir else st.st_size,
        "mtime": st.st_mtime,
        "mime_type": mime_type,
    }


