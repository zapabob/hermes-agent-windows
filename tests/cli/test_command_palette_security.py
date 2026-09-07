"""CLI command palette security contracts (Ctrl+P / select≠exec)."""

from types import SimpleNamespace

from hermes_cli.command_palette_security import (
    assert_selection_does_not_execute,
    format_palette_prefill,
    is_dangerous_palette_slash,
    palette_may_open,
    palette_selection_mode,
)


class TestPaletteMayOpen:
    def test_blocked_when_approval_active(self):
        assert palette_may_open(approval_active=True) is False

    def test_blocked_when_secret_active(self):
        assert palette_may_open(secret_active=True) is False

    def test_open_when_idle(self):
        assert palette_may_open() is True


class TestSelectNeExec:
    def test_selection_mode_is_prefill_only(self):
        assert palette_selection_mode() == "prefill_only"

    def test_prefill_contract_helper(self):
        assert_selection_does_not_execute(
            process_command_called=False,
            handle_slash_called=False,
            buffer_text=format_palette_prefill("/model"),
            expected_command="/model",
        )

    def test_yolo_is_dangerous_but_still_prefill_only(self):
        assert is_dangerous_palette_slash("/yolo") is True
        assert palette_selection_mode() == "prefill_only"
        assert format_palette_prefill("/yolo") == "/yolo "


class TestCliPaletteWiresSecurity:
    def test_open_refuses_over_approval(self):
        from cli import HermesCLI

        cli = HermesCLI.__new__(HermesCLI)
        cli._command_palette_state = None
        cli._approval_state = {"choices": []}
        cli._model_picker_state = None
        cli._clarify_state = None
        cli._slash_confirm_state = None
        cli._sudo_state = None
        cli._secret_state = None
        cli._capture_modal_input_snapshot = lambda: None
        cli._invalidate = lambda **k: None
        cli._open_command_palette()
        assert cli._command_palette_state is None

    def test_selection_prefills_without_process_command(self):
        from cli import HermesCLI

        cli = HermesCLI.__new__(HermesCLI)
        cli._command_palette_state = {
            "entries": [("/yolo", "Session", "Toggle YOLO")],
            "filter": "",
            "selected": 0,
            "_scroll_offset": 0,
        }
        buf = SimpleNamespace(text="", cursor_position=0)
        cli._app = SimpleNamespace(current_buffer=buf)
        cli._invalidate = lambda **k: None
        cli._restore_modal_input_snapshot = lambda: None
        called = {"process": False}

        def _boom(*_a, **_k):
            called["process"] = True

        cli.process_command = _boom  # type: ignore[attr-defined]
        cli._handle_command_palette_selection()
        assert called["process"] is False
        assert buf.text == "/yolo "
        assert cli._command_palette_state is None
