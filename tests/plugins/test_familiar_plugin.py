"""Contract tests for the Familiar explicit-intent launch plugin.

The suite never launches Familiar or VRChat. Process status and creation are
injected or mocked at the plugin boundary.
"""

from __future__ import annotations

from unittest.mock import Mock

import pytest


@pytest.mark.parametrize(
    ("raw_text", "source", "platform"),
    [
        ("VRChat起動しないで", "user", "desktop"),
        ("「VRChat起動」と言った時だけ", "user", "desktop"),
        ("VRChat起動について", "user", "desktop"),
        ("VRChatを起動", "user", "desktop"),
        ("", "user", "desktop"),
        ("VRChat起動", "assistant", "desktop"),
        ("VRChat起動", "tool", "desktop"),
        ("VRChat起動", "cron", "desktop"),
        ("VRChat起動", "user", "cron"),
        ("VRChat起動", "user", "telegram"),
    ],
)
def test_launch_gate_rejects_near_matches_and_untrusted_sources(raw_text, source, platform):
    from plugins.familiar.core import allows_launch

    assert allows_launch(raw_text=raw_text, source=source, platform=platform) is False


@pytest.mark.parametrize("raw_text", ["VRChat起動", "  VRChat起動\r\n"])
def test_launch_gate_accepts_only_stripped_exact_desktop_user_request(raw_text):
    from plugins.familiar.core import allows_launch

    assert allows_launch(raw_text=raw_text, source="user", platform="desktop") is True


def test_exact_request_spawns_once_with_official_clone_command(tmp_path):
    from plugins.familiar.core import request_launch

    vendor = tmp_path / "familiar"
    vendor.mkdir()
    (vendor / "pyproject.toml").write_text("[project]\nname='vrc-familiar'\n", encoding="utf-8")
    status_probe = Mock(return_value=False)
    spawn = Mock(return_value=object())

    result = request_launch(
        raw_text="VRChat起動",
        source="user",
        platform="desktop",
        vendor_dir=vendor,
        uv_executable="uv",
        status_probe=status_probe,
        spawn=spawn,
    )

    assert result["status"] == "started"
    status_probe.assert_called_once_with("uv", vendor)
    spawn.assert_called_once_with("uv", vendor)


def test_vrchat_process_detection_alone_never_reaches_status_or_spawn(tmp_path):
    from plugins.familiar.core import request_launch

    status_probe = Mock(return_value=False)
    spawn = Mock()

    result = request_launch(
        raw_text="",
        source="user",
        platform="desktop",
        vendor_dir=tmp_path / "familiar",
        uv_executable="uv",
        status_probe=status_probe,
        spawn=spawn,
        vrchat_process_detected=True,
    )

    assert result["status"] == "ignored"
    status_probe.assert_not_called()
    spawn.assert_not_called()


def test_exact_request_is_idempotent_when_familiar_is_running(tmp_path):
    from plugins.familiar.core import request_launch

    vendor = tmp_path / "familiar"
    vendor.mkdir()
    (vendor / "pyproject.toml").write_text("[project]\nname='vrc-familiar'\n", encoding="utf-8")
    status_probe = Mock(return_value=True)
    spawn = Mock()

    result = request_launch(
        raw_text="VRChat起動",
        source="user",
        platform="desktop",
        vendor_dir=vendor,
        uv_executable="uv",
        status_probe=status_probe,
        spawn=spawn,
    )

    assert result["status"] == "already_running"
    spawn.assert_not_called()


def test_plugin_registers_hook_without_model_callable_tools(monkeypatch):
    import plugins.familiar as plugin

    calls = {"hooks": [], "tools": []}

    class Context:
        def register_hook(self, name, callback):
            calls["hooks"].append((name, callback))

        def register_tool(self, **kwargs):
            calls["tools"].append(kwargs)

    monkeypatch.setattr(plugin.core, "request_launch", Mock(return_value={"status": "ignored"}))
    plugin.register(Context())

    assert [name for name, _ in calls["hooks"]] == ["pre_llm_call"]
    assert calls["tools"] == []

    hook = calls["hooks"][0][1]
    hook(user_message="VRChat起動", platform="desktop")
    plugin.core.request_launch.assert_called_once()
    kwargs = plugin.core.request_launch.call_args.kwargs
    assert kwargs["raw_text"] == "VRChat起動"
    assert kwargs["source"] == "user"
    assert kwargs["platform"] == "desktop"


def test_spawn_wrapper_uses_official_clone_entrypoint_and_hidden_process(tmp_path):
    import subprocess

    from plugins.familiar.core import _spawn_familiar

    vendor = tmp_path / "familiar"
    vendor.mkdir()
    log_path = tmp_path / "familiar.log"
    popen = Mock(return_value=object())

    _spawn_familiar("uv.exe", vendor, popen=popen, log_path=log_path)

    argv = popen.call_args.args[0]
    kwargs = popen.call_args.kwargs
    assert argv == ["uv.exe", "run", "familiar", "run", "--print", "none"]
    assert kwargs["cwd"] == vendor
    assert kwargs["stdin"] is subprocess.DEVNULL
    assert kwargs["stdout"] is subprocess.DEVNULL
    assert kwargs["creationflags"] == (
        getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
        | getattr(subprocess, "CREATE_NO_WINDOW", 0)
    )


def test_missing_vendor_checkout_fails_without_spawning(tmp_path):
    from plugins.familiar.core import request_launch

    spawn = Mock()
    result = request_launch(
        raw_text="VRChat起動",
        source="user",
        platform="desktop",
        vendor_dir=tmp_path / "missing",
        uv_executable="uv",
        status_probe=Mock(return_value=False),
        spawn=spawn,
    )

    assert result["status"] == "unavailable"
    assert result["reason"] == "vendor_missing"
    spawn.assert_not_called()
