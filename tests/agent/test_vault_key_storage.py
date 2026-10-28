"""Where the local vault key lives: ``vault.key`` (default) or the OS keychain (opt-in).

Contracts (temp HERMES_HOME + an in-memory keychain injected at ``vault_keychain.os_keyring``;
nothing touches a real credential store, and the optional ``keyring`` package is not required):

- ``vault.key_storage`` defaults to ``file``; a missing ``keyring`` never breaks a file vault;
- keychain mode stores a NEW vault's key in the keychain, one entry per vault, and the disk keeps only
  a non-secret pointer;
- ``migrate_key`` runs write -> readback -> decrypt existing ciphertext -> pointer commit -> delete old
  key, in that order, and every failure before the last step leaves the original storage working;
- ciphertext present but key missing: the error explains recovery and NO new key is ever minted;
- an explicit keychain request that cannot be honoured fails visibly (no silent file downgrade).
"""

from __future__ import annotations

import json
import shutil
import sys
from pathlib import Path

import pytest
from cryptography.fernet import Fernet

import utils
from agent import vault_keychain, vault_store
from agent.vault_store import VaultError, VaultStore
from hermes_cli.config_defaults import DEFAULT_CONFIG
from utils import atomic_write_bytes

_LOGIN = {"identifier_type": "email", "identifier": "jane@example.com", "password": "dummy-pw-not-real-42"}


class MemoryKeychain:
    """Stand-in for a keyring backend: a dict keyed by (service, account)."""

    name = "MemoryKeychain"

    def __init__(self) -> None:
        self.entries: dict[tuple[str, str], str] = {}

    def get_password(self, service, account):
        return self.entries.get((service, account))

    def set_password(self, service, account, password):
        self.entries[(service, account)] = password

    def delete_password(self, service, account):
        if self.entries.pop((service, account), None) is None:
            raise KeyError("no such entry")


class ForgetfulKeychain(MemoryKeychain):
    """Accepts the write but hands back something else (a broken or mis-scoped store)."""

    def get_password(self, service, account):
        return Fernet.generate_key().decode("ascii")


class RefusingKeychain(MemoryKeychain):
    def set_password(self, service, account, password):
        raise OSError("credential store locked")


class WrongKeyAfterStoreKeychain(MemoryKeychain):
    """Echoes the key once (so ``store_key``'s readback passes), then serves a different, valid key."""

    def __init__(self) -> None:
        super().__init__()
        self._reads = 0

    def get_password(self, service, account):
        self._reads += 1
        if self._reads == 1:
            return super().get_password(service, account)
        return Fernet.generate_key().decode("ascii")


@pytest.fixture
def home(tmp_path, monkeypatch):
    def make(name: str = "default", key_storage: str | None = None) -> Path:
        path = tmp_path / name
        path.mkdir()
        if key_storage:
            (path / "config.yaml").write_text(f"vault:\n  key_storage: {key_storage}\n", encoding="utf-8")
        monkeypatch.setenv("HERMES_HOME", str(path))
        return path

    return make


def _use(monkeypatch, backend) -> MemoryKeychain:
    monkeypatch.setattr(vault_keychain, "os_keyring", lambda: backend)
    return backend


@pytest.fixture
def keychain(monkeypatch) -> MemoryKeychain:
    return _use(monkeypatch, MemoryKeychain())


def _unreachable(monkeypatch) -> None:
    def refuse():
        raise vault_keychain.KeychainUnavailable("no OS keychain is reachable from this session")

    monkeypatch.setattr(vault_keychain, "os_keyring", refuse)


def _add(store: VaultStore) -> str:
    return store.add_item("login", "Example", dict(_LOGIN), origin="https://example.com").id


def _password(store: VaultStore, item: str) -> str:
    return store.resolve_secret(item)["password"]


# -- defaults and optional dependency -----------------------------------------------------------------


