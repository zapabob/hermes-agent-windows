from __future__ import annotations

import hashlib
import importlib
import json
import os
import sys
import tempfile
import uuid
from contextlib import contextmanager
from pathlib import Path
from typing import Callable, Iterator

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from .bounded_walk import stable_file_time_ns
from .models import ScanResult, Verdict
from .store import SecurityStore, decode_quarantine_findings, utc_now


_MAGIC = b"HERMESQ1"


@contextmanager
def _held_quarantine_source(
    source: Path, expected_size: int
) -> Iterator[tuple[object | None, tuple[int, int, int] | None]]:
    if sys.platform != "win32":
        yield None, None
        return

    win32con = importlib.import_module("win32con")
    win32file = importlib.import_module("win32file")
    # Hold DELETE access without sharing writes or deletes until the verified handle is disposed.
    handle = win32file.CreateFile(
        str(source),
        win32con.GENERIC_READ | win32con.DELETE,
        win32con.FILE_SHARE_READ,
        None,
        win32con.OPEN_EXISTING,
        win32file.FILE_FLAG_OPEN_REPARSE_POINT,
        None,
    )
    try:
        info = win32file.GetFileInformationByHandle(handle)
        if info[0] & (win32con.FILE_ATTRIBUTE_REPARSE_POINT | win32con.FILE_ATTRIBUTE_DIRECTORY):
            raise ValueError("quarantine source is not a regular file")
        identity = (info[4], (info[8] << 32) | info[9], (info[5] << 32) | info[6])
        if expected_size < 0 or identity[2] != expected_size:
            raise RuntimeError("file changed during quarantine")
        yield handle, identity
    finally:
        handle.Close()


def _restrict_windows_acl(path: Path, directory: bool = False) -> None:
    if sys.platform != "win32":
        os.chmod(path, 0o700 if directory else 0o600)
        return
    ntsecuritycon = importlib.import_module("ntsecuritycon")
    win32api = importlib.import_module("win32api")
    win32security = importlib.import_module("win32security")

    owner_name = win32api.GetUserNameEx(2)
    owner_sid, _, _ = win32security.LookupAccountName(None, owner_name)
    system_sid = win32security.CreateWellKnownSid(win32security.WinLocalSystemSid, None)
    acl = win32security.ACL()
    inheritance = 0
    if directory:
        inheritance = win32security.CONTAINER_INHERIT_ACE | win32security.OBJECT_INHERIT_ACE
    acl.AddAccessAllowedAceEx(win32security.ACL_REVISION, inheritance, ntsecuritycon.FILE_ALL_ACCESS, owner_sid)
    acl.AddAccessAllowedAceEx(win32security.ACL_REVISION, inheritance, ntsecuritycon.FILE_ALL_ACCESS, system_sid)
    descriptor = win32security.SECURITY_DESCRIPTOR()
    descriptor.SetSecurityDescriptorOwner(owner_sid, False)
    descriptor.SetSecurityDescriptorDacl(1, acl, 0)
    flags = win32security.OWNER_SECURITY_INFORMATION | win32security.DACL_SECURITY_INFORMATION
    flags |= win32security.PROTECTED_DACL_SECURITY_INFORMATION
    win32security.SetFileSecurity(str(path), flags, descriptor)


def _windows_ads_base(target: Path) -> Path | None:
    if sys.platform != "win32" or ":" not in target.name:
        return None
    parts = target.name.split(":")
    if (
        len(parts) not in (2, 3)
        or not parts[0]
        or not parts[1]
        or (len(parts) == 3 and parts[2].upper() != "$DATA")
    ):
        raise ValueError("unsupported alternate data stream destination")
    return target.with_name(parts[0])


class _ADSRestoreRolledBack(OSError):
    """The newly created stream was disposed after a failed write."""


