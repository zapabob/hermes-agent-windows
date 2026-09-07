"""CLI / Desktop command-palette security contracts (Windows Workstation Edition).

CodeGraph 2026-09-08:
  - Desktop owner: apps/desktop command-palette + store (mod+k / mod+p)
  - CLI owner: cli.HermesCLI._open_command_palette (c-p)
  - Forbidden: palette-specific subprocess / credential / approval bypass

Selection on the CLI palette **prefills** the composer only — it never
auto-executes slash commands. Dangerous terminal commands still flow through
the existing approval modal after the user submits.
"""

from __future__ import annotations

from typing import Any, Mapping, Optional

# Slash commands that change approval posture or run host commands. Palette
# may still *prefill* these, but must never auto-submit them.
DANGEROUS_PALETTE_SLASH_PREFIXES: tuple[str, ...] = (
    "/yolo",
    "/exec",
    "/terminal",
    "/shell",
    "/sudo",
)


def palette_may_open(
    *,
    approval_active: bool = False,
    model_picker_active: bool = False,
    clarify_active: bool = False,
    slash_confirm_active: bool = False,
    sudo_active: bool = False,
    secret_active: bool = False,
    palette_already_open: bool = False,
) -> bool:
    """Return True when Ctrl+P may open the CLI command palette.

    Approval / secret / confirm modals win — palette must not steal focus or
    provide an alternate path around those gates.
    """
    if palette_already_open:
        return False
    if approval_active or model_picker_active or clarify_active:
        return False
    if slash_confirm_active or sudo_active or secret_active:
        return False
    return True


def palette_selection_mode() -> str:
    """CLI palette selection is always insert-only (never execute)."""
    return "prefill_only"


def is_dangerous_palette_slash(command: str) -> bool:
    """True when the exact slash string is approval-sensitive."""
    name = (command or "").strip().lower()
    if not name:
        return False
    if not name.startswith("/"):
        name = f"/{name}"
    bare = name.split()[0]
    return bare in DANGEROUS_PALETTE_SLASH_PREFIXES


def format_palette_prefill(command: str) -> str:
    """Canonical composer prefill: exact command + trailing space for args."""
    cmd = (command or "").strip()
    if not cmd:
        return ""
    if not cmd.startswith("/"):
        cmd = f"/{cmd}"
    return f"{cmd} "


def cli_modal_flags_from_instance(cli: Any) -> Mapping[str, bool]:
    """Derive palette_may_open kwargs from a HermesCLI-like object."""
    return {
        "approval_active": bool(getattr(cli, "_approval_state", None)),
        "model_picker_active": bool(getattr(cli, "_model_picker_state", None)),
        "clarify_active": bool(getattr(cli, "_clarify_state", None)),
        "slash_confirm_active": bool(getattr(cli, "_slash_confirm_state", None)),
        "sudo_active": bool(getattr(cli, "_sudo_state", None)),
        "secret_active": bool(getattr(cli, "_secret_state", None)),
        "palette_already_open": bool(getattr(cli, "_command_palette_state", None)),
    }


def assert_selection_does_not_execute(
    *,
    process_command_called: bool,
    handle_slash_called: bool,
    buffer_text: Optional[str],
    expected_command: str,
) -> None:
    """Test helper contract: select ≠ exec."""
    if process_command_called or handle_slash_called:
        raise AssertionError("command palette selection must not auto-execute")
    expected = format_palette_prefill(expected_command)
    if buffer_text != expected:
        raise AssertionError(f"expected prefill {expected!r}, got {buffer_text!r}")
