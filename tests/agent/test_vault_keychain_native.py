"""The vault key against the host's REAL Windows Credential Manager.

Everything in ``test_vault_key_storage.py`` uses an in-memory keychain, which proves Hermes' plumbing
but not that the platform store accepts, returns and deletes an entry the way
``agent.vault_keychain`` expects. These run only on native Windows (``windows_only``), need the
optional ``keyring`` package (skipped, not failed, when it is absent), use a temporary HERMES_HOME and
uniquely named dummy entries, and delete exactly the entries they made in teardown. No key or
credential is printed or asserted into a message.
"""

from __future__ import annotations

import importlib
import os
import subprocess
import sys
import uuid
from pathlib import Path

import pytest
from cryptography.fernet import Fernet

from agent import vault_keychain as kc
from agent.vault_store import VaultStore

pytestmark = pytest.mark.windows_only

_LOGIN = {"identifier_type": "email", "identifier": "ci@example.com", "password": "dummy-pw-not-real-42"}
_REPO_ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture
def os_keychain():
    """The real backend keyring resolves to; skip where the host has none (not a failure)."""
    pytest.importorskip("keyring")
    try:
        backend = kc.os_keyring()
    except kc.KeychainUnavailable as exc:
        pytest.skip(f"no OS keychain on this host: {exc}")
    made: list[dict] = []
    yield made
    for ref in made:
        kc.delete_key(ref)
    del backend


@pytest.fixture
def hermes_home(tmp_path, monkeypatch) -> Path:
    home = tmp_path / "hermes-home"
    home.mkdir()
    (home / "config.yaml").write_text("vault:\n  key_storage: keychain\n", encoding="utf-8")
    monkeypatch.setenv("HERMES_HOME", str(home))
    return home


def _in_new_process(home: Path, code: str) -> subprocess.CompletedProcess:
    """Run *code* in a fresh interpreter (a process restart) against the same temporary HERMES_HOME."""
    env = {**os.environ, "HERMES_HOME": str(home), "PYTHONPATH": os.pathsep.join(p for p in sys.path if p)}
    return subprocess.run([sys.executable, "-c", code], env=env, cwd=_REPO_ROOT, capture_output=True,
                          text=True, timeout=120, check=False)


_READ_BACK = (
    "import sys\n"
    "from agent.vault_store import VaultStore\n"
    "s = VaultStore()\n"
    "item = s.list_items()[0].id\n"
    "sys.stdout.write('ok' if s.resolve_secret(item)['password'] == 'dummy-pw-not-real-42' else 'mismatch')\n"
)


def _acl_principals(path: Path) -> tuple[set[str], bool]:
    win32security = importlib.import_module("win32security")
    descriptor = win32security.GetFileSecurity(str(path), win32security.DACL_SECURITY_INFORMATION)
    acl = descriptor.GetSecurityDescriptorDacl()
    sids = {win32security.ConvertSidToStringSid(acl.GetAce(i)[2]) for i in range(acl.GetAceCount())}
    control = descriptor.GetSecurityDescriptorControl()[0]
    return sids, bool(control & win32security.SE_DACL_PROTECTED)


def test_credential_manager_stores_reads_and_deletes_a_dummy_entry(os_keychain):
    ref = {"storage": "keychain", "service": kc.SERVICE, "account": f"hermes-ci-smoke-{uuid.uuid4().hex}"}
    os_keychain.append(ref)
    key = Fernet.generate_key()
    kc.store_key(ref, key)  # raises unless the store hands the same bytes back
    assert kc.load_key(ref) == key
    assert kc.delete_key(ref)
    assert kc.load_key(ref) is None


def test_keychain_mode_vault_round_trips_through_credential_manager(os_keychain, hermes_home):
    vault = hermes_home / "vault"
    item = VaultStore().add_item("login", "Example", dict(_LOGIN), origin="https://example.com").id
    ref = kc.read_ref(vault / "vault.keyref")
    assert ref is not None, "keychain mode must keep only a pointer beside the ciphertext"
    os_keychain.append(ref)
    assert not (vault / "vault.key").exists()
    assert VaultStore().resolve_secret(item)["password"] == _LOGIN["password"]

    assert VaultStore().migrate_key("file") == "file"
    assert (vault / "vault.key").exists() and not (vault / "vault.keyref").exists()
    assert kc.load_key(ref) is None, "moving to the file deletes the vault's own credential"
    sids, protected = _acl_principals(vault / "vault.key")
    assert protected and sids == {"S-1-5-18", _current_user_sid()}, "file rollback keeps the owner+SYSTEM DACL"

    assert VaultStore().migrate_key("keychain") == "keychain"
    back = kc.read_ref(vault / "vault.keyref")
    os_keychain.append(back)
    assert not (vault / "vault.key").exists()
    assert VaultStore().resolve_secret(item)["password"] == _LOGIN["password"]


