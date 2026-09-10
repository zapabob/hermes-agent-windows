"""Harness daemon Windows launch flags: CREATE_NO_WINDOW, never DETACHED_PROCESS."""

from __future__ import annotations

import pytest

from hermes_cli._subprocess_compat import (
    windows_detach_flags,
    windows_detach_flags_without_breakaway,
)

_DETACHED_PROCESS = 0x00000008
_CREATE_NO_WINDOW = 0x08000000


@pytest.mark.windows_only
def test_windows_detach_flags_hide_console_without_detached() -> None:
    flags = windows_detach_flags()
    assert flags & _CREATE_NO_WINDOW == _CREATE_NO_WINDOW
    assert flags & _DETACHED_PROCESS == 0

    no_breakaway = windows_detach_flags_without_breakaway()
    assert no_breakaway & _CREATE_NO_WINDOW == _CREATE_NO_WINDOW
    assert no_breakaway & _DETACHED_PROCESS == 0
    assert no_breakaway != 0


def test_windows_detach_flags_zero_off_windows(monkeypatch: pytest.MonkeyPatch) -> None:
    import hermes_cli._subprocess_compat as compat

    monkeypatch.setattr(compat, "IS_WINDOWS", False)
    assert windows_detach_flags() == 0
    assert windows_detach_flags_without_breakaway() == 0