def test_key_storage_defaults_to_file_and_a_new_vault_keeps_the_key_file(home):
    h = home()
    assert DEFAULT_CONFIG["vault"]["key_storage"] == "file"
    assert vault_store.configured_key_storage() == "file"
    item = _add(VaultStore())
    assert (h / "vault" / "vault.key").exists()
    assert not (h / "vault" / "vault.keyref").exists()
    assert _password(VaultStore(), item) == _LOGIN["password"]


def test_unknown_key_storage_value_is_treated_as_file(home):
    home(key_storage="keychian")
    assert vault_store.configured_key_storage() == "file"


def test_missing_keyring_package_never_breaks_a_file_vault(home, monkeypatch):
    h = home()
    monkeypatch.setitem(sys.modules, "keyring", None)  # `import keyring` raises ImportError
    item = _add(VaultStore())
    assert _password(VaultStore(), item) == _LOGIN["password"]
    assert VaultStore().list_items()[0].id == item
    with pytest.raises(vault_keychain.KeychainUnavailable, match="keyring"):
        vault_keychain.os_keyring()
    assert (h / "vault" / "vault.key").exists()


def test_reading_an_empty_vault_never_creates_a_directory_or_touches_the_keychain(home, keychain):
    h = home(key_storage="keychain")
    store = VaultStore()
    assert store.list_items() == [] and store.has_items() is False
    assert not (h / "vault").exists()
    assert keychain.entries == {}


@pytest.mark.parametrize("module", ["keyring.backends.fail", "keyring.backends.null", "keyrings.alt.file"])
def test_plaintext_or_null_keyring_backends_are_not_an_os_keychain(module):
    backend = type("Backend", (), {"__module__": module})()
    assert vault_keychain._is_os_keychain(backend) is False
    assert vault_keychain._is_os_keychain(type("WinVault", (), {"__module__": "keyring.backends.Windows"})())
    chained = type("Chain", (), {"__module__": "keyring.backends.chainer", "backends": [backend]})()
    assert vault_keychain._is_os_keychain(chained) is False


# -- keychain mode -----------------------------------------------------------------------------------


def test_keychain_mode_puts_a_new_vault_key_in_the_keychain_per_vault(home, keychain):
    a = home("a", key_storage="keychain")
    item_a = _add(VaultStore())
    assert not (a / "vault" / "vault.key").exists()
    assert len(keychain.entries) == 1
    (key,) = keychain.entries.values()
    assert key.encode() not in (a / "vault" / "vault.keyref").read_bytes(), "the pointer holds no key material"
    assert _password(VaultStore(), item_a) == _LOGIN["password"]

    b = home("b", key_storage="keychain")
    item_b = _add(VaultStore())
    assert not (b / "vault" / "vault.key").exists()
    assert len(keychain.entries) == 2, "each vault gets its own keychain entry"
    assert _password(VaultStore(), item_b) == _LOGIN["password"]
    assert _password(VaultStore(a / "vault"), item_a) == _LOGIN["password"]


def test_keychain_mode_without_a_reachable_keychain_refuses_and_mints_nothing(home, monkeypatch):
    h = home(key_storage="keychain")
    _unreachable(monkeypatch)
    with pytest.raises(VaultError, match="keychain"):
        _add(VaultStore())
    vault = h / "vault"
    assert not (vault / "vault.key").exists(), "an explicit keychain request must not fall back to a file"
    assert not (vault / "vault.keyref").exists()
    assert not (vault / "vault.json.enc").exists()


def test_keychain_mode_refusing_a_write_refuses_and_mints_nothing(home, monkeypatch):
    h = home(key_storage="keychain")
    backend = _use(monkeypatch, RefusingKeychain())
    with pytest.raises(VaultError, match="keychain"):
        _add(VaultStore())
    assert not (h / "vault" / "vault.key").exists() and not (h / "vault" / "vault.keyref").exists()
    assert backend.entries == {}


