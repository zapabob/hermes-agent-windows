#!/usr/bin/env python3
"""Bind a family receipt to explicitly scoped source freshness only."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import stat
import subprocess
from collections.abc import Mapping, Sequence
from typing import Any

SCHEMA_VERSION = 1
RECEIPT_KIND = "SOURCE_FRESHNESS_ONLY"
HEAD_RE = re.compile(r"^(?:[0-9a-f]{40}|[0-9a-f]{64})$")
DIGEST_RE = re.compile(r"^[0-9a-f]{64}$")
IDENTITY_FIELDS = ("campaign", "family", "packet", "rv")
_BINDING_FIELDS = {"schema_version", "head", "scope", "source_digest"}
_RECEIPT_FIELDS = {
    "schema_version", "kind", "campaign", "family", "packet", "rv",
    "head", "scope", "source_digest",
}
_WINDOWS_REPARSE_POINT = 0x0400


class ReceiptError(RuntimeError):
    """A fail-closed source binding operation with a stable result code."""

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


def _clean_git_env() -> dict[str, str]:
    allowed = {
        "PATH", "SYSTEMROOT", "WINDIR", "COMSPEC", "PATHEXT", "TEMP", "TMP",
        "TMPDIR", "LANG", "LC_ALL",
    }
    env = {key: value for key, value in os.environ.items() if key.upper() in allowed}
    env.update({
        "GIT_CONFIG_GLOBAL": os.devnull,
        "GIT_CONFIG_NOSYSTEM": "1",
        "GIT_NO_REPLACE_OBJECTS": "1",
        "GIT_OPTIONAL_LOCKS": "0",
        "GIT_TERMINAL_PROMPT": "0",
    })
    return env


def _git(repo: Path, *args: str) -> bytes:
    command = [
        "git", "--no-pager", "-C", str(repo),
        "-c", "core.fsmonitor=false", "-c", "core.quotepath=false", *args,
    ]
    try:
        result = subprocess.run(
            command,
            stdin=subprocess.DEVNULL,
            capture_output=True,
            env=_clean_git_env(),
            timeout=30,
            check=False,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise ReceiptError("GIT_UNAVAILABLE_OR_TIMEOUT") from exc
    if result.returncode:
        command_name = args[0] if args else "unknown"
        raise ReceiptError(f"GIT_COMMAND_FAILED_{command_name.upper().replace('-', '_')}")
    return result.stdout


def _current_head(repo: Path) -> str:
    try:
        value = _git(repo, "rev-parse", "--verify", "HEAD^{commit}").decode("ascii").strip()
    except UnicodeError as exc:
        raise ReceiptError("HEAD_INVALID") from exc
    if HEAD_RE.fullmatch(value) is None:
        raise ReceiptError("HEAD_INVALID")
    return value


def _repo_root(repo: str | os.PathLike[str]) -> Path:
    try:
        root = Path(repo).resolve(strict=True)
    except (OSError, RuntimeError, TypeError, ValueError) as exc:
        raise ReceiptError("REPO_INVALID") from exc
    if not root.is_dir():
        raise ReceiptError("REPO_INVALID")
    try:
        reported = _git(root, "rev-parse", "--show-toplevel").decode("utf-8", errors="strict").strip()
        reported_root = Path(reported).resolve(strict=True)
    except (OSError, RuntimeError, UnicodeError) as exc:
        raise ReceiptError("REPOSITORY_UNAVAILABLE") from exc
    if os.path.normcase(os.path.normpath(str(reported_root))) != os.path.normcase(os.path.normpath(str(root))):
        raise ReceiptError("REPOSITORY_ROOT_MISMATCH")
    return root


def _validate_path(value: object) -> str:
    if not isinstance(value, str) or not value or "\x00" in value or "\\" in value:
        raise ReceiptError("PATH_INVALID")
    try:
        value.encode("utf-8", errors="strict")
    except UnicodeError as exc:
        raise ReceiptError("PATH_INVALID") from exc
    pure = PurePosixPath(value)
    if (
        pure.is_absolute()
        or pure.as_posix() != value
        or any(part in {"", ".", ".."} for part in value.split("/"))
        or re.match(r"^[A-Za-z]:", value) is not None
        or (os.name == "nt" and ":" in value)
    ):
        raise ReceiptError("PATH_INVALID")
    return value


def _normalise_scope(value: object) -> list[str]:
    if not isinstance(value, (list, tuple)) or not value:
        raise ReceiptError("SCOPE_INVALID")
    paths = [_validate_path(path) for path in value]
    if len(paths) != len(set(paths)):
        raise ReceiptError("SCOPE_DUPLICATE")
    return sorted(paths)


def _strict_identity(values: Mapping[str, object]) -> dict[str, str]:
    result: dict[str, str] = {}
    for field in IDENTITY_FIELDS:
        value = values.get(field)
        if (
            not isinstance(value, str)
            or not value
            or value != value.strip()
            or any(ord(character) < 32 or ord(character) == 127 for character in value)
        ):
            raise ReceiptError("IDENTITY_INVALID")
        try:
            value.encode("utf-8", errors="strict")
        except UnicodeError as exc:
            raise ReceiptError("IDENTITY_INVALID") from exc
        result[field] = value
    return result


def _is_reparse(info: os.stat_result) -> bool:
    attributes = getattr(info, "st_file_attributes", 0)
    return stat.S_ISLNK(info.st_mode) or bool(attributes & _WINDOWS_REPARSE_POINT)


def _stable_time_ns(info: os.stat_result, *, windows: bool = os.name == "nt") -> int:
    # st_ctime is deprecated on Windows since Python 3.12 (os.stat_result docs):
    # path stat reports creation time while fstat reports metadata change time,
    # so only st_birthtime_ns is comparable across the two calls.
    if windows:
        birth = getattr(info, "st_birthtime_ns", None)
        if birth is not None:
            return birth
    return info.st_ctime_ns


def _file_identity(info: os.stat_result) -> tuple[int, int, int, int, int, int, int]:
    return (
        info.st_dev,
        info.st_ino,
        info.st_size,
        info.st_mtime_ns,
        _stable_time_ns(info),
        info.st_mode,
        getattr(info, "st_file_attributes", 0),
    )


def _inspect_scoped_file(root: Path, relative: str) -> tuple[Path, os.stat_result]:
    candidate = root
    components = relative.split("/")
    for index, component in enumerate(components):
        candidate = candidate / component
        try:
            info = candidate.lstat()
        except FileNotFoundError as exc:
            raise ReceiptError("SOURCE_MISSING") from exc
        except OSError as exc:
            raise ReceiptError("SOURCE_UNREADABLE") from exc
        if _is_reparse(info):
            raise ReceiptError("PATH_REPARSE_REFUSED")
        final_component = index == len(components) - 1
        if not final_component and not stat.S_ISDIR(info.st_mode):
            raise ReceiptError("PATH_NOT_DIRECTORY")
        if final_component and not stat.S_ISREG(info.st_mode):
            raise ReceiptError("SOURCE_NOT_REGULAR")
    try:
        resolved = candidate.resolve(strict=True)
        resolved.relative_to(root)
    except (OSError, RuntimeError, ValueError) as exc:
        raise ReceiptError("PATH_OUTSIDE_REPO") from exc
    return candidate, info


def _worktree_digest(root: Path, relative: str) -> tuple[str, tuple[int, int, int, int, int, int, int]]:
    candidate, initial_info = _inspect_scoped_file(root, relative)
    initial_identity = _file_identity(initial_info)
    flags = os.O_RDONLY | getattr(os, "O_BINARY", 0) | getattr(os, "O_NOINHERIT", 0)
    flags |= getattr(os, "O_NOFOLLOW", 0)
    try:
        descriptor = os.open(candidate, flags)
    except FileNotFoundError as exc:
        raise ReceiptError("SOURCE_MISSING") from exc
    except OSError as exc:
        raise ReceiptError("SOURCE_UNREADABLE") from exc
    digest = hashlib.sha256()
    try:
        opened_info = os.fstat(descriptor)
        if _is_reparse(opened_info) or _file_identity(opened_info) != initial_identity:
            raise ReceiptError("SOURCE_CHANGED_DURING_CAPTURE")
        while True:
            try:
                block = os.read(descriptor, 1024 * 1024)
            except OSError as exc:
                raise ReceiptError("SOURCE_UNREADABLE") from exc
            if not block:
                break
            digest.update(block)
        final_handle_info = os.fstat(descriptor)
        if _file_identity(final_handle_info) != initial_identity:
            raise ReceiptError("SOURCE_CHANGED_DURING_CAPTURE")
    finally:
        os.close(descriptor)
    _, final_path_info = _inspect_scoped_file(root, relative)
    if _file_identity(final_path_info) != initial_identity:
        raise ReceiptError("SOURCE_CHANGED_DURING_CAPTURE")
    return digest.hexdigest(), initial_identity


def _pathspec(path: str) -> str:
    return f":(literal){path}"


def _scoped_records(root: Path, scope: Sequence[str]) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for relative in scope:
        pathspec = _pathspec(relative)
        status = _git(
            root,
            "status", "--porcelain=v1", "-z", "--untracked-files=all", "--ignored=no",
            "--no-renames", "--", pathspec,
        )
        index = _git(root, "ls-files", "--stage", "-z", "--", pathspec)
        worktree_digest, identity = _worktree_digest(root, relative)
        records.append({
            "path": relative,
            "status_hex": status.hex(),
            "index_hex": index.hex(),
            "worktree_sha256": worktree_digest,
            "_identity": identity,
        })
    return records


def _source_digest(records: Sequence[Mapping[str, Any]]) -> str:
    canonical_records = [
        {
            "path": record["path"],
            "status_hex": record["status_hex"],
            "index_hex": record["index_hex"],
            "worktree_sha256": record["worktree_sha256"],
        }
        for record in records
    ]
    serialized = json.dumps(
        canonical_records,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8", errors="strict")
    return hashlib.sha256(serialized).hexdigest()


def _binding(value: object, *, code_prefix: str) -> dict[str, Any]:
    if not isinstance(value, Mapping) or set(value) != _BINDING_FIELDS:
        raise ReceiptError(f"{code_prefix}_SCHEMA_INVALID")
    if type(value["schema_version"]) is not int or value["schema_version"] != SCHEMA_VERSION:
        raise ReceiptError(f"{code_prefix}_SCHEMA_INVALID")
    head = value["head"]
    digest = value["source_digest"]
    scope = value["scope"]
    if not isinstance(head, str) or HEAD_RE.fullmatch(head) is None:
        raise ReceiptError(f"{code_prefix}_HEAD_INVALID")
    if not isinstance(digest, str) or DIGEST_RE.fullmatch(digest) is None:
        raise ReceiptError(f"{code_prefix}_DIGEST_INVALID")
    if not isinstance(scope, list):
        raise ReceiptError(f"{code_prefix}_SCOPE_INVALID")
    try:
        normalised = _normalise_scope(scope)
    except ReceiptError as exc:
        raise ReceiptError(f"{code_prefix}_SCOPE_INVALID") from exc
    if scope != normalised:
        raise ReceiptError(f"{code_prefix}_SCOPE_INVALID")
    return {
        "schema_version": SCHEMA_VERSION,
        "head": head,
        "scope": list(scope),
        "source_digest": digest,
    }


def capture_source_binding(
    repo: str | os.PathLike[str], expected_scope: object
) -> dict[str, Any]:
    """Capture scoped Git/index/worktree state without traversing unrelated paths.

    Rechecks reject observed changes and static reparse points; this is not an
    atomic no-follow traversal or a cross-process edit lease.
    """
    try:
        root = _repo_root(repo)
        scope = _normalise_scope(expected_scope)
        head_before = _current_head(root)
        first_records = _scoped_records(root, scope)
        second_records = _scoped_records(root, scope)
        head_after = _current_head(root)
        if head_before != head_after:
            raise ReceiptError("CAPTURE_HEAD_CHANGED")
        if first_records != second_records:
            raise ReceiptError("CAPTURE_SOURCE_CHANGED")
        return {
            "schema_version": SCHEMA_VERSION,
            "head": head_before,
            "scope": scope,
            "source_digest": _source_digest(first_records),
        }
    except ReceiptError:
        raise
    except Exception as exc:
        raise ReceiptError("CAPTURE_FAILED") from exc


def create_family_receipt(
    binding: object,
    campaign: object,
    family: object,
    packet: object,
    rv: object,
) -> dict[str, Any]:
    """Create a freshness-only receipt; it grants no semantic or write authority."""
    checked_binding = _binding(binding, code_prefix="BINDING")
    identity = _strict_identity({
        "campaign": campaign,
        "family": family,
        "packet": packet,
        "rv": rv,
    })
    return {
        "schema_version": SCHEMA_VERSION,
        "kind": RECEIPT_KIND,
        **identity,
        **checked_binding,
    }


def validate_family_receipt(
    receipt: object,
    *,
    campaign: object,
    family: object,
    packet: object,
    rv: object,
    expected_scope: object,
    current_binding: object,
) -> dict[str, Any]:
    """Compare a receipt with a fresh binding supplied by the trusted Integrator.

    Callers must obtain ``current_binding`` from ``capture_source_binding`` on
    the current repository immediately before validation. This function only
    compares the supplied values; it does not reopen the repository, establish
    who created either value, or provide signature/authenticity guarantees.
    """
    try:
        expected_identity = _strict_identity({
            "campaign": campaign,
            "family": family,
            "packet": packet,
            "rv": rv,
        })
    except ReceiptError:
        return {"valid": False, "code": "EXPECTED_IDENTITY_INVALID"}
    try:
        scope = _normalise_scope(expected_scope)
    except ReceiptError:
        return {"valid": False, "code": "EXPECTED_SCOPE_INVALID"}
    if not isinstance(receipt, Mapping) or set(receipt) != _RECEIPT_FIELDS:
        return {"valid": False, "code": "RECEIPT_SCHEMA_INVALID"}
    if type(receipt["schema_version"]) is not int or receipt["schema_version"] != SCHEMA_VERSION:
        return {"valid": False, "code": "RECEIPT_SCHEMA_INVALID"}
    if receipt["kind"] != RECEIPT_KIND or not isinstance(receipt["kind"], str):
        return {"valid": False, "code": "RECEIPT_SCHEMA_INVALID"}
    try:
        receipt_identity = _strict_identity({field: receipt[field] for field in IDENTITY_FIELDS})
        receipt_binding = _binding(
            {field: receipt[field] for field in _BINDING_FIELDS},
            code_prefix="RECEIPT",
        )
    except (ReceiptError, KeyError):
        return {"valid": False, "code": "RECEIPT_SCHEMA_INVALID"}
    try:
        current = _binding(current_binding, code_prefix="CURRENT_BINDING")
    except ReceiptError:
        return {"valid": False, "code": "CURRENT_BINDING_INVALID"}
    if receipt_identity != expected_identity:
        return {"valid": False, "code": "IDENTITY_MISMATCH"}
    if receipt_binding["scope"] != scope or current["scope"] != scope:
        return {"valid": False, "code": "SCOPE_MISMATCH"}
    if receipt_binding["head"] != current["head"]:
        return {"valid": False, "code": "HEAD_MISMATCH"}
    if receipt_binding["source_digest"] != current["source_digest"]:
        return {"valid": False, "code": "SOURCE_FINGERPRINT_MISMATCH"}
    return {"valid": True, "code": "VALID"}
