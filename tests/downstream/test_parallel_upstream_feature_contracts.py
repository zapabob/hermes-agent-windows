"""Parallel-track contracts for TRACK B UX adoption.

Covers local diagnostics, cron continuity sanitize, and command-palette
select≠exec / Ctrl+P / dangerous-action authorities.
"""

from __future__ import annotations

import zipfile
from pathlib import Path

import hermes_cli.command_palette_security as palette
import hermes_cli.diagnostics_local_export as lex
from cron.continuity_sanitize import (
    format_continuity_section,
    sanitize_continuity_text,
)


def test_local_export_filename_contract():
    name = lex.make_bundle_filename()
    assert name.startswith("Hermes-Diagnostics-")
    assert name.endswith(".zip")


def test_local_export_module_has_no_upload_imports():
    import ast

    mod_path = Path(lex.__file__)
    tree = ast.parse(mod_path.read_text(encoding="utf-8"))
    imported: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                imported.add(alias.name.split(".")[0])
        elif isinstance(node, ast.ImportFrom):
            if node.module:
                imported.add(node.module.split(".")[0])
                imported.add(node.module)

    assert "urllib" not in imported
    assert "hermes_cli.diagnostics_upload" not in imported
    assert "diagnostics_upload" not in imported


def test_zip_bytes_never_claims_unredacted():
    blob = lex.build_local_zip_bytes({"report": "hello"}, metadata={"redacted": False})
    with zipfile.ZipFile(__import__("io").BytesIO(blob)) as zf:
        import json

        manifest = json.loads(zf.read("manifest.json"))
    assert manifest["redacted"] is True


def test_command_palette_select_ne_exec():
    assert palette.palette_selection_mode() == "prefill_only"
    assert palette.palette_may_open(approval_active=True) is False
    assert palette.format_palette_prefill("/status") == "/status "


def test_command_palette_dangerous_slash_still_prefill_only():
    assert palette.is_dangerous_palette_slash("/yolo") is True
    assert palette.palette_selection_mode() == "prefill_only"


def test_cron_continuity_secret_removed():
    raw = "token=ghp_abcdefghijklmnopqrstuvwxyz0123456789ABCD"
    out = sanitize_continuity_text(raw)
    assert "abcdefghijklmnopqrstuvwxyz0123456789ABCD" not in out


def test_cron_continuity_untrusted_and_no_memory_promotion():
    section = format_continuity_section("prior", is_self=True)
    assert "UNTRUSTED" in section
    assert "durable memory" in section.lower()
