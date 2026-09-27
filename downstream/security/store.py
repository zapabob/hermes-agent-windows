from __future__ import annotations

import json
import sqlite3
import threading
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator

from hermes_constants import get_hermes_home

from .models import EngineState, Finding, ScanResult, Verdict


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def decode_quarantine_findings(value: object) -> object:
    """Reject damaged evidence before exposing a quarantine observation."""
    if not isinstance(value, str):
        raise sqlite3.DatabaseError("invalid quarantine findings")
    try:
        findings = json.loads(value)
    except json.JSONDecodeError as exc:
        raise sqlite3.DatabaseError("invalid quarantine findings") from exc
    if not isinstance(findings, list) or any(
        not isinstance(item, dict)
        or not isinstance(item.get("source"), str)
        or not isinstance(item.get("name"), str)
        for item in findings
    ):
        raise sqlite3.DatabaseError("invalid quarantine findings")
    return findings


class SecurityStore:
    def __init__(self, root: Path | None = None, *, read_only: bool = False) -> None:
        self.root = root or (get_hermes_home() / "security")
        self.path = self.root / "security.db"
        self.read_only = read_only
        self._lock = threading.RLock()
        if not self.read_only:
            self.root.mkdir(parents=True, exist_ok=True)
            self._initialize()

    @property
    def available(self) -> bool:
        return self.path.is_file()

    def _require_writable(self) -> None:
        if self.read_only:
            raise RuntimeError("security store is read-only")

    @contextmanager
    def connection(self) -> Iterator[sqlite3.Connection]:
        if self.read_only:
            if not self.available:
                raise FileNotFoundError(self.path)
            con = sqlite3.connect(f"{self.path.resolve().as_uri()}?mode=ro", uri=True, timeout=30)
        else:
            con = sqlite3.connect(self.path, timeout=30)
        con.row_factory = sqlite3.Row
        if self.read_only:
            con.execute("PRAGMA query_only=ON")
        else:
            con.execute("PRAGMA journal_mode=WAL")
        con.execute("PRAGMA foreign_keys=ON")
        try:
            yield con
            if not self.read_only:
                con.commit()
        finally:
            con.close()

    def _initialize(self) -> None:
        schema = "\n".join((
            "CREATE TABLE IF NOT EXISTS feed_state (name TEXT PRIMARY KEY, version TEXT NOT NULL, updated_at TEXT NOT NULL, status TEXT NOT NULL, details_json TEXT NOT NULL DEFAULT '{}');",
            "CREATE TABLE IF NOT EXISTS malware_hashes (sha256 TEXT PRIMARY KEY CHECK(length(sha256)=64), label TEXT NOT NULL, source TEXT NOT NULL, malware_family TEXT, confidence INTEGER NOT NULL DEFAULT 100, first_seen TEXT, last_seen TEXT, feed_version TEXT NOT NULL, updated_at TEXT NOT NULL);",
            "CREATE TABLE IF NOT EXISTS iocs (kind TEXT NOT NULL, value TEXT NOT NULL, label TEXT NOT NULL, source TEXT NOT NULL, updated_at TEXT NOT NULL, PRIMARY KEY(kind, value));",
            "CREATE TABLE IF NOT EXISTS scan_results (id INTEGER PRIMARY KEY AUTOINCREMENT, path TEXT NOT NULL, sha256 TEXT NOT NULL, size INTEGER NOT NULL, verdict TEXT NOT NULL, score INTEGER NOT NULL, action TEXT NOT NULL, findings_json TEXT NOT NULL, versions_json TEXT NOT NULL, cache_key TEXT NOT NULL, scanned_at TEXT NOT NULL, error TEXT, cache_valid INTEGER NOT NULL DEFAULT 1, cache_generation INTEGER NOT NULL DEFAULT 0, UNIQUE(sha256, cache_key));",
            "CREATE TABLE IF NOT EXISTS scan_cache_epochs (sha256 TEXT NOT NULL, cache_key TEXT NOT NULL, epoch INTEGER NOT NULL, PRIMARY KEY(sha256, cache_key));",
            "CREATE TABLE IF NOT EXISTS quarantine_items (id TEXT PRIMARY KEY, blob_name TEXT NOT NULL UNIQUE, original_path TEXT NOT NULL, original_filename TEXT NOT NULL, sha256 TEXT NOT NULL, size INTEGER NOT NULL, verdict TEXT NOT NULL, findings_json TEXT NOT NULL, engine_versions_json TEXT NOT NULL DEFAULT '{}', original_atime_ns INTEGER, original_mtime_ns INTEGER, original_ctime_ns INTEGER, restore_state TEXT NOT NULL DEFAULT 'quarantined', created_at TEXT NOT NULL, restored_at TEXT, deleted_at TEXT);",
            "CREATE TABLE IF NOT EXISTS allowlist (kind TEXT NOT NULL, value TEXT NOT NULL, reason TEXT NOT NULL, created_by TEXT NOT NULL DEFAULT 'local_user', created_at TEXT NOT NULL, expires_at TEXT, PRIMARY KEY(kind, value));",
            "CREATE TABLE IF NOT EXISTS detection_events (id INTEGER PRIMARY KEY AUTOINCREMENT, event_type TEXT NOT NULL, subject TEXT NOT NULL, verdict TEXT, action TEXT NOT NULL, details_json TEXT NOT NULL, created_at TEXT NOT NULL);",
            "CREATE INDEX IF NOT EXISTS idx_scan_results_time ON scan_results(scanned_at DESC);",
            "CREATE INDEX IF NOT EXISTS idx_detection_events_time ON detection_events(created_at DESC);",
        ))
        with self._lock, self.connection() as con:
            con.executescript(schema)
            # Lock before reading columns so another process cannot migrate from the same stale schema.
            con.execute("BEGIN IMMEDIATE")
            migrations = {
                "malware_hashes": (
                    ("malware_family", "TEXT"),
                    ("confidence", "INTEGER NOT NULL DEFAULT 100"),
                    ("first_seen", "TEXT"),
                    ("last_seen", "TEXT"),
                ),
                "scan_results": (
                    ("cache_valid", "INTEGER NOT NULL DEFAULT 0"),
                    ("cache_generation", "INTEGER NOT NULL DEFAULT 0"),
                ),
                "quarantine_items": (
                    ("original_filename", "TEXT NOT NULL DEFAULT ''"),
                    ("engine_versions_json", "TEXT NOT NULL DEFAULT '{}'"),
                    ("original_atime_ns", "INTEGER"),
                    ("original_mtime_ns", "INTEGER"),
                    ("original_ctime_ns", "INTEGER"),
                    ("restore_state", "TEXT NOT NULL DEFAULT 'quarantined'"),
                ),
                "allowlist": (
                    ("created_by", "TEXT NOT NULL DEFAULT 'local_user'"),
                    ("expires_at", "TEXT"),
                ),
            }
            for table, columns in migrations.items():
                existing = {row[1] for row in con.execute(f"PRAGMA table_info({table})")}
                for name, declaration in columns:
                    if name not in existing:
                        con.execute(f"ALTER TABLE {table} ADD COLUMN {name} {declaration}")

    def lookup_hash(self, sha256: str) -> sqlite3.Row | None:
        if not self.available:
            return None
        with self.connection() as con:
            return con.execute("SELECT * FROM malware_hashes WHERE sha256=?", (sha256,)).fetchone()

    def upsert_malware_hash(
        self,
        sha256: str,
        *,
        source: str,
        malware_family: str,
        confidence: int = 100,
        feed_version: str = "local",
        first_seen: str | None = None,
        last_seen: str | None = None,
    ) -> None:
        self._require_writable()
        canonical = sha256.strip().lower()
        if len(canonical) != 64 or any(character not in "0123456789abcdef" for character in canonical):
            raise ValueError("sha256 must be 64 lowercase hexadecimal characters")
        now = utc_now()
        with self._lock, self.connection() as con:
            con.execute(
                "INSERT INTO malware_hashes(sha256,label,source,malware_family,confidence,first_seen,last_seen,feed_version,updated_at) "
                "VALUES(?,?,?,?,?,?,?,?,?) ON CONFLICT(sha256) DO UPDATE SET "
                "label=excluded.label,source=excluded.source,malware_family=excluded.malware_family,"
                "confidence=excluded.confidence,first_seen=excluded.first_seen,last_seen=excluded.last_seen,"
                "feed_version=excluded.feed_version,updated_at=excluded.updated_at",
                (
                    canonical,
                    malware_family,
                    source,
                    malware_family,
                    max(0, min(int(confidence), 100)),
                    first_seen or now,
                    last_seen or now,
                    feed_version,
                    now,
                ),
            )

    def is_allowed(self, sha256: str, path: str) -> bool:
        if not self.available:
            return False
        with self.connection() as con:
            row = con.execute(
                "SELECT 1 FROM allowlist WHERE ((kind='sha256' AND value=?) OR (kind='path' AND value=?)) "
                "AND (expires_at IS NULL OR expires_at > ?) LIMIT 1",
                (sha256, path, utc_now()),
            ).fetchone()
        return row is not None

    def cache_get(self, sha256: str, cache_key: str) -> ScanResult | None:
        entry = self.cache_get_with_generation(sha256, cache_key)
        return entry[0] if entry is not None else None

    def cache_get_with_generation(self, sha256: str, cache_key: str) -> tuple[ScanResult, int] | None:
        if not self.available:
            return None
        with self.connection() as con:
            row = con.execute(
                "SELECT * FROM scan_results WHERE sha256=? AND cache_key=? AND cache_valid=1 ORDER BY id DESC LIMIT 1",
                (sha256, cache_key),
            ).fetchone()
        if row is None:
            return None
        findings = tuple(
            Finding(
                source=item["source"], name=item["name"], score=int(item["score"]),
                state=EngineState(item.get("state", EngineState.AVAILABLE.value)),
                details=dict(item.get("details") or {}),
            )
            for item in json.loads(row["findings_json"])
        )
        result = ScanResult(
            path=row["path"], sha256=row["sha256"], size=row["size"],
            verdict=Verdict(row["verdict"]), score=row["score"], action=row["action"],
            findings=findings, engine_versions=json.loads(row["versions_json"]),
            cached=True, error=row["error"],
        )
        return result, int(row["cache_generation"])

    def invalidate_cached_scan(self, sha256: str, cache_key: str) -> None:
        self._require_writable()
        with self._lock, self.connection() as con:
            con.execute("BEGIN IMMEDIATE")
            con.execute(
                "INSERT INTO scan_cache_epochs (sha256,cache_key,epoch) VALUES(?,?,1) "
                "ON CONFLICT(sha256,cache_key) DO UPDATE SET epoch=scan_cache_epochs.epoch+1",
                (sha256, cache_key),
            )
            con.execute(
                "UPDATE scan_results SET cache_valid=0, cache_generation=cache_generation+1 "
                "WHERE sha256=? AND cache_key=?",
                (sha256, cache_key),
            )

    def cache_epoch(self, sha256: str, cache_key: str) -> int:
        if not self.available:
            return 0
        with self.connection() as con:
            row = con.execute(
                "SELECT epoch FROM scan_cache_epochs WHERE sha256=? AND cache_key=?",
                (sha256, cache_key),
            ).fetchone()
        return int(row["epoch"]) if row is not None else 0

    def refresh_cached_scan(self, sha256: str, cache_key: str, generation: int, path: str) -> bool:
        self._require_writable()
        with self._lock, self.connection() as con:
            updated = con.execute(
                "UPDATE scan_results SET path=?, scanned_at=? "
                "WHERE sha256=? AND cache_key=? AND cache_valid=1 AND cache_generation=?",
                (path, utc_now(), sha256, cache_key, generation),
            )
            return updated.rowcount == 1

    def record_scan(self, result: ScanResult, cache_key: str) -> None:
        self._require_writable()
        with self._lock, self.connection() as con:
            self._write_scan_row(con, result, cache_key)
        self.record_detection_event(result)

    def record_scan_if_epoch(self, result: ScanResult, cache_key: str, expected_epoch: int) -> bool:
        self._require_writable()
        with self._lock, self.connection() as con:
            con.execute("BEGIN IMMEDIATE")
            row = con.execute(
                "SELECT epoch FROM scan_cache_epochs WHERE sha256=? AND cache_key=?",
                (result.sha256, cache_key),
            ).fetchone()
            current_epoch = int(row["epoch"]) if row is not None else 0
            if current_epoch != expected_epoch:
                return False
            self._write_scan_row(con, result, cache_key)
        self.record_detection_event(result)
        return True

    @staticmethod
    def _write_scan_row(con: sqlite3.Connection, result: ScanResult, cache_key: str) -> None:
        findings = json.dumps([item.to_dict() for item in result.findings], ensure_ascii=False, sort_keys=True)
        versions = json.dumps(result.engine_versions, ensure_ascii=False, sort_keys=True)
        con.execute(
            "INSERT INTO scan_results (path,sha256,size,verdict,score,action,findings_json,versions_json,cache_key,scanned_at,error,cache_valid,cache_generation) "
            "VALUES(?,?,?,?,?,?,?,?,?,?,?,1,1) ON CONFLICT(sha256,cache_key) DO UPDATE SET "
            "path=excluded.path,size=excluded.size,verdict=excluded.verdict,score=excluded.score,"
            "action=excluded.action,findings_json=excluded.findings_json,versions_json=excluded.versions_json,"
            "scanned_at=excluded.scanned_at,error=excluded.error,cache_valid=1,"
            "cache_generation=scan_results.cache_generation+1",
            (result.path, result.sha256, result.size, result.verdict.value, result.score,
             result.action, findings, versions, cache_key, utc_now(), result.error),
        )

    def record_detection_event(self, result: ScanResult) -> None:
        if result.verdict in {Verdict.SUSPICIOUS, Verdict.MALICIOUS, Verdict.SCAN_ERROR}:
            self.event(
                "detection",
                result.path,
                result.verdict.value,
                result.action,
                {
                    "sha256": result.sha256,
                    "score": result.score,
                    "findings": [
                        {"source": item.source, "name": item.name, "state": item.state.value}
                        for item in result.findings
                    ],
                },
            )

    def event(self, event_type: str, subject: str, verdict: str | None, action: str, details: dict[str, Any]) -> None:
        self._require_writable()
        with self._lock, self.connection() as con:
            con.execute(
                "INSERT INTO detection_events(event_type,subject,verdict,action,details_json,created_at) VALUES(?,?,?,?,?,?)",
                (event_type, subject, verdict, action, json.dumps(details, ensure_ascii=False, sort_keys=True), utc_now()),
            )

    def upsert_feed(self, name: str, version: str, status: str, details: dict[str, Any]) -> None:
        self._require_writable()
        with self._lock, self.connection() as con:
            con.execute(
                "INSERT INTO feed_state(name,version,updated_at,status,details_json) VALUES(?,?,?,?,?) "
                "ON CONFLICT(name) DO UPDATE SET version=excluded.version,updated_at=excluded.updated_at,"
                "status=excluded.status,details_json=excluded.details_json",
                (name, version, utc_now(), status, json.dumps(details, ensure_ascii=False, sort_keys=True)),
            )

    def feed_versions(self) -> dict[str, str]:
        if not self.available:
            return {}
        with self.connection() as con:
            rows = con.execute("SELECT name,version FROM feed_state ORDER BY name").fetchall()
        return {row["name"]: row["version"] for row in rows}

    def status_summary(self) -> dict[str, Any]:
        if not self.available:
            return {
                "files_scanned": 0,
                "detections": 0,
                "quarantine_count": 0,
                "last_scan": None,
                "last_signature_update": None,
            }
        with self.connection() as con:
            scans = con.execute(
                "SELECT COUNT(*) AS files_scanned, MAX(scanned_at) AS last_scan FROM scan_results"
            ).fetchone()
            detections = con.execute(
                "SELECT COUNT(*) AS count FROM scan_results WHERE verdict IN ('MALICIOUS','SUSPICIOUS')"
            ).fetchone()
            quarantine = con.execute(
                "SELECT COUNT(*) AS count FROM quarantine_items WHERE restored_at IS NULL AND deleted_at IS NULL"
            ).fetchone()
            update = con.execute(
                "SELECT MAX(updated_at) AS last_signature_update FROM feed_state WHERE status='ok'"
            ).fetchone()
        return {
            "files_scanned": int(scans["files_scanned"] or 0),
            "detections": int(detections["count"] or 0),
            "quarantine_count": int(quarantine["count"] or 0),
            "last_scan": scans["last_scan"],
            "last_signature_update": update["last_signature_update"],
        }

    def status_rows(self, table: str, limit: int = 50) -> list[dict[str, Any]]:
        allowed = {"feed_state", "quarantine_items", "detection_events"}
        if table not in allowed:
            raise ValueError("unsupported table")
        if not self.available:
            return []
        order = "created_at" if table != "feed_state" else "updated_at"
        with self.connection() as con:
            rows = con.execute(f"SELECT * FROM {table} ORDER BY {order} DESC LIMIT ?", (limit,)).fetchall()
        result = [dict(row) for row in rows]
        if table == "quarantine_items":
            for item in result:
                decode_quarantine_findings(item["findings_json"])
        return result
