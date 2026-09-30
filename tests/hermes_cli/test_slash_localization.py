"""Exercise localized display through the existing registry and public CLI."""
from __future__ import annotations

import os
import re
from pathlib import Path
import subprocess
import sys

import pytest
from prompt_toolkit.completion import CompleteEvent
from prompt_toolkit.document import Document

from agent import i18n
from hermes_cli import commands


@pytest.fixture(autouse=True)
def clean_language(monkeypatch):
    monkeypatch.setenv("HERMES_LANGUAGE", "en")
    i18n.reset_language_cache()
    yield
    i18n.reset_language_cache()


def test_help_builder_switches_language_without_reimport(monkeypatch):
    english = commands.build_commands_by_category()
    monkeypatch.setenv("HERMES_LANGUAGE", "ja")
    japanese = commands.build_commands_by_category()
    assert "新しいセッション" in japanese["Session"]["/new"]
    assert "Start a new session" in english["Session"]["/new"]
    assert "エイリアス" in japanese["Session"]["/reset"]
    assert commands.resolve_command("reset") is commands.resolve_command("new")
    assert commands.category_label("Session") == "セッション"
    monkeypatch.setenv("HERMES_LANGUAGE", "en")
    assert commands.build_commands_by_category() == english


def test_missing_translation_retains_description_and_hint(monkeypatch):
    monkeypatch.setenv("HERMES_LANGUAGE", "ja")
    custom = commands.CommandDef("test_unknown", "English fallback", "Custom", args_hint="<text>")
    assert custom.describe() == "English fallback"
    rendered = commands._build_description(custom)
    assert "English fallback" in rendered
    assert "/test_unknown <text>" in rendered
    assert commands.category_label("Custom") == "Custom"


def test_description_fallback_preserves_literal_braces():
    custom = commands.CommandDef("test_literal", "Send {payload} or {\"name\": 1}", "Custom")
    assert custom.describe() == custom.description


def test_mutable_completion_table_preserves_overrides_additions_and_deletions(monkeypatch):
    monkeypatch.setenv("HERMES_LANGUAGE", "ja")
    monkeypatch.setitem(commands.COMMANDS, "/new", "Custom {payload}")
    monkeypatch.setitem(commands.COMMANDS, "/local-extension", "Local extension")
    monkeypatch.delitem(commands.COMMANDS, "/status")
    entries = list(commands.SlashCommandCompleter().get_completions(Document("/"), CompleteEvent(completion_requested=True)))
    names = {entry.text.strip() for entry in entries}
    assert "local-extension" in names
    assert "status" not in names
    selected = next(entry for entry in entries if entry.text.strip() == "new")
    assert "Custom {payload}" in "".join(text for _, text in selected.display_meta)


def test_mutable_help_table_is_used_by_public_filtered_help(monkeypatch, capsys):
    from cli import HermesCLI
    monkeypatch.setenv("HERMES_LANGUAGE", "ja")
    session = commands.COMMANDS_BY_CATEGORY["Session"]
    monkeypatch.setitem(session, "/new", "Custom {payload}")
    monkeypatch.setitem(session, "/local-extension", "Extension {literal}")
    monkeypatch.delitem(session, "/status")
    cli = HermesCLI.__new__(HermesCLI)
    cli.config, cli.agent, cli.model, cli.session_id = {}, None, "", "test-help"
    assert cli.process_command("/help") is True
    output = capsys.readouterr().out
    assert "Custom {payload}" in output
    assert "Extension {literal}" in output
    plain = re.sub(r"\x1b\[[0-?]*[ -/]*[@-~]", "", output)
    names = {line.split()[0] for line in plain.splitlines() if line.strip()}
    assert "/status" not in names
    assert cli.process_command("/help local-extension") is True
    filtered = capsys.readouterr().out
    assert "Extension {literal}" in filtered
    plain_filtered = re.sub(r"\x1b\[[0-?]*[ -/]*[@-~]", "", filtered)
    filtered_names = {line.split()[0] for line in plain_filtered.splitlines() if line.strip()}
    assert "/new" not in filtered_names


def test_localized_completion_retains_filter_and_plugin_coexistence(monkeypatch):
    from hermes_cli import plugins
    monkeypatch.setenv("HERMES_LANGUAGE", "ja")
    monkeypatch.setattr(plugins, "get_plugin_commands", lambda: {"local-plugin": {"description": "Plugin help"}})
    completer = commands.SlashCommandCompleter(command_filter=lambda name: name != "/new")
    entries = list(completer.get_completions(Document("/"), CompleteEvent(completion_requested=True)))
    names = {entry.text.strip() for entry in entries}
    assert "new" not in names
    assert "local-plugin" in names


def test_localized_help_preserves_command_visibility_and_uniqueness(monkeypatch):
    english = commands.build_commands()
    monkeypatch.setenv("HERMES_LANGUAGE", "ja")
    japanese = commands.build_commands()
    assert japanese.keys() == english.keys()
    assert "/approve" not in japanese
    assert "/clear" in japanese
    grouped = commands.build_commands_by_category()
    names = [name for entries in grouped.values() for name in entries]
    assert len(names) == len(set(names))
    assert set(names) == set(japanese)
    gateway = commands.gateway_help_lines()
    assert any("`/approve" in line for line in gateway)
    assert not any("`/clear" in line for line in gateway)
    assert any("新しいセッション" in line for line in gateway if "`/new" in line)


def test_existing_completer_uses_current_language(monkeypatch):
    completer = commands.SlashCommandCompleter()
    monkeypatch.setenv("HERMES_LANGUAGE", "ja")
    entries = list(completer.get_completions(Document("/new"), CompleteEvent(completion_requested=True)))
    selected = next(entry for entry in entries if entry.text == "new ")
    assert "新しいセッション" in "".join(text for _, text in selected.display_meta)


@pytest.mark.parametrize("language, category, description", [
    ("ja", "セッション", "新しいセッション"),
    ("unsupported-language", "Session", "Start a new session"),
    ("config-ja", "セッション", "新しいセッション"),
])
def test_public_help_native_subprocess(tmp_path, language, category, description):
    home = tmp_path / "テスト profile"
    home.mkdir()
    root = Path(__file__).resolve().parents[2]
    assert not (root / ".env").exists(), "Native test requires a checkout without project credentials"
    if language == "config-ja":
        (home / "config.yaml").write_text("display:\n  language: ja\n", encoding="utf-8")
    script = """
from cli import HermesCLI
cli = HermesCLI.__new__(HermesCLI)
cli.config = {}
cli.agent = None
cli.model = ''
cli.session_id = 'localization-test'
assert cli.process_command('/help') is True
"""
    env = {key: value for key, value in os.environ.items() if key.upper() in
           {"SYSTEMROOT", "WINDIR", "COMSPEC", "PATH", "PATHEXT", "TEMP", "TMP"}}
    env.update(HERMES_HOME=str(home), HOME=str(home), USERPROFILE=str(home),
               HERMES_BUNDLED_LOCALES=str(root / "locales"), PYTHONUTF8="1", PYTHONIOENCODING="utf-8")
    if language != "config-ja":
        env["HERMES_LANGUAGE"] = language
    result = subprocess.run([sys.executable, "-c", script], cwd=root, env=env,
                            encoding="utf-8", capture_output=True, timeout=60)
    assert result.returncode == 0, result.stderr
    assert category in result.stdout
    assert description in result.stdout
    assert "/reset" in result.stdout
    assert "slash.new.description" not in result.stdout
