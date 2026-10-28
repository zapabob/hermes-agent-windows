"""Local encrypted vault for browser autofill secrets.

Profile-scoped, model-blind credential store. Metadata (kind, label, origin,
timestamps) lives alongside an encrypted secret payload; the payload is
encrypted at rest with a locally generated Fernet key. The model only ever
sees opaque handles + metadata — secret values are resolved server-side by
the browser fill path and never enter tool results, logs, or the session DB.

Design notes:
- Follows the repo's "default frictionless, 0600 files OK" policy: the key
  file and vault file are created 0600 under ``<HERMES_HOME>/vault/``.
  ``vault.key_storage: keychain`` (opt-in) keeps the key in the OS keychain
  (Windows Credential Manager on Windows) instead -- agent/vault_keychain.py --
  and ``hermes vault key migrate`` moves it. The disk then holds only the
  non-secret pointer ``vault.keyref``.
- Ported design (opaque-handle vault fill) from Merit-Systems/OpenInstinct
  (MIT): lib/manager/server/secret-store.ts + vault services.
- Phase 1 supports three item kinds (``login``, ``payment``, ``address``)
  in the store; browser fill support is login-only.
"""

from __future__ import annotations

import importlib
import json
import logging
import os
import re
import sys
import threading
import uuid
from contextlib import contextmanager, suppress
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional
from urllib.parse import urlsplit

from agent import vault_keychain as kc
from agent.vault_errors import VaultError
from hermes_constants import get_hermes_home
from utils import atomic_write_bytes

logger = logging.getLogger(__name__)

KEY_STORAGE_MODES = ("file", "keychain")

VAULT_KINDS = ("login", "payment", "address")

LOGIN_IDENTIFIER_TYPES = ("email", "phone", "username")

_DEFAULT_PORTS = {"http": 80, "https": 443}

_LOCK = threading.Lock()

# fcntl is Unix-only; Windows locks a byte range with msvcrt (same shape as tools/skill_usage.py).
msvcrt = None
try:
    import fcntl
except ImportError:  # pragma: no cover - platform-specific fallback
    fcntl = None
    with suppress(ImportError):
        import msvcrt


def configured_key_storage() -> str:
    """``vault.key_storage``: where a NEW vault's key goes (``file`` default, or ``keychain``).

    An unrecognised value is treated as ``file`` and logged, so a typo never strands a vault."""
    # Lazy: hermes_cli.config pulls in the whole CLI configuration stack.
    from hermes_cli.config import load_config_readonly

    section = load_config_readonly().get("vault") or {}
    value = section.get("key_storage") if isinstance(section, dict) else None
    mode = str(value or "file").strip().lower()
    if mode not in KEY_STORAGE_MODES:
        logger.warning("vault.key_storage=%r is not one of %s; using 'file'", mode, KEY_STORAGE_MODES)
        return "file"
    return mode


def _restrict_windows_acl(path: Path, *, directory: bool = False) -> None:
    """Restrict a Vault path to the current user and LocalSystem on Windows."""
    if sys.platform != "win32":
        return

    try:
        ntsecuritycon = importlib.import_module("ntsecuritycon")
        win32api = importlib.import_module("win32api")
        win32con = importlib.import_module("win32con")
        win32security = importlib.import_module("win32security")

        owner = win32security.GetTokenInformation(
            win32security.OpenProcessToken(
                win32api.GetCurrentProcess(), win32con.TOKEN_QUERY
            ),
            win32security.TokenUser,
        )[0]
        system = win32security.CreateWellKnownSid(
            win32security.WinLocalSystemSid, None
        )
        inheritance = 0
        if directory:
            inheritance = (
                win32security.CONTAINER_INHERIT_ACE
                | win32security.OBJECT_INHERIT_ACE
            )
        acl = win32security.ACL()
        for sid in (owner, system):
            acl.AddAccessAllowedAceEx(
                win32security.ACL_REVISION,
                inheritance,
                ntsecuritycon.FILE_ALL_ACCESS,
                sid,
            )
        descriptor = win32security.SECURITY_DESCRIPTOR()
        descriptor.SetSecurityDescriptorOwner(owner, False)
        descriptor.SetSecurityDescriptorDacl(True, acl, False)
        descriptor.SetSecurityDescriptorControl(
            win32security.SE_DACL_PROTECTED,
            win32security.SE_DACL_PROTECTED,
        )
        flags = (
            win32security.OWNER_SECURITY_INFORMATION
            | win32security.DACL_SECURITY_INFORMATION
            | win32security.PROTECTED_DACL_SECURITY_INFORMATION
        )
        win32security.SetFileSecurity(str(path), flags, descriptor)
    except Exception as exc:
        raise VaultError("could not secure vault permissions on Windows") from exc