def test_keychain_mode_whose_pointer_cannot_be_saved_leaves_no_entry_or_key(home, keychain, monkeypatch):
    h = home(key_storage="keychain")

    def failing_write_ref(path, ref):
        raise OSError(28, "No space left on device")

    monkeypatch.setattr(vault_keychain, "write_ref", failing_write_ref)
    with pytest.raises(VaultError, match="vault.keyref"):
        _add(VaultStore())
    assert keychain.entries == {}
    assert not (h / "vault" / "vault.key").exists()


def test_an_existing_file_vault_keeps_opening_whatever_the_setting_says(home, keychain):
    h = home()
    item = _add(VaultStore())
    (h / "config.yaml").write_text("vault:\n  key_storage: keychain\n", encoding="utf-8")
    assert _password(VaultStore(), item) == _LOGIN["password"]
    _add(VaultStore())
    assert keychain.entries == {}, "the setting only decides where a NEW vault's key goes"
    assert (h / "vault" / "vault.key").exists()


# -- migration: happy path and ordering ---------------------------------------------------------------


def test_migration_moves_the_key_to_the_keychain_and_back_without_touching_the_ciphertext(home, keychain):
    h = home()
    store = VaultStore()
    item = _add(store)
    key_file = h / "vault" / "vault.key"
    old_key = key_file.read_bytes().strip()
    blob = (h / "vault" / "vault.json.enc").read_bytes()

    assert store.migrate_key("keychain") == "keychain"
    assert not key_file.exists()
    assert list(keychain.entries.values()) == [old_key.decode()]
    assert (h / "vault" / "vault.json.enc").read_bytes() == blob
    assert _password(VaultStore(), item) == _LOGIN["password"]
    assert store.key_location()["storage"] == "keychain"

    assert store.migrate_key("file") == "file"
    assert key_file.read_bytes().strip() == old_key
    assert keychain.entries == {}
    assert not (h / "vault" / "vault.keyref").exists()
    assert _password(VaultStore(), item) == _LOGIN["password"]


def test_migration_to_keychain_follows_write_readback_decrypt_pointer_delete_order(home, keychain, monkeypatch):
    h = home()
    store = VaultStore()
    item = _add(store)
    events: list[str] = []

    def spy(name):
        real = getattr(vault_keychain, name)

        def wrapper(*args, **kwargs):
            events.append(name)
            return real(*args, **kwargs)

        monkeypatch.setattr(vault_keychain, name, wrapper)

    for name in ("store_key", "load_key", "save_new_ref", "remove_file"):
        spy(name)
    real_decrypts = VaultStore._decrypts

    def decrypts(self, key):
        events.append("decrypts")
        return real_decrypts(self, key)

    monkeypatch.setattr(VaultStore, "_decrypts", decrypts)
    store.migrate_key("keychain")

    assert events.index("store_key") < events.index("load_key") < events.index("save_new_ref") < events.index("remove_file")
    assert events.index("decrypts", events.index("load_key")) < events.index("save_new_ref"), \
        "the stored copy must be proven against the ciphertext before the pointer is committed"
    assert events[-1] == "remove_file", "the old key is deleted last"
    assert _password(VaultStore(), item) == _LOGIN["password"]
    assert not (h / "vault" / "vault.key").exists()


# -- migration: failure at each stage keeps the original storage ---------------------------------------


@pytest.mark.parametrize("backend_cls", [RefusingKeychain, ForgetfulKeychain, WrongKeyAfterStoreKeychain],
                         ids=["write-refused", "readback-mismatch", "decrypt-mismatch"])
def test_a_failed_move_to_the_keychain_keeps_the_key_file_and_explains(home, monkeypatch, backend_cls):
    h = home()
    store = VaultStore()
    item = _add(store)
    key = (h / "vault" / "vault.key").read_bytes()
    backend = _use(monkeypatch, backend_cls())

    with pytest.raises(VaultError, match="keychain") as excinfo:
        store.migrate_key("keychain")
    assert "vault.key" in str(excinfo.value), "the error says where the key stays"
    assert (h / "vault" / "vault.key").read_bytes() == key
    assert not (h / "vault" / "vault.keyref").exists()
    assert backend.entries == {}, "no half-made entry may be left behind"
    assert _password(VaultStore(), item) == _LOGIN["password"]


