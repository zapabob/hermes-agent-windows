"""OS-keychain storage for the local vault key (opt-in: ``vault.key_storage: keychain``).

The vault key normally sits in ``vault.key`` next to the ciphertext. In keychain mode it lives in
the OS credential store instead (Windows Credential Manager, macOS Keychain, Secret Service /
KWallet on Linux, via the optional ``keyring`` package), and the vault directory keeps only a
non-secret pointer, ``vault.keyref``, naming the entry. A backup, a synced folder or a copied home
directory then holds ciphertext without its key.

This does not isolate the key from code running as the same OS user: any such process (including
an in-process plugin) can ask the keychain for it, or simply call the vault API.

Selective port of NousResearch/hermes-agent ``agent/vault_keychain.py`` (e5ea5fd): the downstream
differences are a ``vault_errors`` module instead of inline imports, a case-insensitive ownership
check (Windows paths) and an install hint that names the plain ``keyring`` package.
"""

from __future__ import annotations

import json
import logging
import os
import uuid
from contextlib import suppress
from pathlib import Path
from typing import Optional

from agent.vault_errors import VaultError
from utils import atomic_write_bytes

logger = logging.getLogger(__name__)

SERVICE = "Hermes Agent vault key"

# keyring backends that are not an OS credential store: ``fail``/``null`` are what keyring picks on
# a headless Linux box with no Secret Service, and keyrings.alt's plaintext/encrypted-file keyrings
# would only move the key into another file under the same home.
_NOT_A_KEYCHAIN = ("keyring.backends.fail", "keyring.backends.null", "keyrings.alt")


class KeychainUnavailable(Exception):
    """No OS keychain is reachable from this process (headless, no keyring package, plaintext backend)."""


def _is_os_keychain(backend) -> bool:
    children = getattr(backend, "backends", None)
    if children is not None:  # keyring's ChainerBackend writes to its highest-priority child
        return bool(children) and _is_os_keychain(children[0])
    return not type(backend).__module__.startswith(_NOT_A_KEYCHAIN)


def os_keyring():
    """The OS credential store keyring resolves to, or raise :class:`KeychainUnavailable`."""
    try:
        import keyring  # optional dependency: absent installs keep the file layout
    except ImportError as exc:
        raise KeychainUnavailable(
            "the optional `keyring` package is not installed (install it into the Hermes environment, "
            "e.g. `uv pip install keyring`)") from exc
    try:
        backend = keyring.get_keyring()
    except Exception as exc:  # health: allow BLE001 -- backend discovery runs third-party entry points
        raise KeychainUnavailable(f"keyring could not pick a backend ({type(exc).__name__})") from exc
    if not _is_os_keychain(backend):
        raise KeychainUnavailable(
            f"no OS keychain is reachable from this session (keyring backend: {type(backend).__module__}.{type(backend).__name__})")
    return backend


def backend_label() -> str:
    """Human name of the keychain this process would use, for ``hermes vault key``."""
    try:
        backend = os_keyring()
    except KeychainUnavailable as exc:
        return f"unavailable: {exc}"
    return str(getattr(backend, "name", "") or type(backend).__name__)


def _same_dir(left: object, right: Path) -> bool:
    """Path equality as the host filesystem sees it (Windows is case-insensitive)."""
    if not isinstance(left, str) or not left:
        return False
    return os.path.normcase(left) == os.path.normcase(str(Path(right).resolve()))


def new_ref(vault_dir: Path) -> dict:
    """Keychain coordinates for a new entry. The account is random, never derived from the path: a
    renamed profile keeps its pointer, and a new profile reusing the old name must not land on (and
    overwrite) the renamed vault's entry. ``vault_dir`` records which directory owns the entry."""
    return {"storage": "keychain", "service": SERVICE, "account": f"vault-{uuid.uuid4().hex}",
            "vault_dir": str(Path(vault_dir).resolve())}


def owns(ref: dict, vault_dir: Path) -> bool:
    """False for a pointer copied or moved from another directory (profile clone/rename): the entry
    it names may still be another vault's only key, so this vault must not overwrite or delete it."""
    return _same_dir(ref.get("vault_dir"), vault_dir)


def read_ref(path: Path) -> Optional[dict]:
    try:
        data = json.loads(path.read_text(encoding="utf-8-sig"))
    except FileNotFoundError:
        return None
    except (OSError, ValueError) as exc:
        raise VaultError(f"{path.name} is unreadable ({type(exc).__name__}); see `hermes vault key`") from exc
    if not isinstance(data, dict) or data.get("storage") != "keychain" or not data.get("account"):
        raise VaultError(f"{path.name} does not describe a keychain entry; see `hermes vault key`")
    return data


def write_ref(path: Path, ref: dict) -> None:
    atomic_write_bytes(path, json.dumps(ref, indent=2).encode("utf-8"), mode=0o600, fsync_dir=True)


def save_new_ref(path: Path, ref: dict) -> None:
    """Save the pointer to an entry just created. If saving fails, delete the entry unless the pointer
    did land (a replace can succeed before a later step errors): every account is random, so an entry
    no pointer names is a key Hermes would never find or remove again."""
    try:
        write_ref(path, ref)
    except OSError:
        with suppress(VaultError):
            if (read_ref(path) or {}).get("account") == ref["account"]:
                raise
        delete_key(ref)
        raise


def load_key(ref: dict) -> Optional[bytes]:
    """The stored key, or None when the entry is gone. Raises KeychainUnavailable."""
    backend = os_keyring()
    try:
        value = backend.get_password(str(ref.get("service") or SERVICE), str(ref["account"]))
    except Exception as exc:  # health: allow BLE001 -- a locked or dismissed keychain raises backend-specific types
        raise KeychainUnavailable(f"the OS keychain did not answer ({type(exc).__name__})") from exc
    return value.encode("ascii") if value else None


def store_key(ref: dict, key: bytes) -> None:
    """Write the key and read it back: a store that accepts a write it cannot return is unusable."""
    backend = os_keyring()
    service, account = str(ref.get("service") or SERVICE), str(ref["account"])
    try:
        backend.set_password(service, account, key.decode("ascii"))
        readback = backend.get_password(service, account)
    except Exception as exc:  # health: allow BLE001 -- every keyring backend raises its own types
        raise KeychainUnavailable(f"the OS keychain refused the key ({type(exc).__name__})") from exc
    if readback != key.decode("ascii"):
        raise KeychainUnavailable("the OS keychain did not return the key it was given")


def delete_key(ref: dict) -> bool:
    """True once the entry is gone, including when an earlier, interrupted cleanup already removed it."""
    service, account = str(ref.get("service") or SERVICE), str(ref["account"])
    try:
        backend = os_keyring()
        with suppress(Exception):  # a missing entry raises PasswordDeleteError; the read below decides
            backend.delete_password(service, account)
        return backend.get_password(service, account) is None
    except Exception:  # health: allow BLE001 -- unreachable keychain: the caller keeps the pointer to retry
        logger.warning("could not confirm deletion of keychain entry %r", account)
        return False


def remove_file(path: Path) -> None:
    """Delete *path*; a file that is already gone counts as removed. Other OS errors propagate."""
    try:
        os.remove(path)
    except FileNotFoundError:
        pass
