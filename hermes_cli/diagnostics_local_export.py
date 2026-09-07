"""Local-first diagnostics export (Windows Workstation Edition).

Primary action for Desktop diagnostics is a ZIP written to disk — never a
Nous-internal upload. Collection and redaction reuse the shared CLI pipeline
(``collect_share_bundle`` / ``_redact_log_text``) so local and remote paths
cannot diverge on the safety boundary.

Network I/O is intentionally absent from this module. Remote upload stays in
``hermes_cli.diagnostics_upload`` and is opt-in only.
"""

from __future__ import annotations

import io
import json
import logging
import platform
import sys
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Optional

from hermes_constants import get_hermes_home

logger = logging.getLogger(__name__)

LOCAL_BUNDLE_FORMAT = "hermes-diagnostics-local/1"
_MAX_EXTRA_FILES = 4
_MAX_EXTRA_BYTES = 524_288
_MAX_ERROR_CONTEXT = 8_000


def default_export_dir() -> Path:
    """Profile-scoped export directory (created on write)."""
    return get_hermes_home() / "diagnostics-exports"


def make_bundle_filename(when: Optional[datetime] = None) -> str:
    """Return ``Hermes-Diagnostics-YYYYMMDD-HHMMSS.zip`` (UTC)."""
    stamp = (when or datetime.now(timezone.utc)).strftime("%Y%m%d-%H%M%S")
    return f"Hermes-Diagnostics-{stamp}.zip"


def _sanitize_extra_label(label: str) -> str:
    safe = "".join(ch for ch in label if ch.isalnum() or ch in "._- ()").strip()[:64]
    while ".." in safe:
        safe = safe.replace("..", ".")
    return safe.lstrip(".").strip()


def attach_client_artifacts(
    bundle: dict[str, str],
    *,
    error_context: Optional[str] = None,
    extra_files: Optional[Mapping[str, str]] = None,
) -> dict[str, str]:
    """Force-redact and attach client-supplied text into *bundle*.

    Mirrors the sanitization rules of ``diagnostics.share_nous`` so the local
    export cannot carry secrets the upload path would have stripped.
    """
    from hermes_cli.debug import _redact_log_text

    out = dict(bundle)

    if isinstance(error_context, str) and error_context.strip():
        out["error-context.txt"] = _redact_log_text(error_context.strip()[:_MAX_ERROR_CONTEXT])

    if isinstance(extra_files, Mapping):
        for label, text in list(extra_files.items())[:_MAX_EXTRA_FILES]:
            if not isinstance(label, str) or not isinstance(text, str):
                continue
            safe_label = _sanitize_extra_label(label)
            if not safe_label or not text.strip():
                continue
            out[f"client/{safe_label}"] = _redact_log_text(text[:_MAX_EXTRA_BYTES])

    return out


def collect_identity_metadata() -> dict[str, Any]:
    """Non-secret identity block for the ZIP manifest."""
    meta: dict[str, Any] = {
        "format": LOCAL_BUNDLE_FORMAT,
        "redacted": True,
        "created": datetime.now(timezone.utc).isoformat(),
        "platform": {
            "system": platform.system(),
            "release": platform.release(),
            "machine": platform.machine(),
            "python": sys.version.split()[0],
        },
    }
    try:
        from hermes_cli import __version__

        meta["hermes_version"] = __version__
    except Exception:
        meta["hermes_version"] = None

    # Best-effort git identity — never fail the export if git is unavailable.
    try:
        import subprocess

        root = Path(__file__).resolve().parents[1]
        sha = subprocess.check_output(
            ["git", "rev-parse", "HEAD"],
            cwd=str(root),
            stderr=subprocess.DEVNULL,
            timeout=5,
            text=True,
            encoding="utf-8",
        ).strip()
        if sha:
            meta["downstream_sha"] = sha
    except Exception:
        meta["downstream_sha"] = None

    try:
        snapshot = Path(__file__).resolve().parents[1] / ".codex" / "UPSTREAM_SNAPSHOT.json"
        if snapshot.is_file():
            data = json.loads(snapshot.read_text(encoding="utf-8"))
            frozen = data.get("sha") or data.get("upstream_sha") or data.get("commit")
            if isinstance(frozen, str) and frozen.strip():
                meta["frozen_upstream_sha"] = frozen.strip()
    except Exception:
        pass

    return meta


def build_local_zip_bytes(
    files: Mapping[str, str],
    *,
    metadata: Optional[Mapping[str, Any]] = None,
) -> bytes:
    """Pack redacted text files + manifest.json into a ZIP (in memory)."""
    meta = dict(metadata or collect_identity_metadata())
    meta["redacted"] = True  # never allow a false claim
    meta["format"] = LOCAL_BUNDLE_FORMAT
    meta["file_names"] = sorted(files.keys())

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, mode="w", compression=zipfile.ZIP_DEFLATED) as zf:
        zf.writestr(
            "manifest.json",
            json.dumps(meta, ensure_ascii=False, indent=2) + "\n",
        )
        for name, text in sorted(files.items()):
            # ZIP members are paths; reject empty / traversal-shaped names.
            safe_name = name.replace("\\", "/").lstrip("/")
            if not safe_name or ".." in safe_name.split("/"):
                continue
            zf.writestr(safe_name, text if text.endswith("\n") else text + "\n")
    return buf.getvalue()


def export_local_diagnostics(
    *,
    log_lines: int = 200,
    error_context: Optional[str] = None,
    extra_files: Optional[Mapping[str, str]] = None,
    destination_dir: Optional[Path] = None,
) -> dict[str, Any]:
    """Collect, force-redact, and write a local diagnostics ZIP.

    Returns ``{"ok": True, "path": <abs>, "filename": ..., "redacted": True}``
    or ``{"ok": False, "error": ...}``. Never performs network I/O.
    """
    try:
        from hermes_cli.debug import collect_share_bundle

        if not isinstance(log_lines, int) or not (10 <= log_lines <= 2000):
            log_lines = 200

        # Redaction is NOT optional on the local path either — the ZIP may
        # still be attached to a GitHub issue or mailed to support.
        bundle = collect_share_bundle(log_lines=log_lines, redact=True)
        bundle = attach_client_artifacts(
            bundle,
            error_context=error_context,
            extra_files=extra_files,
        )

        dest = Path(destination_dir) if destination_dir else default_export_dir()
        dest.mkdir(parents=True, exist_ok=True)
        filename = make_bundle_filename()
        path = dest / filename

        blob = build_local_zip_bytes(bundle)
        path.write_bytes(blob)

        logger.info("diagnostics local export written to %s (%d bytes)", path, len(blob))
        return {
            "ok": True,
            "path": str(path.resolve()),
            "filename": filename,
            "redacted": True,
            "bytes": len(blob),
        }
    except Exception as exc:
        logger.exception("diagnostics local export failed")
        return {"ok": False, "error": str(exc)}