@pytest.mark.parametrize("backend_cls", [ForgetfulKeychain, RefusingKeychain], ids=["readback-mismatch", "write-refused"])
def test_store_key_proves_the_keychain_can_return_what_it_was_given(monkeypatch, backend_cls):
    _use(monkeypatch, backend_cls())
    ref = vault_keychain.new_ref(Path("unused-vault-dir"))
    with pytest.raises(vault_keychain.KeychainUnavailable):
        vault_keychain.store_key(ref, Fernet.generate_key())


def test_store_key_load_key_delete_key_round_trip(keychain):
    ref = vault_keychain.new_ref(Path("unused-vault-dir"))
    key = Fernet.generate_key()
    vault_keychain.store_key(ref, key)
    assert vault_keychain.load_key(ref) == key
    assert vault_keychain.delete_key(ref) is True
    assert vault_keychain.load_key(ref) is None
    assert vault_keychain.delete_key(ref) is True, "deleting an already-gone entry still reports success"


def test_migration_whose_pointer_cannot_be_saved_leaves_no_untracked_entry(home, keychain, monkeypatch):
    h = home()
    item = _add(VaultStore())

    def failing_write_ref(path, ref):
        raise OSError(28, "No space left on device")

    monkeypatch.setattr(vault_keychain, "write_ref", failing_write_ref)
    with pytest.raises(VaultError, match="vault.keyref"):
        VaultStore().migrate_key("keychain")
    assert keychain.entries == {}, "a retry would mint another random account, so nothing may be left"
    assert (h / "vault" / "vault.key").exists()
    assert _password(VaultStore(), item) == _LOGIN["password"]


def test_failing_to_delete_the_old_key_file_is_reported_and_a_rerun_finishes_cleanly(home, keychain, monkeypatch):
    h = home()
    item = _add(VaultStore())
    key_file = h / "vault" / "vault.key"
    real_remove = vault_keychain.remove_file

    def locked_remove(path):
        if Path(path) == key_file:
            raise PermissionError(13, "file is in use")
        real_remove(path)

    monkeypatch.setattr(vault_keychain, "remove_file", locked_remove)
    with pytest.raises(VaultError, match="could not be removed"):
        VaultStore().migrate_key("keychain")
    assert key_file.exists() and (h / "vault" / "vault.keyref").exists()
    assert _password(VaultStore(), item) == _LOGIN["password"], "the vault keeps working from the file"
    assert len(keychain.entries) == 1

    monkeypatch.setattr(vault_keychain, "remove_file", real_remove)
    assert VaultStore().migrate_key("keychain") == "keychain"
    assert not key_file.exists()
    assert len(keychain.entries) == 1, "the rerun resumes into its own entry instead of minting another"
    assert _password(VaultStore(), item) == _LOGIN["password"]


def test_migration_to_the_keychain_without_a_reachable_keychain_keeps_the_file(home, monkeypatch):
    h = home()
    item = _add(VaultStore())
    _unreachable(monkeypatch)
    with pytest.raises(VaultError, match="keychain"):
        VaultStore().migrate_key("keychain")
    assert (h / "vault" / "vault.key").exists()
    assert not (h / "vault" / "vault.keyref").exists()
    assert _password(VaultStore(), item) == _LOGIN["password"]


def test_a_move_back_to_file_that_cannot_secure_the_file_keeps_the_keychain_copy(home, keychain, monkeypatch):
    h = home(key_storage="keychain")
    item = _add(VaultStore())
    entries = dict(keychain.entries)
    real_acl = vault_store._restrict_windows_acl

    def refuse_acl(path, *, directory=False):
        if Path(path).name == "vault.key":
            raise VaultError("could not secure vault permissions on Windows")
        real_acl(path, directory=directory)

    monkeypatch.setattr(vault_store, "_restrict_windows_acl", refuse_acl)
    with pytest.raises(VaultError, match="secure"):
        VaultStore().migrate_key("file")
    assert not (h / "vault" / "vault.key").exists(), "a key file whose protection failed is not left behind"
    assert (h / "vault" / "vault.keyref").exists()
    assert keychain.entries == entries
    monkeypatch.setattr(vault_store, "_restrict_windows_acl", real_acl)
    assert _password(VaultStore(), item) == _LOGIN["password"]