def _restore_new_windows_ads(target: Path, base: Path, plaintext: bytes) -> None:
    pywintypes = importlib.import_module("pywintypes")
    win32con = importlib.import_module("win32con")
    win32file = importlib.import_module("win32file")
    base_handle = win32file.CreateFile(
        str(base), win32con.GENERIC_READ, win32con.FILE_SHARE_READ, None,
        win32con.OPEN_EXISTING, win32file.FILE_FLAG_OPEN_REPARSE_POINT, None,
    )
    try:
        attributes = win32file.GetFileInformationByHandle(base_handle)[0]
        if attributes & (win32con.FILE_ATTRIBUTE_REPARSE_POINT | win32con.FILE_ATTRIBUTE_DIRECTORY):
            raise ValueError("alternate data stream base is not a regular file")
        try:
            stream_handle = win32file.CreateFile(
                str(target), win32con.GENERIC_READ | win32con.GENERIC_WRITE | win32con.DELETE,
                0, None, win32con.CREATE_NEW, win32file.FILE_FLAG_OPEN_REPARSE_POINT, None,
            )
        except (OSError, pywintypes.error) as exc:
            winerror = getattr(exc, "winerror", None)
            if winerror is None and exc.args:
                winerror = exc.args[0]
            if winerror in (80, 183):
                raise FileExistsError(str(target)) from exc
            raise
        try:
            status, written = win32file.WriteFile(stream_handle, plaintext)
            if status != 0 or written != len(plaintext):
                raise OSError("incomplete alternate data stream restore write")
            win32file.FlushFileBuffers(stream_handle)
            win32file.SetFilePointer(stream_handle, 0, win32file.FILE_BEGIN)
            status, observed = win32file.ReadFile(stream_handle, len(plaintext) + 1)
            if status != 0 or observed != plaintext:
                raise OSError("alternate data stream restore readback mismatch")
        except Exception as write_exc:
            try:
                win32file.SetFileInformationByHandle(
                    stream_handle, win32file.FileDispositionInfo, True,
                )
            except Exception as cleanup_exc:
                raise RuntimeError("alternate data stream restore outcome unknown") from cleanup_exc
            raise _ADSRestoreRolledBack(str(write_exc)) from write_exc
        finally:
            stream_handle.Close()
    finally:
        base_handle.Close()


class VaultKey:
    def __init__(self, root: Path) -> None:
        self.path = root / "vault-key.dpapi"

    def load_or_create(self) -> bytes:
        if self.path.exists():
            protected = self.path.read_bytes()
            if sys.platform == "win32":
                win32crypt = importlib.import_module("win32crypt")

                return bytes(win32crypt.CryptUnprotectData(protected, None, None, None, 0)[1])
            return protected
        key = AESGCM.generate_key(bit_length=256)
        protected = key
        if sys.platform == "win32":
            win32crypt = importlib.import_module("win32crypt")

            protected = bytes(win32crypt.CryptProtectData(key, "Hermes Security Vault", None, None, None, 0))
        self.path.write_bytes(protected)
        _restrict_windows_acl(self.path)
        return key


