"""Explicit channel ownership keeps credentials usable without duplicate listeners."""

import os

import pytest
import yaml

from gateway.config import Platform, load_gateway_config


@pytest.mark.asyncio
async def test_outbound_only_platform_never_constructs_an_inbound_adapter(
    monkeypatch, tmp_path
):
    from unittest.mock import AsyncMock

    from gateway.config import GatewayConfig, PlatformConfig
    from gateway.run import GatewayRunner

    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    runner = GatewayRunner(
        GatewayConfig(
            platforms={
                Platform.TELEGRAM: PlatformConfig(
                    enabled=True, token="synthetic", extra={"connection_enabled": False}
                )
            },
            sessions_dir=tmp_path / "sessions",
        )
    )

    def no_connection(*args):
        raise AssertionError(
            "Outbound-only profiles must not construct a receiving adapter"
        )

    monkeypatch.setattr(runner, "_create_adapter", no_connection)
    monkeypatch.setattr(
        runner, "_start_secondary_profile_adapters", AsyncMock(return_value=0)
    )
    try:
        await runner.start()
        assert not runner.adapters and not runner._failed_platforms
    finally:
        await runner.stop()


@pytest.mark.parametrize("platform_name", ["telegram", "discord", "line"])
@pytest.mark.parametrize("enabled", [True, False])
def test_connection_ownership_preserves_existing_send_permission(
    monkeypatch, tmp_path, platform_name, enabled
):
    """Exercise the actual send dispatcher without making an external request."""
    import json
    from types import SimpleNamespace
    from unittest.mock import AsyncMock

    from gateway.config import GatewayConfig, PlatformConfig
    from gateway.platform_registry import platform_registry
    from tools import send_message_tool
    import gateway.mirror
    import tools.interrupt

    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    platform = Platform(platform_name)
    pconfig = PlatformConfig(
        enabled=enabled,
        token="synthetic-owned-credential",
        extra={"connection_enabled": False},
    )
    monkeypatch.setattr(
        "gateway.config.load_gateway_config",
        lambda: GatewayConfig(platforms={platform: pconfig}),
    )
    monkeypatch.setattr(
        send_message_tool, "prepare_send_message_platforms", lambda: None
    )
    monkeypatch.setattr(
        send_message_tool,
        "resolve_send_target",
        lambda *args, **kwargs: ("synthetic-target", None, None),
    )
    monkeypatch.setattr(
        platform_registry,
        "get",
        lambda name: SimpleNamespace(send_message_handler=None),
    )
    monkeypatch.setattr(tools.interrupt, "is_interrupted", lambda: False)
    monkeypatch.setattr(
        gateway.mirror, "mirror_to_session", lambda *args, **kwargs: False
    )
    send = AsyncMock(return_value={"success": True})
    monkeypatch.setattr(send_message_tool, "_send_to_platform", send)
    result = json.loads(
        send_message_tool._handle_send({
            "target": platform_name + ":synthetic-target",
            "message": "synthetic local contract",
        })
    )
    if enabled:
        assert result["success"]
        send.assert_awaited_once()
        assert send.call_args.args[:4] == (
            platform,
            pconfig,
            "synthetic-target",
            "synthetic local contract",
        )
    else:
        assert not result.get("success", False)
        send.assert_not_called()


@pytest.mark.parametrize(
    "profile", ["default", "delivery-worker", "job-seeker", "secretary"]
)
def test_explicit_profile_channel_ownership_survives_ambient_credentials(
    profile, tmp_path, monkeypatch
):
    """Use the actual loader and plugin enablement; never start a connection."""
    for key in list(os.environ):
        if key.startswith(("TELEGRAM_", "DISCORD_", "LINE_", "BUZZ_", "PHOTON_")):
            monkeypatch.delenv(key)
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "synthetic-shared-telegram")
    monkeypatch.setenv("DISCORD_BOT_TOKEN", "synthetic-shared-discord")
    monkeypatch.setenv("BUZZ_RELAY_URL", "https://unused.invalid")
    monkeypatch.setenv("BUZZ_PRIVATE_KEY", "synthetic-unused-buzz")
    own_bots = profile == "default"
    config = {
        "platforms": {
            "buzz": {"enabled": False},
            "telegram": {"extra": {"connection_enabled": own_bots}},
            "discord": {"extra": {"connection_enabled": own_bots}},
        },
        "telegram": {"enabled": True},
        "discord": {"enabled": True},
    }
    if profile != "default":
        monkeypatch.setenv("LINE_CHANNEL_ACCESS_TOKEN", "synthetic-shared-line")
        monkeypatch.setenv("LINE_CHANNEL_SECRET", "synthetic-shared-line-secret")
        config["platforms"]["line"] = {
            "enabled": True,
            "extra": {"connection_enabled": profile == "delivery-worker"},
        }
    (tmp_path / "config.yaml").write_text(yaml.safe_dump(config), encoding="utf-8")

    loaded = load_gateway_config()

    assert loaded.platforms[Platform.TELEGRAM].enabled is True
    assert loaded.platforms[Platform.DISCORD].enabled is True
    assert loaded.platforms[Platform.TELEGRAM].connection_enabled is own_bots
    assert loaded.platforms[Platform.DISCORD].connection_enabled is own_bots
    assert loaded.platforms[Platform.TELEGRAM].token == "synthetic-shared-telegram"
    assert loaded.platforms[Platform.DISCORD].token == "synthetic-shared-discord"
    assert loaded.platforms[Platform("buzz")].enabled is False
    if profile != "default":
        assert loaded.platforms[Platform("line")].enabled is True
        assert loaded.platforms[Platform("line")].connection_enabled is (
            profile == "delivery-worker"
        )