def test_a_move_back_to_file_whose_keychain_entry_cannot_be_deleted_keeps_the_pointer_for_a_rerun(home, keychain, monkeypatch):
    h = home(key_storage="keychain")
    item = _add(VaultStore())
    real_delete = keychain.delete_password
    monkeypatch.setattr(keychain, "delete_password", lambda *a: (_ for _ in ()).throw(OSError("locked")))

    assert VaultStore().migrate_key("file") == "file"
    where = VaultStore().key_location()
    assert where["storage"] == "file" and where["keychain_entry_left"]
    assert (h / "vault" / "vault.keyref").exists()
    assert _password(VaultStore(), item) == _LOGIN["password"]

    monkeypatch.setattr(keychain, "delete_password", real_delete)
    assert VaultStore().migrate_key("file") == "file"
    assert "keychain_entry_left" not in VaultStore().key_location()
    assert keychain.entries == {} and not (h / "vault" / "vault.keyref").exists()


def test_cleanup_of_an_already_deleted_keychain_entry_completes(home, keychain):
    h = home(key_storage="keychain")
    item = _add(VaultStore())
    keyref = (h / "vault" / "vault.keyref").read_bytes()
    assert VaultStore().migrate_key("file") == "file"
    (h / "vault" / "vault.keyref").write_bytes(keyref)  # stopped after deleting the entry, before the pointer
    assert VaultStore().migrate_key("file") == "file"
    assert "keychain_entry_left" not in VaultStore().key_location()
    assert not (h / "vault" / "vault.keyref").exists()
    assert _password(VaultStore(), item) == _LOGIN["password"]


# -- missing key: never mint ------------------------------------------------------------------------


@pytest.mark.parametrize("lose", ["keychain entry", "key file"])
def test_missing_key_with_an_existing_vault_explains_recovery_and_mints_nothing(home, keychain, lose):
    h = home(key_storage="keychain" if lose == "keychain entry" else None)
    _add(VaultStore())
    blob = (h / "vault" / "vault.json.enc").read_bytes()
    if lose == "keychain entry":
        keychain.entries.clear()
    else:
        (h / "vault" / "vault.key").unlink()

    with pytest.raises(VaultError) as excinfo:
        VaultStore().list_items()
    message = str(excinfo.value)
    assert "hermes vault key" in message and "vault.json.enc" in message
    with pytest.raises(VaultError):
        _add(VaultStore())  # a write must not mint a key either
    assert (h / "vault" / "vault.json.enc").read_bytes() == blob, "the ciphertext must be left alone"
    assert not (h / "vault" / "vault.key").exists(), "no fresh key may be minted over an existing vault"
    assert len(keychain.entries) == 0
    if lose == "keychain entry":  # and a rerun of the move must not report the lost entry as fine
        with pytest.raises(VaultError, match="hermes vault key"):
            VaultStore().migrate_key("keychain")


def test_an_unreachable_keychain_never_costs_the_ciphertext_or_mints_a_key(home, keychain, monkeypatch):
    h = home(key_storage="keychain")
    _add(VaultStore())
    blob = (h / "vault" / "vault.json.enc").read_bytes()
    _unreachable(monkeypatch)
    with pytest.raises(VaultError, match="not reachable"):
        VaultStore().list_items()
    assert (h / "vault" / "vault.json.enc").read_bytes() == blob
    assert not (h / "vault" / "vault.key").exists()


