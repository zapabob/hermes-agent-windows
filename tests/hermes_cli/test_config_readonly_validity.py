"""Strict current-config behavior; only owned temporary files are used."""
import builtins
from pathlib import Path

import pytest

from hermes_cli import config, managed_scope


@pytest.fixture
def owned_config(tmp_path, monkeypatch):
    home = tmp_path / "owned-home"
    home.mkdir()
    managed = tmp_path / "owned-managed"
    managed.mkdir()
    monkeypatch.setenv("HERMES_HOME", str(home))
    monkeypatch.setenv("HERMES_MANAGED_DIR", str(managed))
    monkeypatch.setattr(config, "_LOAD_CONFIG_CACHE", {})
    monkeypatch.setattr(config, "_LAST_EXPANDED_CONFIG_BY_PATH", {})
    monkeypatch.setattr(managed_scope, "_CONFIG_CACHE", {})
    return home / "config.yaml", managed / "config.yaml"


@pytest.mark.parametrize("layer", [0, 1], ids=["user", "managed"])
@pytest.mark.parametrize("bad", ["[]", "[one]", "false", "42", "secret: [owned-secret"],
                         ids=["empty-list", "list", "bool", "number", "syntax"])
def test_invalid_current_file_never_uses_warmed_values(owned_config, layer, bad):
    for file in owned_config:
        file.write_text("mcp_servers:\n  owned:\n    enabled: true\n", encoding="utf-8")
    assert config.load_config_readonly()["mcp_servers"]["owned"]["enabled"] is True
    owned_config[layer].write_text(bad, encoding="utf-8")
    before = set(owned_config[layer].parent.iterdir())
    with pytest.raises(config.ConfigReadError) as error:
        config.load_config_readonly(require_valid=True)
    assert "owned-secret" not in str(error.value)
    assert set(owned_config[layer].parent.iterdir()) == before


@pytest.mark.parametrize("layer", [0, 1], ids=["user", "managed"])
def test_unchanged_signature_does_not_hide_unreadable_file(owned_config, monkeypatch, layer):
    for file in owned_config:
        file.write_text("mcp_servers: {}\n", encoding="utf-8")
    config.load_config_readonly()
    stat_before = owned_config[layer].stat()
    original = builtins.open

    def denied_open(file, *args, **kwargs):
        if Path(file) == owned_config[layer]:
            raise PermissionError("owned-secret must not reach result")
        return original(file, *args, **kwargs)

    monkeypatch.setattr(builtins, "open", denied_open)
    with pytest.raises(config.ConfigReadError) as error:
        config.load_config_readonly(require_valid=True)
    assert error.value.category == "unreadable"
    assert "owned-secret" not in str(error.value)
    assert owned_config[layer].stat().st_mtime_ns == stat_before.st_mtime_ns


def test_strict_uses_canonical_normalization_env_and_managed_leaf_precedence(owned_config, monkeypatch):
    user, managed = owned_config
    monkeypatch.setenv("M02_OWNED_MODEL", "owned-model")
    user.write_text("model: ${M02_OWNED_MODEL}\nmcp_servers:\n  owned:\n    command: owned-command\n    enabled: true\n", encoding="utf-8")
    managed.write_text("model:\n  default:\n    provider: custom\n    model: managed-model\nmcp_servers:\n  owned:\n    enabled: false\n", encoding="utf-8")
    normal = config.load_config_readonly()
    strict = config.load_config_readonly(require_valid=True)
    assert strict == normal
    assert strict["model"]["default"] == "managed-model"
    assert strict["model"]["provider"] == "custom"
    assert strict["mcp_servers"]["owned"] == {"command": "owned-command", "enabled": False}
    managed.unlink()
    assert config.load_config_readonly(require_valid=True)["model"] == "owned-model"


@pytest.mark.parametrize("content", [None, "", "null", "{}"])
def test_missing_or_empty_files_are_valid_and_strict_read_creates_nothing(owned_config, content):
    if content is not None:
        owned_config[0].write_text(content, encoding="utf-8")
    before = set(owned_config[0].parent.iterdir())
    result = config.load_config_readonly(require_valid=True)
    assert isinstance(result, dict) and "model" in result
    assert set(owned_config[0].parent.iterdir()) == before


def test_missing_named_home_is_typed_refusal_without_recreation(tmp_path, monkeypatch):
    home = tmp_path / "profiles" / "deleted-owned-profile"
    monkeypatch.setenv("HERMES_HOME", str(home))
    with pytest.raises(config.ConfigReadError) as error:
        config.load_config_readonly(require_valid=True)
    assert error.value.category == "missing_profile"
    assert not home.exists()


def test_normal_reader_retains_lkg_while_strict_refuses(owned_config):
    file = owned_config[0]
    file.write_text("mcp_servers:\n  owned:\n    enabled: false\n", encoding="utf-8")
    assert config.load_config()["mcp_servers"]["owned"]["enabled"] is False
    file.write_text("mcp_servers: [", encoding="utf-8")
    assert config.load_config()["mcp_servers"]["owned"]["enabled"] is False
    with pytest.raises(config.ConfigReadError):
        config.load_config_readonly(require_valid=True)


@pytest.mark.parametrize("layer,bad", [(0, "agent: owned-invalid-scalar"),
                                       (0, "owned_loop: &cycle {again: *cycle}"),
                                       (1, "owned_loop: &cycle {again: *cycle}")])
def test_nested_normalization_or_expansion_failure_is_typed(owned_config, layer, bad):
    owned_config[layer].write_text(bad, encoding="utf-8")
    with pytest.raises(config.ConfigReadError) as error:
        config.load_config_readonly(require_valid=True)
    assert error.value.category == "invalid_value"
    assert error.value.path == owned_config[layer]
    assert "owned-invalid-scalar" not in str(error.value)