def normalize_origin(url_or_origin: str) -> str:
    """Normalize a URL or origin to ``scheme://host[:port]``.

    Default ports (80 for http, 443 for https) are stripped so that
    ``https://example.com`` and ``https://example.com:443`` compare equal.
    Raises :class:`VaultError` for values without a scheme + host.
    """
    value = (url_or_origin or "").strip()
    if not value:
        raise VaultError("origin is required")
    if "://" not in value:
        raise VaultError(f"origin must include a scheme (got {value!r})")
    parts = urlsplit(value)
    scheme = (parts.scheme or "").lower()
    host = (parts.hostname or "").lower()
    if not scheme or not host:
        raise VaultError(f"could not parse origin from {value!r}")
    try:
        port = parts.port
    except ValueError as exc:
        raise VaultError(f"invalid port in origin {value!r}") from exc
    if port is None or port == _DEFAULT_PORTS.get(scheme):
        return f"{scheme}://{host}"
    return f"{scheme}://{host}:{port}"


@dataclass(frozen=True)
class VaultItemMeta:
    """Metadata-only view of a vault item. Never contains secret values."""

    id: str
    kind: str
    label: str
    origin: Optional[str]
    created_at: str

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "kind": self.kind,
            "label": self.label,
            "origin": self.origin,
            "created_at": self.created_at,
        }