@pytest.mark.parametrize(
    "value, expected",
    [(False, False), ("false", False), (0, False), (True, True), (None, True)],
)
def test_connection_flag_round_trips_without_changing_platform_permission(
    value, expected
):
    from gateway.config import PlatformConfig

    config = PlatformConfig.from_dict({
        "enabled": True,
        "extra": {"connection_enabled": value},
    })
    restored = PlatformConfig.from_dict(config.to_dict())
    assert restored.enabled is True and restored.connection_enabled is expected
    assert PlatformConfig(enabled=True).connection_enabled is True


@pytest.mark.asyncio
@pytest.mark.parametrize("platform_name", ["telegram", "discord", "line"])
async def test_standalone_outbound_branch_does_not_start_a_receiver(
    monkeypatch, platform_name
):
    from unittest.mock import AsyncMock

    import gateway.run
    from gateway.config import PlatformConfig
    from gateway.platform_registry import PlatformEntry, platform_registry
    from tools import send_message_tool

    def receiver_forbidden(*args):
        raise AssertionError("Standalone send must not create a receiver")

    sender = AsyncMock(return_value={"success": True})
    entry = PlatformEntry(
        name=platform_name,
        label="Synthetic",
        adapter_factory=receiver_forbidden,
        check_fn=lambda: True,
        standalone_sender_fn=sender,
        max_message_length=4096,
    )
    original_get = platform_registry.get
    monkeypatch.setattr(
        platform_registry,
        "get",
        lambda name: entry if name == platform_name else original_get(name),
    )
    monkeypatch.setattr(gateway.run, "_gateway_runner_ref", lambda: None)
    if platform_name == "telegram":
        monkeypatch.setattr(send_message_tool, "_send_telegram", sender)
    config = PlatformConfig(
        enabled=True,
        token="synthetic-owned-credential",
        extra={"connection_enabled": False},
    )
    result = await send_message_tool._send_to_platform(
        Platform(platform_name), config, "123456", "synthetic local contract"
    )
    assert result["success"]
    sender.assert_awaited_once()


@pytest.mark.parametrize("enabled", [True, False])
def test_cron_keeps_outbound_only_targets_and_standalone_delivery(
    monkeypatch, tmp_path, enabled
):
    from unittest.mock import AsyncMock

    from cron import scheduler
    from gateway.config import GatewayConfig, HomeChannel, PlatformConfig
    from tools import send_message_tool

    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    config = GatewayConfig(
        platforms={
            Platform.TELEGRAM: PlatformConfig(
                enabled=enabled,
                token="synthetic-owned-credential",
                home_channel=HomeChannel(
                    platform=Platform.TELEGRAM, chat_id="123456", name="Synthetic"
                ),
                extra={"connection_enabled": False},
            )
        }
    )
    monkeypatch.setattr("gateway.config.load_gateway_config", lambda: config)
    monkeypatch.setattr(
        scheduler, "load_config", lambda: {"cron": {"wrap_response": False}}
    )
    sender = AsyncMock(return_value={"success": True})
    monkeypatch.setattr(send_message_tool, "_send_to_platform", sender)
    targets = scheduler.cron_delivery_targets()
    assert any(target["id"] == "telegram" for target in targets) is enabled
    result = scheduler._deliver_result_unscoped(
        {"id": "synthetic", "deliver": "telegram:123456"},
        "synthetic local contract",
        adapters={},
    )
    if enabled:
        assert result is None
        sender.assert_awaited_once()
    else:
        assert result
        sender.assert_not_called()


def test_outbound_only_platform_does_not_disarm_relay_idle_mode():
    from gateway.config import GatewayConfig, PlatformConfig
    from gateway.run import GatewayRunner

    runner = GatewayRunner.__new__(GatewayRunner)
    runner.config = GatewayConfig(
        platforms={
            Platform.RELAY: PlatformConfig(enabled=True, token="synthetic-relay"),
            Platform.TELEGRAM: PlatformConfig(
                enabled=True, token="synthetic-bot", extra={"connection_enabled": False}
            ),
        }
    )
    assert runner._scale_to_zero_active_messaging_platforms() == [Platform.RELAY]
    assert Platform.TELEGRAM in runner.config.get_connected_platforms()


def test_send_only_open_policy_cannot_bypass_the_receiving_policy_guard(monkeypatch):
    from gateway.config import GatewayConfig, PlatformConfig
    from gateway.run import _own_policy_open_startup_violation

    monkeypatch.setenv("GATEWAY_ALLOW_ALL_USERS", "false")
    monkeypatch.setenv("WEIXIN_ALLOW_ALL_USERS", "false")
    platform = PlatformConfig(
        enabled=True,
        token="synthetic",
        extra={
            "dm_policy": "open",
            "group_policy": "open",
            "connection_enabled": False,
        },
    )
    config = GatewayConfig(platforms={Platform.WEIXIN: platform})
    assert _own_policy_open_startup_violation(config) is None
    platform.extra["connection_enabled"] = True
    assert _own_policy_open_startup_violation(config)
