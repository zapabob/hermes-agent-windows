"""Explicit channel ownership keeps credentials usable without duplicate listeners."""
import os

import pytest
import yaml

from gateway.config import Platform, load_gateway_config


@pytest.mark.parametrize("profile", ["default", "delivery-worker", "job-seeker", "secretary"])
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
        "platforms": {"buzz": {"enabled": False}},
        "telegram": {"enabled": own_bots},
        "discord": {"enabled": own_bots},
    }
    if profile != "default":
        monkeypatch.setenv("LINE_CHANNEL_ACCESS_TOKEN", "synthetic-shared-line")
        monkeypatch.setenv("LINE_CHANNEL_SECRET", "synthetic-shared-line-secret")
        config["platforms"]["line"] = {"enabled": profile == "delivery-worker"}
    (tmp_path / "config.yaml").write_text(yaml.safe_dump(config), encoding="utf-8")

    loaded = load_gateway_config()

    assert loaded.platforms[Platform.TELEGRAM].enabled is own_bots
    assert loaded.platforms[Platform.DISCORD].enabled is own_bots
    assert loaded.platforms[Platform.TELEGRAM].token == "synthetic-shared-telegram"
    assert loaded.platforms[Platform.DISCORD].token == "synthetic-shared-discord"
    assert loaded.platforms[Platform("buzz")].enabled is False
    if profile != "default":
        assert loaded.platforms[Platform("line")].enabled is (profile == "delivery-worker")