class VaultStore:
    """Encrypted, profile-scoped vault under ``<HERMES_HOME>/vault/``."""

    def __init__(self, base_dir: Optional[Path] = None):
        self._base = Path(base_dir) if base_dir is not None else (
            Path(get_hermes_home()) / "vault"
        )
        self._vault_path = self._base / "vault.json.enc"
        self._key_path = self._base / "vault.key"
        # Keychain mode (vault.key_storage: keychain) keeps only this non-secret pointer beside the
        # ciphertext; agent/vault_keychain.py owns the entry it names.
        self._keyref_path = self._base / "vault.keyref"

    # -- key / crypto ------------------------------------------------------

    def _ensure_dir(self) -> None:
        self._base.mkdir(mode=0o700, parents=True, exist_ok=True)
        # Route through the canonical securer (honors managed/NixOS
        # group-share mode and HERMES_UID/GID ownership) rather than a
        # bespoke chmod — same requirement as the browser-profile snapshot
        # dir (f1d05c review).
        try:
            from hermes_cli.config import _secure_dir

            _secure_dir(self._base)
        except Exception:
            try:
                os.chmod(self._base, 0o700)
            except OSError:
                pass
        _restrict_windows_acl(self._base, directory=True)

    @contextmanager
    def _locked(self, *, create: bool = True):
        """Serialize read-modify-write cycles across threads AND processes: the Desktop gateway, a CLI
        ``hermes vault add`` / ``key migrate`` and a TUI slash worker all touch the same vault files;
        two unlocked writers would drop each other's items or race a key move. ``create=False`` (read
        paths) never creates the vault directory just to look inside it."""
        with _LOCK:
            if not create and not self._base.exists():
                yield
                return
            self._ensure_dir()
            lock_path = self._base / ".vault.lock"
            if msvcrt and (not lock_path.exists() or lock_path.stat().st_size == 0):
                lock_path.write_text(" ", encoding="utf-8")  # msvcrt needs a non-empty byte range to lock
            with open(lock_path, "r+" if msvcrt else "a+", encoding="utf-8") as fd:
                if fcntl:
                    fcntl.flock(fd, fcntl.LOCK_EX)
                elif msvcrt:
                    fd.seek(0)
                    msvcrt.locking(fd.fileno(), msvcrt.LK_LOCK, 1)
                try:
                    yield
                finally:
                    with suppress(OSError):
                        if fcntl:
                            fcntl.flock(fd, fcntl.LOCK_UN)
                        elif msvcrt:
                            fd.seek(0)
                            msvcrt.locking(fd.fileno(), msvcrt.LK_UNLCK, 1)

    def _fernet(self):
        from cryptography.fernet import Fernet

        return Fernet(self._key())

    def _has_ciphertext(self) -> bool:
        return self._vault_path.exists() and self._vault_path.stat().st_size > 0

    def _key(self) -> bytes:
        """``vault.key`` when present (the legacy layout wins), else the keychain entry ``vault.keyref``
        names, else a new key for a vault that has no items yet. Never mints a key over ciphertext:
        that would make the saved items unrecoverable for good."""
        self._ensure_dir()
        if self._key_path.exists():
            with suppress(OSError):
                os.chmod(self._key_path, 0o600)
            _restrict_windows_acl(self._key_path)
            return self._key_path.read_bytes().strip()
        ref = kc.read_ref(self._keyref_path)
        if ref is not None:
            try:
                ref = self._adopt(ref)
                key = kc.load_key(ref)
            except kc.KeychainUnavailable as exc:
                key, why = None, f"the OS keychain is not reachable here: {exc}"
            else:
                why = f"the keychain entry {ref.get('service')!r} / {ref['account']!r} is gone"
            if key:
                return key
        else:
            why = f"{self._key_path.name} is missing"
        if self._has_ciphertext():
            raise VaultError(self._missing_key_message(why))
        return self._create_key()

    def _missing_key_message(self, why: str) -> str:
        return (f"The vault key could not be found ({why}). vault.json.enc in {self._base} was left untouched. "
                "If this profile came from another machine, run `hermes vault key migrate --to file` there and "
                "copy its vault.key next to vault.json.enc; if the keychain entry was deleted, restore it from a "
                "keychain backup. `hermes vault key` shows where the key is expected. To start over instead, "
                "delete vault.json.enc (its saved items are lost).")

    def _conflicting_key_message(self) -> str:
        # Never overwrite or delete the other copy here: it may be the only key that opens the vault.
        return (f"{self._key_path} does not decrypt vault.json.enc, so the key was not moved and nothing "
                "was deleted. If the vault's key is in the OS keychain, move this vault.key aside and run "
                "`hermes vault key` again.")

    def _create_key(self) -> bytes:
        """A key for a vault with no ciphertext yet. ``vault.key_storage: keychain`` is an explicit
        request: an unusable keychain refuses (no key is minted, nothing is written) instead of quietly
        downgrading the key to a file the user asked not to use."""
        from cryptography.fernet import Fernet

        key = Fernet.generate_key()
        if configured_key_storage() == "keychain":
            ref = kc.new_ref(self._base)
            try:
                kc.store_key(ref, key)
            except kc.KeychainUnavailable as exc:
                raise VaultError(
                    f"vault.key_storage is 'keychain' but the OS keychain cannot be used ({exc}); no vault key "
                    "was created. Fix the keychain, or run `hermes vault key migrate --to file` to keep the "
                    "key in vault.key.") from exc
            try:
                self._save_new_ref(ref)
            except (OSError, VaultError) as exc:
                raise VaultError(f"could not save {self._keyref_path.name} ({exc}); no vault key was created") from exc
            return key
        kc.remove_file(self._keyref_path)
        self._write_key_file(key)
        return key

    def _write_key_file(self, key: bytes) -> None:
        """Atomic + directory fsync: an interrupted write must never leave a partial vault.key, which
        reads prefer over a working keychain entry. The protected current-user/LocalSystem DACL is
        applied (and enforced) before the file is trusted; if it cannot be, the file is removed again.
        Callers hold the vault lock."""
        atomic_write_bytes(self._key_path, key, mode=0o600, fsync_dir=True)
        try:
            _restrict_windows_acl(self._key_path)
        except VaultError:
            with suppress(OSError):
                kc.remove_file(self._key_path)
            raise

    def _write_ref(self, ref: dict) -> None:
        kc.write_ref(self._keyref_path, ref)
        _restrict_windows_acl(self._keyref_path)

    def _save_new_ref(self, ref: dict) -> None:
        kc.save_new_ref(self._keyref_path, ref)
        _restrict_windows_acl(self._keyref_path)

    def own_copied_key(self, published_base: Path) -> Optional[dict]:
        """A ``--clone-all`` copy carries the source's ``vault.keyref``, which names the SOURCE's entry;
        the source moving its key to a file deletes that entry. Before the clone is published at
        ``published_base``, give it an entry of its own, so it never depends on another profile.
        Returns the new entry's ref (the caller deletes exactly that entry if publication fails), or
        None when nothing was shared. Raises VaultError when the keychain cannot be read or written:
        the clone must not be published sharing the source's entry."""
        ref = kc.read_ref(self._keyref_path)
        if ref is None or self._key_path.exists():
            return None  # key file layout (a vault.key always wins on read): nothing is shared
        try:
            key = kc.load_key(ref)
            if not self._decrypts(key):
                return None  # the source's own entry is already gone: the copy is no worse off than it
            mine = kc.new_ref(published_base)
            kc.store_key(mine, key)
        except kc.KeychainUnavailable as exc:
            raise VaultError(
                f"its key is in the OS keychain, which this session cannot use ({exc}). Clone from a session "
                "that can reach the keychain, or run `hermes vault key migrate --to file` on the source first.") from exc
        try:
            self._write_ref(mine)
        except (OSError, VaultError):
            kc.delete_key(mine)  # the staged clone is discarded with this error, a landed pointer included
            raise
        return mine

    def _adopt(self, ref: dict) -> dict:
        """Give a moved vault (profile rename, or a clone made before clones got their own entry at
        creation) its own keychain entry. Never deletes the entry it came from: another copy may still
        depend on it. Raises KeychainUnavailable only when the shared entry cannot be read; if the new
        entry cannot be written, the shared one keeps serving."""
        if kc.owns(ref, self._base):
            return ref
        key = kc.load_key(ref)
        if not self._decrypts(key):
            return ref
        mine = kc.new_ref(self._base)
        try:
            kc.store_key(mine, key)
            self._write_ref(mine)
        except (kc.KeychainUnavailable, OSError, VaultError):
            # The replace can land before the error (e.g. a temp-file cleanup failing on Windows): then
            # the saved pointer already names the new entry, which must survive.
            with suppress(VaultError):
                if (kc.read_ref(self._keyref_path) or {}).get("account") == mine["account"]:
                    return mine
            kc.delete_key(mine)  # no orphan per retry; the shared entry keeps serving reads
            logger.warning("could not give the copied vault in %s its own keychain entry", self._base, exc_info=True)
            return ref
        return mine

    def _decrypts(self, key: Optional[bytes]) -> bool:
        from cryptography.fernet import Fernet, InvalidToken

        if not key:
            return False
        if not self._has_ciphertext():
            return True
        try:
            Fernet(key).decrypt(self._vault_path.read_bytes())
        except (InvalidToken, ValueError):
            return False
        return True

    # -- key storage ---------------------------------------------------------

    def key_location(self) -> dict[str, Any]:
        """Where this vault's key lives (never the key itself), for ``hermes vault key``."""
        ref = kc.read_ref(self._keyref_path)
        if self._key_path.exists():
            where = {"storage": "file", "path": str(self._key_path)}
            if ref is not None:  # a keychain copy that could not be removed yet
                where["keychain_entry_left"] = ref["account"]
            return where
        return dict(ref) if ref else {"storage": "none", "path": str(self._key_path)}

    def migrate_key(self, target: str) -> str:
        """Move the key between ``vault.key`` and the OS keychain. The destination is written and proven
        to decrypt the vault before the source is removed, so an interrupted move leaves a working vault
        and re-running it finishes the job. A failed move keeps the original storage and raises."""
        if target not in KEY_STORAGE_MODES:
            raise VaultError("key storage must be 'file' or 'keychain'")
        with self._locked():
            return self._migrate_to_keychain() if target == "keychain" else self._migrate_to_file()

    def _migrate_to_keychain(self) -> str:
        existing = kc.read_ref(self._keyref_path)
        if not self._key_path.exists():
            if existing is not None:  # already moved: prove the entry still opens the vault
                try:
                    key = kc.load_key(self._adopt(existing))
                except kc.KeychainUnavailable as exc:
                    raise VaultError(f"cannot read the vault key from the OS keychain: {exc}") from exc
                if not self._decrypts(key):
                    raise VaultError(self._missing_key_message(f"the keychain entry {existing['account']!r} does not open the vault"))
                return "keychain"
            if self._has_ciphertext():
                raise VaultError(self._missing_key_message(f"{self._key_path.name} is missing"))
            try:
                kc.os_keyring()  # nothing to move yet, but the new vault's key must have somewhere to go
            except kc.KeychainUnavailable as exc:
                raise VaultError(f"cannot use the OS keychain: {exc}") from exc
            return "keychain"
        key = self._key_path.read_bytes().strip()
        if not self._decrypts(key):
            raise VaultError(self._conflicting_key_message())
        # Resume into our own entry from an interrupted move; a copied pointer's entry is not ours to overwrite.
        ref = existing if existing is not None and kc.owns(existing, self._base) else kc.new_ref(self._base)
        try:
            kc.store_key(ref, key)  # write + readback match
            if not self._decrypts(kc.load_key(ref)):  # the stored copy must open the existing ciphertext
                raise kc.KeychainUnavailable("the key read back from the keychain does not decrypt the vault")
        except kc.KeychainUnavailable as exc:
            if ref is not existing:
                kc.delete_key(ref)
            raise VaultError(f"could not move the vault key to the OS keychain ({exc}); "
                             f"it stays in {self._key_path}") from exc
        if ref is not existing:
            try:
                self._save_new_ref(ref)  # atomic pointer commit (deletes the new entry if it cannot land)
            except (OSError, VaultError) as exc:
                raise VaultError(f"could not save {self._keyref_path.name} ({exc}); the key stays in {self._key_path}") from exc
        try:
            kc.remove_file(self._key_path)  # the old key goes last, only after everything above held
        except OSError as exc:
            raise VaultError(
                f"the key now also lives in the OS keychain, but {self._key_path} could not be removed ({exc}); "
                "the vault keeps working from the file. Run `hermes vault key migrate --to keychain` again "
                "to finish.") from exc
        return "keychain"

    def _migrate_to_file(self) -> str:
        ref = kc.read_ref(self._keyref_path)
        if self._key_path.exists():
            if ref is not None:  # a move stopped with both copies present; the file is the one in use
                if not self._decrypts(self._key_path.read_bytes().strip()):
                    raise VaultError(self._conflicting_key_message())
                self._release_ref(ref)
            return "file"
        if ref is None:
            if self._has_ciphertext():
                raise VaultError(self._missing_key_message(f"{self._key_path.name} is missing"))
            return "file"
        try:
            key = kc.load_key(ref)
        except kc.KeychainUnavailable as exc:
            raise VaultError(f"cannot read the vault key from the OS keychain: {exc}") from exc
        if not key or not self._decrypts(key):
            raise VaultError(self._missing_key_message(f"the keychain entry {ref['account']!r} does not hold this vault's key"))
        self._write_key_file(key)
        if self._key_path.read_bytes().strip() != key:
            kc.remove_file(self._key_path)
            raise VaultError(f"could not write {self._key_path}; the key stays in the OS keychain")
        self._release_ref(ref)
        return "file"

    def _release_ref(self, ref: dict) -> None:
        """The file holds the key now: drop the keychain copy. An entry this vault does not own (copied
        pointer) is left alone; if deleting ours fails, the pointer stays so a rerun can finish."""
        if kc.owns(ref, self._base) and not kc.delete_key(ref):
            return
        kc.remove_file(self._keyref_path)

    # -- persistence -------------------------------------------------------

    def _read_all(self) -> List[Dict[str, Any]]:
        if not self._vault_path.exists():
            return []
        blob = self._vault_path.read_bytes()
        if not blob:
            return []
        from cryptography.fernet import InvalidToken

        try:
            raw = self._fernet().decrypt(blob)
        except InvalidToken as exc:
            raise VaultError(
                "vault file could not be decrypted (key mismatch or corruption)"
            ) from exc
        data = json.loads(raw.decode("utf-8"))
        items = data.get("items", [])
        return items if isinstance(items, list) else []

    def _write_all(self, items: List[Dict[str, Any]]) -> None:
        self._ensure_dir()
        payload = json.dumps({"version": 1, "items": items}).encode("utf-8")
        blob = self._fernet().encrypt(payload)
        tmp = self._vault_path.with_suffix(".enc.tmp")
        fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        try:
            os.write(fd, blob)
        finally:
            os.close(fd)
        os.replace(tmp, self._vault_path)
        try:
            os.chmod(self._vault_path, 0o600)
        except OSError:
            pass
        _restrict_windows_acl(self._vault_path)

    # -- public API ----------------------------------------------------------

    def add_item(
        self,
        kind: str,
        label: str,
        secret: Dict[str, Any],
        origin: Optional[str] = None,
    ) -> VaultItemMeta:
        """Add an item. ``secret`` is the sensitive payload (encrypted at rest).

        For ``kind='login'``, ``origin`` is required and the secret payload
        must contain ``identifier_type``, ``identifier`` and ``password``.
        """
        if kind not in VAULT_KINDS:
            raise VaultError(f"unknown vault kind {kind!r} (expected one of {VAULT_KINDS})")
        label = (label or "").strip()
        if not label:
            raise VaultError("label is required")
        norm_origin: Optional[str] = None
        if kind == "login":
            if not origin:
                raise VaultError("origin is required for login items")
            norm_origin = normalize_origin(origin)
            id_type = secret.get("identifier_type")
            if id_type not in LOGIN_IDENTIFIER_TYPES:
                raise VaultError(
                    f"identifier_type must be one of {LOGIN_IDENTIFIER_TYPES}"
                )
            if not secret.get("identifier") or not secret.get("password"):
                raise VaultError("login items require identifier and password")
        elif origin:
            norm_origin = normalize_origin(origin)

        item_id = f"vault_{uuid.uuid4().hex[:12]}"
        record = {
            "id": item_id,
            "kind": kind,
            "label": label,
            "origin": norm_origin,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "secret": dict(secret),
        }
        with self._locked():
            items = self._read_all()
            items.append(record)
            self._write_all(items)
        return self._meta(record)

    def list_items(self) -> List[VaultItemMeta]:
        """Metadata-only listing. Secret payloads are never included."""
        with self._locked(create=False):
            return [self._meta(rec) for rec in self._read_all()]

    def has_items(self) -> bool:
        try:
            with self._locked(create=False):
                return bool(self._read_all())
        except Exception:
            return False

    def remove_item(self, item_id: str) -> bool:
        with self._locked(create=False):
            items = self._read_all()
            remaining = [rec for rec in items if rec.get("id") != item_id]
            if len(remaining) == len(items):
                return False
            self._write_all(remaining)
            return True

    def get_meta(self, item_id: str) -> Optional[VaultItemMeta]:
        with self._locked(create=False):
            for rec in self._read_all():
                if rec.get("id") == item_id:
                    return self._meta(rec)
        return None

    def resolve_secret(self, item_id: str) -> Dict[str, Any]:
        """Resolve the decrypted secret payload for server-side use ONLY.

        Callers must never place the returned values into tool results,
        logs, exceptions, or any string that reaches the session DB.
        """
        with self._locked(create=False):
            for rec in self._read_all():
                if rec.get("id") == item_id:
                    return dict(rec.get("secret") or {})
        raise VaultError(f"no vault item with id {item_id!r}")

    @staticmethod
    def _meta(rec: Dict[str, Any]) -> VaultItemMeta:
        return VaultItemMeta(
            id=str(rec.get("id", "")),
            kind=str(rec.get("kind", "")),
            label=str(rec.get("label", "")),
            origin=rec.get("origin"),
            created_at=str(rec.get("created_at", "")),
        )


def get_vault_store() -> VaultStore:
    """Default profile-scoped vault store."""
    return VaultStore()


def scrub_secret_from_text(text: str, secret: Dict[str, Any]) -> str:
    """Defensively strip any secret values from a string (e.g. an exception
    message) before it can be surfaced. Case-sensitive exact substring scrub."""
    scrubbed = text
    for value in secret.values():
        if isinstance(value, str) and len(value) >= 3 and value in scrubbed:
            scrubbed = scrubbed.replace(value, "[REDACTED]")
    # Also collapse anything that looks like a leaked password-ish token in
    # common key=value echoes.
    scrubbed = re.sub(r"(password['\"]?\s*[:=]\s*)\S+", r"\1[REDACTED]", scrubbed)
    return scrubbed
