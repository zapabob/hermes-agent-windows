"""``hermes vault key``: show where the key lives, and move it only when the move is proven.

Temp HERMES_HOME + an in-memory keychain; the setting changes only after a successful move, so a
refused or failed move leaves both the key and ``vault.key_storage`` where they were.
"""

from __future__ import annotations

import argparse

import pytest

from agent import vault_keychain
from agent.vault_store import VaultStore
from hermes_cli import config as hermes_config
from hermes_cli.vault import register_cli, vault_command

_LOGIN = {"identifier_type": "email", "identifier": "jane@example.com", "password": "dummy-pw-not-real-42"}


class MemoryKeychain:
    name = "MemoryKeychain"

    def __init__(self) -> None:
        self.entries: dict[tuple[str, str], str] = {}

    def get_password(self, service, account):
        return self.entries.get((service, account))

    def set_password(self, service, account, password):
        self.entries[(service, account)] = password

    def delete_password(self, service, account):
        self.entries.pop((service, account), None)


@pytest.fixture
def keychain(monkeypatch) -> MemoryKeychain:
    backend = MemoryKeychain()
    monkeypatch.setattr(vault_keychain, "os_keyring", lambda: backend)
    return backend


def _run(*argv: str) -> None:
    parser = argparse.ArgumentParser()
    register_cli(parser)
    vault_command(parser.parse_args(argv))


def _configured() -> str:
    return (hermes_config.load_config().get("vault") or {}).get("key_storage", "file")


def test_key_command_reports_a_file_key_and_the_setting(keychain, capsys):
    VaultStore().add_item("login", "Example", dict(_LOGIN), origin="https://example.com")
    _run("key")
    out = capsys.readouterr().out
    assert "file" in out and "vault.key_storage = file" in out


def test_migrate_to_keychain_moves_the_key_then_records_the_setting(keychain, capsys):
    store = VaultStore()
    item = store.add_item("login", "Example", dict(_LOGIN), origin="https://example.com").id
    _run("key", "migrate", "--to", "keychain")
    assert "OS keychain" in capsys.readouterr().out
    assert store.key_location()["storage"] == "keychain"
    assert _configured() == "keychain"
    assert len(keychain.entries) == 1
    assert VaultStore().resolve_secret(item)["password"] == _LOGIN["password"]

    _run("key", "migrate", "--to", "file")
    assert store.key_location()["storage"] == "file" and keychain.entries == {}
    assert _configured() == "file"
    assert VaultStore().resolve_secret(item)["password"] == _LOGIN["password"]


def test_a_refused_migration_exits_nonzero_and_changes_neither_key_nor_setting(monkeypatch, capsys):
    def refuse():
        raise vault_keychain.KeychainUnavailable("no OS keychain is reachable from this session")

    monkeypatch.setattr(vault_keychain, "os_keyring", refuse)
    store = VaultStore()
    item = store.add_item("login", "Example", dict(_LOGIN), origin="https://example.com").id
    with pytest.raises(SystemExit) as excinfo:
        _run("key", "migrate", "--to", "keychain")
    assert excinfo.value.code == 1
    assert "keychain" in capsys.readouterr().out
    assert store.key_location()["storage"] == "file"
    assert _configured() == "file", "the setting must not claim a storage the key is not in"
    assert VaultStore().resolve_secret(item)["password"] == _LOGIN["password"]


def test_migrate_before_any_vault_exists_only_records_the_setting(keychain, capsys):
    _run("key", "migrate", "--to", "keychain")
    assert "No vault key exists yet" in capsys.readouterr().out
    assert _configured() == "keychain"
    assert keychain.entries == {}