class QuarantineVault:
    def __init__(self, store: SecurityStore, *, read_only: bool = False) -> None:
        self.store = store
        self.root = store.root / "quarantine"
        self.read_only = read_only or store.read_only
        self.key: bytes | None = None
        if not self.read_only:
            self.root.mkdir(parents=True, exist_ok=True)
            _restrict_windows_acl(self.root, directory=True)
            self.key = VaultKey(store.root).load_or_create()

    def _encrypt(
        self, source: Path, destination: Path, sha256: str,
        *, source_handle: object | None = None, expected_size: int | None = None,
    ) -> None:
        if self.key is None:
            raise RuntimeError("quarantine vault is read-only")
        nonce = os.urandom(12)
        if source_handle is None:
            plaintext = source.read_bytes()
        else:
            if expected_size is None:
                raise ValueError("expected size is required for a held source")
            win32file = importlib.import_module("win32file")
            status, plaintext = win32file.ReadFile(source_handle, expected_size)
            trailing_status, trailing = win32file.ReadFile(source_handle, 1)
            if status or trailing_status or len(plaintext) != expected_size or trailing:
                raise RuntimeError("file changed during quarantine")
        ciphertext = AESGCM(self.key).encrypt(nonce, plaintext, sha256.encode("ascii"))
        destination.write_bytes(_MAGIC + nonce + ciphertext)
        _restrict_windows_acl(destination)

    def _decrypt(self, source: Path, sha256: str) -> bytes:
        if self.key is None:
            raise RuntimeError("quarantine vault is read-only")
        payload = source.read_bytes()
        if not payload.startswith(_MAGIC) or len(payload) < len(_MAGIC) + 28:
            raise ValueError("invalid quarantine blob")
        offset = len(_MAGIC)
        return AESGCM(self.key).decrypt(payload[offset:offset + 12], payload[offset + 12:], sha256.encode("ascii"))

    def quarantine(self, source: Path, result: ScanResult) -> str:
        item_id = str(uuid.uuid4())
        blob_name = f"{item_id}.blob"
        staging = self.root / f".{item_id}.staging"
        destination = self.root / blob_name
        published = False
        recorded = False
        disposition_attempted = False
        try:
            with _held_quarantine_source(source, result.size) as (handle, handle_identity):
                before = source.stat()
                if handle_identity is not None and (
                    before.st_dev & 0xFFFFFFFF,
                    before.st_ino,
                    before.st_size,
                ) != handle_identity:
                    raise RuntimeError("file changed during quarantine")
                if result.file_identity is not None and (
                    before.st_dev,
                    before.st_ino,
                    before.st_size,
                    before.st_mtime_ns,
                    stable_file_time_ns(before),
                ) != result.file_identity:
                    raise RuntimeError("file changed during quarantine")
                self._encrypt(source, staging, result.sha256, source_handle=handle, expected_size=result.size)
                plaintext = self._decrypt(staging, result.sha256)
                if hashlib.sha256(plaintext).hexdigest() != result.sha256:
                    raise ValueError("quarantine verification failed")
                after = source.stat()
                identity_before = (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns)
                identity_after = (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns)
                if identity_before != identity_after or after.st_size != result.size:
                    raise RuntimeError("file changed during quarantine")
                os.replace(staging, destination)
                published = True
                findings = json.dumps([item.to_dict() for item in result.findings], ensure_ascii=False, sort_keys=True)
                versions = json.dumps(result.engine_versions, ensure_ascii=False, sort_keys=True)
                with self.store.connection() as con:
                    con.execute(
                        "INSERT INTO quarantine_items(id,blob_name,original_path,original_filename,sha256,size,verdict,"
                        "findings_json,engine_versions_json,original_atime_ns,original_mtime_ns,original_ctime_ns,"
                        "restore_state,created_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                        (
                            item_id,
                            blob_name,
                            str(source),
                            source.name,
                            result.sha256,
                            result.size,
                            result.verdict.value,
                            findings,
                            versions,
                            before.st_atime_ns,
                            before.st_mtime_ns,
                            before.st_ctime_ns,
                            "pending_source_disposition",
                            utc_now(),
                        ),
                    )
                recorded = True
                # The API may delete the held source and then lose its acknowledgement.
                # From this point onward the blob and pending row are recovery evidence.
                disposition_attempted = True
                if handle is None:
                    source.unlink()
                else:
                    win32file = importlib.import_module("win32file")
                    win32file.SetFileInformationByHandle(handle, win32file.FileDispositionInfo, True)
            # The Windows disposition takes effect when the held handle closes.
            with self.store.connection() as con:
                changed = con.execute(
                    "UPDATE quarantine_items SET restore_state='quarantined' "
                    "WHERE id=? AND restore_state='pending_source_disposition'", (item_id,)
                )
                if changed.rowcount != 1:
                    raise RuntimeError("quarantine outcome record missing")
        except Exception:
            if not disposition_attempted:
                if recorded:
                    with self.store.connection() as con:
                        con.execute("DELETE FROM quarantine_items WHERE id=?", (item_id,))
                if published:
                    destination.unlink(missing_ok=True)
            raise
        finally:
            staging.unlink(missing_ok=True)
        self.store.event("quarantine", item_id, result.verdict.value, "quarantined", {"sha256": result.sha256, "original_path": str(source)})
        return item_id

    def inspect(self, item_id: str) -> dict[str, object]:
        if not self.store.available:
            raise KeyError(item_id)
        with self.store.connection() as con:
            row = con.execute("SELECT * FROM quarantine_items WHERE id=?", (item_id,)).fetchone()
        if row is None:
            raise KeyError(item_id)
        item = dict(row)
        item["findings"] = decode_quarantine_findings(item.pop("findings_json"))
        item["blob_present"] = (self.root / str(item["blob_name"])).is_file()
        return item

    def restore(self, item_id: str, scan: Callable[[Path], ScanResult], destination: Path | None = None, force: bool = False) -> Path:
        item = self.inspect(item_id)
        if item["restore_state"] in ("pending_source_disposition", "pending_restore_outcome"):
            raise ValueError("quarantine outcome pending")
        if item["deleted_at"]:
            raise ValueError("quarantine item was deleted")
        target = destination or Path(str(item["original_path"]))
        if target.exists():
            raise FileExistsError(str(target))
        ads_base = _windows_ads_base(target)
        plaintext = self._decrypt(self.root / str(item["blob_name"]), str(item["sha256"]))
        if hashlib.sha256(plaintext).hexdigest() != item["sha256"]:
            raise ValueError("quarantine blob hash mismatch")
        target.parent.mkdir(parents=True, exist_ok=True)
        handle, temp_name = tempfile.mkstemp(prefix=".hermes-restore-", dir=target.parent)
        os.close(handle)
        temp_path = Path(temp_name)
        try:
            temp_path.write_bytes(plaintext)
            _restrict_windows_acl(temp_path)
            current = scan(temp_path)
            if current.verdict == Verdict.MALICIOUS and not force:
                raise PermissionError("current signatures still classify this item as malicious")
            if ads_base is None:
                os.replace(temp_path, target)
                atime_ns = item.get("original_atime_ns")
                mtime_ns = item.get("original_mtime_ns")
                if isinstance(atime_ns, int) and isinstance(mtime_ns, int):
                    os.utime(target, ns=(atime_ns, mtime_ns))
            else:
                with self.store.connection() as con:
                    claimed = con.execute(
                        "UPDATE quarantine_items SET restore_state='pending_restore_outcome',restore_target=? "
                        "WHERE id=? AND restore_state='quarantined' AND restored_at IS NULL "
                        "AND deleted_at IS NULL", (str(target), item_id),
                    )
                    if claimed.rowcount != 1:
                        raise ValueError("quarantine item is not available for restore")
                try:
                    _restore_new_windows_ads(target, ads_base, plaintext)
                except (_ADSRestoreRolledBack, FileExistsError, ValueError):
                    with self.store.connection() as con:
                        con.execute(
                            "UPDATE quarantine_items SET restore_state='quarantined',restore_target=NULL "
                            "WHERE id=? AND restore_state='pending_restore_outcome'", (item_id,),
                        )
                    raise
        finally:
            temp_path.unlink(missing_ok=True)
        with self.store.connection() as con:
            if ads_base is None:
                con.execute(
                    "UPDATE quarantine_items SET restored_at=?,restore_state='restored' WHERE id=?",
                    (utc_now(), item_id),
                )
            else:
                recorded = con.execute(
                    "UPDATE quarantine_items SET restored_at=?,restore_state='restored' "
                    "WHERE id=? AND restore_state='pending_restore_outcome'",
                    (utc_now(), item_id),
                )
                if recorded.rowcount != 1:
                    raise RuntimeError("alternate data stream restore outcome record missing")
        self.store.event("restore", item_id, current.verdict.value, "restored", {"destination": str(target), "forced": force})
        return target

    def delete(self, item_id: str) -> None:
        if self.read_only:
            raise RuntimeError("quarantine vault is read-only")
        with self.store.connection() as con:
            con.execute("BEGIN IMMEDIATE")
            item = con.execute(
                "SELECT blob_name,verdict,sha256,restore_state,findings_json "
                "FROM quarantine_items WHERE id=?",
                (item_id,),
            ).fetchone()
            if item is None:
                raise KeyError(item_id)
            if item["restore_state"] in ("pending_source_disposition", "pending_restore_outcome"):
                raise ValueError("quarantine outcome pending")
            decode_quarantine_findings(item["findings_json"])
            (self.root / str(item["blob_name"])).unlink(missing_ok=True)
            con.execute(
                "UPDATE quarantine_items SET deleted_at=?,restore_state='deleted' WHERE id=?",
                (utc_now(), item_id),
            )
        self.store.event("quarantine_delete", item_id, str(item["verdict"]), "deleted", {"sha256": item["sha256"]})