def test_a_stray_key_file_that_cannot_open_the_vault_never_costs_the_keychain_copy(home, keychain):
    h = home(key_storage="keychain")
    item = _add(VaultStore())
    (h / "vault" / "vault.key").write_bytes(Fernet.generate_key())  # e.g. restored from an old backup
    good = dict(keychain.entries)
    for target in ("file", "keychain"):
        with pytest.raises(VaultError, match="does not decrypt"):
            VaultStore().migrate_key(target)
    assert keychain.entries == good
    (h / "vault" / "vault.key").unlink()
    assert _password(VaultStore(), item) == _LOGIN["password"]


def test_migrate_key_rejects_an_unknown_target(home):
    home()
    with pytest.raises(VaultError, match="'file' or 'keychain'"):
        VaultStore().migrate_key("cloud")


# -- ownership: clone, rename, reused names -----------------------------------------------------------


def test_cloned_and_renamed_keychain_vaults_never_share_or_overwrite_an_entry(home, keychain):
    """A profile clone copies vault.keyref; a rename moves it. Neither copy may later overwrite or delete
    the entry another copy still depends on, and a new vault at a reused name gets its own entry."""
    work = home("work", key_storage="keychain")
    item = _add(VaultStore())
    a, b = home("clone-a", key_storage="keychain"), home("clone-b", key_storage="keychain")
    for clone in (a, b):
        shutil.copytree(work / "vault", clone / "vault")
    assert VaultStore(a / "vault").migrate_key("file") == "file"
    assert VaultStore(b / "vault").migrate_key("keychain") == "keychain"
    assert VaultStore(work / "vault").migrate_key("file") == "file"  # deletes only the original's own entry
    for vault in (a, b, work):
        assert _password(VaultStore(vault / "vault"), item) == _LOGIN["password"]

    assert VaultStore(work / "vault").migrate_key("keychain") == "keychain"
    renamed = home("renamed", key_storage="keychain")
    (work / "vault").rename(renamed / "vault")
    _add(VaultStore(work / "vault"))  # a new vault where the renamed one used to live
    assert _password(VaultStore(renamed / "vault"), item) == _LOGIN["password"]


def test_a_pointer_naming_a_foreign_directory_is_not_owned(home, keychain):
    h = home(key_storage="keychain")
    _add(VaultStore())
    ref = vault_keychain.read_ref(h / "vault" / "vault.keyref")
    assert vault_keychain.owns(ref, h / "vault")
    assert not vault_keychain.owns({**ref, "vault_dir": str(h / "elsewhere")}, h / "vault")
    assert not vault_keychain.owns({k: v for k, v in ref.items() if k != "vault_dir"}, h / "vault")


@pytest.mark.windows_only
def test_ownership_comparison_ignores_drive_letter_and_path_case_on_windows(home, keychain):
    h = home(key_storage="keychain")
    _add(VaultStore())
    ref = vault_keychain.read_ref(h / "vault" / "vault.keyref")
    assert vault_keychain.owns({**ref, "vault_dir": ref["vault_dir"].swapcase()}, h / "vault")


@pytest.mark.parametrize("pointer_landed", [False, True])
def test_copied_vault_keeps_opening_when_saving_its_own_pointer_fails(home, keychain, monkeypatch, pointer_landed):
    work = home("work", key_storage="keychain")
    item = _add(VaultStore())
    clone = home("clone", key_storage="keychain")
    shutil.copytree(work / "vault", clone / "vault")
    real_write_ref = vault_keychain.write_ref

    def failing_write_ref(path, ref):
        if pointer_landed:  # the replace happened, a later step (temp cleanup) failed
            real_write_ref(path, ref)
        raise OSError(28, "No space left on device")

    monkeypatch.setattr(vault_keychain, "write_ref", failing_write_ref)
    assert _password(VaultStore(), item) == _LOGIN["password"]
    # no half-made entry left behind; an entry the saved pointer names is never deleted
    assert len(keychain.entries) == (2 if pointer_landed else 1)
    monkeypatch.setattr(vault_keychain, "write_ref", real_write_ref)
    assert _password(VaultStore(), item) == _LOGIN["password"], "and on every later open"