def _current_user_sid() -> str:
    win32api = importlib.import_module("win32api")
    win32con = importlib.import_module("win32con")
    win32security = importlib.import_module("win32security")
    token = win32security.OpenProcessToken(win32api.GetCurrentProcess(), win32con.TOKEN_QUERY)
    return win32security.ConvertSidToStringSid(win32security.GetTokenInformation(token, win32security.TokenUser)[0])


def test_a_restarted_process_opens_the_migrated_vault(os_keychain, hermes_home):
    item_store = VaultStore()
    item_store.add_item("login", "Example", dict(_LOGIN), origin="https://example.com")
    os_keychain.append(kc.read_ref(hermes_home / "vault" / "vault.keyref"))
    assert item_store.migrate_key("file") == "file"
    assert item_store.migrate_key("keychain") == "keychain"
    os_keychain.append(kc.read_ref(hermes_home / "vault" / "vault.keyref"))

    result = _in_new_process(hermes_home, _READ_BACK)
    assert (result.returncode, result.stdout) == (0, "ok"), result.stderr[-400:]


def test_a_move_that_fails_midway_still_opens_after_a_process_restart(os_keychain, hermes_home, monkeypatch):
    (hermes_home / "config.yaml").write_text("vault:\n  key_storage: file\n", encoding="utf-8")
    store = VaultStore()
    store.add_item("login", "Example", dict(_LOGIN), origin="https://example.com")
    real_remove = kc.remove_file

    def interrupted(path):
        if Path(path).name == "vault.key":
            raise PermissionError(13, "simulated crash before the old key is deleted")
        real_remove(path)

    monkeypatch.setattr(kc, "remove_file", interrupted)
    with pytest.raises(Exception, match="could not be removed"):
        store.migrate_key("keychain")
    ref = kc.read_ref(hermes_home / "vault" / "vault.keyref")
    assert ref is not None
    os_keychain.append(ref)
    monkeypatch.setattr(kc, "remove_file", real_remove)

    # Both copies exist after the "crash": a new process must still open the vault, and its rerun must finish.
    result = _in_new_process(hermes_home, _READ_BACK)
    assert (result.returncode, result.stdout) == (0, "ok"), result.stderr[-400:]
    finish = _in_new_process(
        hermes_home, "from agent.vault_store import VaultStore\nprint(VaultStore().migrate_key('keychain'))")
    assert (finish.returncode, finish.stdout.strip()) == (0, "keychain"), finish.stderr[-400:]
    assert not (hermes_home / "vault" / "vault.key").exists()
    again = _in_new_process(hermes_home, _READ_BACK)
    assert (again.returncode, again.stdout) == (0, "ok"), again.stderr[-400:]


def test_the_vault_lock_excludes_another_process_on_windows(tmp_path):
    """Migration must hold a cross-PROCESS lock (CLI and Desktop both write the vault), not only a thread lock."""
    store = VaultStore(tmp_path / "vault")
    probe = (
        "import msvcrt, sys\n"
        f"fd = open({str(tmp_path / 'vault' / '.vault.lock')!r}, 'r+', encoding='utf-8')\n"
        "try:\n"
        "    msvcrt.locking(fd.fileno(), msvcrt.LK_NBLCK, 1)\n"
        "except OSError:\n"
        "    sys.stdout.write('blocked')\n"
        "else:\n"
        "    sys.stdout.write('free')\n"
    )

    def run_probe() -> str:
        return subprocess.run([sys.executable, "-c", probe], capture_output=True, text=True, timeout=60,
                              check=False).stdout

    with store._locked():
        assert run_probe() == "blocked"
    assert run_probe() == "free"