def _profile_env(tmp_path, monkeypatch) -> Path:
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("USERPROFILE", str(tmp_path))
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    source = tmp_path / ".hermes"
    source.mkdir()
    (source / "config.yaml").write_text("vault:\n  key_storage: keychain\n", encoding="utf-8")
    monkeypatch.setenv("HERMES_HOME", str(source))
    return source


def test_clone_all_owns_its_key_before_the_source_ever_migrates(tmp_path, monkeypatch, keychain):
    """A --clone-all copy gets its own keychain entry when it is created, so the source moving its key
    to a file (which deletes the source's entry) cannot strand a clone that was never opened."""
    from hermes_cli.profiles import create_profile

    source = _profile_env(tmp_path, monkeypatch)
    item = _add(VaultStore())
    clone = create_profile("vault-clone", clone_from="default", clone_all=True, no_alias=True)

    assert VaultStore().migrate_key("file") == "file"  # the clone has not opened its vault yet
    assert _password(VaultStore(source / "vault"), item) == _LOGIN["password"]
    assert _password(VaultStore(clone / "vault"), item) == _LOGIN["password"]
    assert not (clone / "vault" / "vault.key").exists(), "the clone keeps keychain storage"
    assert len(keychain.entries) == 1, "only the clone's own entry is left"


def test_clone_all_without_a_reachable_keychain_is_refused_not_published_sharing_the_key(tmp_path, monkeypatch, keychain):
    from hermes_cli.profiles import create_profile, get_profile_dir

    _profile_env(tmp_path, monkeypatch)
    _add(VaultStore())
    _unreachable(monkeypatch)  # e.g. an SSH session that cannot reach the login keychain
    with pytest.raises(ValueError, match="keychain"):
        create_profile("vault-clone", clone_from="default", clone_all=True, no_alias=True)
    assert not get_profile_dir("vault-clone").exists()
    assert len(keychain.entries) == 1, "the source's entry is untouched"


def test_clone_all_of_a_file_vault_needs_no_keychain(tmp_path, monkeypatch):
    from hermes_cli.profiles import create_profile

    source = _profile_env(tmp_path, monkeypatch)
    (source / "config.yaml").write_text("vault:\n  key_storage: file\n", encoding="utf-8")
    item = _add(VaultStore())
    _unreachable(monkeypatch)
    clone = create_profile("vault-clone", clone_from="default", clone_all=True, no_alias=True)
    assert _password(VaultStore(clone / "vault"), item) == _LOGIN["password"]


# -- atomic key-file writes ------------------------------------------------------------------------


def test_atomic_write_bytes_replaces_whole_and_leaves_no_temp_files(tmp_path):
    folder = tmp_path / "keys"
    target = folder / "vault.key"
    atomic_write_bytes(target, b"first", mode=0o600, fsync_dir=True)
    atomic_write_bytes(target, b"second", mode=0o600, fsync_dir=True)
    assert target.read_bytes() == b"second"
    assert [p.name for p in folder.iterdir()] == ["vault.key"]


def test_atomic_write_bytes_failure_keeps_the_old_content(tmp_path, monkeypatch):
    folder = tmp_path / "keys"
    target = folder / "vault.key"
    atomic_write_bytes(target, b"old")

    def broken_replace(tmp, dest):
        raise OSError("disk full")

    monkeypatch.setattr(utils, "atomic_replace", broken_replace)
    with pytest.raises(OSError):
        atomic_write_bytes(target, b"new")
    assert target.read_bytes() == b"old"
    assert [p.name for p in folder.iterdir()] == ["vault.key"]


def test_the_keyref_is_valid_json_pointing_at_a_keychain_entry(home, keychain):
    h = home(key_storage="keychain")
    _add(VaultStore())
    data = json.loads((h / "vault" / "vault.keyref").read_text(encoding="utf-8"))
    assert data["storage"] == "keychain" and data["service"] == vault_keychain.SERVICE
    assert (data["service"], data["account"]) in keychain.entries
    (h / "vault" / "vault.keyref").write_text("{not json", encoding="utf-8")
    with pytest.raises(VaultError, match="unreadable"):
        VaultStore().key_location()
