"""Non-creating reads of host-selected sources. No live execution is inferred.

Host metadata paths are registered in-process, never accepted over MCP. The
running host and its filesystem are trusted. Reparse checks are defence in
 depth, not a sandbox against concurrent same-user directory replacement.
"""
from __future__ import annotations

import os
from pathlib import Path
import re
import stat

from .contracts import ControlError, MAX_EVIDENCE_BYTES, decode_request, valid_id
from .projection import project_routes

_RUN = re.compile(r'eng-[a-f0-9]{32}\Z')


def _safe_path(path: Path) -> bool:
    """Reject links/reparse points anywhere along a fixed, host-issued path."""
    for part in (*reversed(path.parents), path):
        try:
            st = part.lstat()
        except FileNotFoundError:
            return False
        if stat.S_ISLNK(st.st_mode) or getattr(st, 'st_file_attributes', 0) & 0x400:
            raise ControlError('unsafe_evidence_path')
    return True


def _read_record(path: Path) -> dict | None:
    if not _safe_path(path):
        return None
    before = path.lstat()
    if not stat.S_ISREG(before.st_mode) or before.st_nlink != 1:
        raise ControlError('unsafe_evidence_path')
    flags = os.O_RDONLY | getattr(os, 'O_NOFOLLOW', 0) | getattr(os, 'O_BINARY', 0)
    fd = os.open(path, flags)
    with os.fdopen(fd, 'rb') as stream:
        opened = os.fstat(stream.fileno())
        if (opened.st_dev, opened.st_ino) != (before.st_dev, before.st_ino):
            raise ControlError('unsafe_evidence_path')
        data = stream.read(MAX_EVIDENCE_BYTES + 1)
        after = os.fstat(stream.fileno())
        if (opened.st_size, opened.st_mtime_ns) != (after.st_size, after.st_mtime_ns):
            raise ControlError('observation_changed')
    return decode_request(data, limit=MAX_EVIDENCE_BYTES)


class HermesObservations:
    """Profile-home registry supplied by the existing trusted parent host.

    This adapter reads persisted gateway state and an already-loaded effective
    configuration snapshot. It does NOT claim to have observed engineering
    lifecycle/receipts which the older producer does not persist.
    """

    def __init__(self, *, homes: dict[str, Path], registered_slots: tuple[str, ...]):
        if any(not valid_id(k) or not Path(v).is_absolute() for k, v in homes.items()):
            raise ControlError('invalid_host_configuration')
        self._homes = {k: Path(v) for k, v in homes.items()}
        self._slots = tuple(registered_slots)

    def _home(self, profile_id: str) -> Path:
        if profile_id not in self._homes:
            raise ControlError('resource_denied')
        return self._homes[profile_id]

    def routes(self, profile_id: str) -> dict:
        from hermes_cli.config import peek_effective_config

        cfg = peek_effective_config(self._home(profile_id) / 'config.yaml')
        if cfg is None:
            return {'state': 'UNKNOWN', 'reason': 'config_not_observed', 'routes': None}
        return {'state': 'AVAILABLE', 'reason': 'configured_routes',
                'routes': project_routes(cfg, slots=self._slots),
                'request_sent_routes': None, 'provider_reported_routes': None}

    def runtime(self, profile_id: str) -> dict:
        from gateway.status import runtime_status_is_stale

        try:
            record = _read_record(self._home(profile_id) / 'gateway_state.json')
        except (OSError, ControlError):
            return {'state': 'UNKNOWN', 'reason': 'status_unreadable'}
        if record is None:
            return {'state': 'ABSENT', 'reason': 'status_absent'}
        timestamp = record.get('updated_at')
        if type(timestamp) is not str or len(timestamp) > 64:
            timestamp = None
        return {'state': 'STALE' if runtime_status_is_stale(record) else 'AVAILABLE',
                'reason': 'persisted_status_only', 'producer_observed_at': timestamp,
                'process_ownership': 'UNKNOWN', 'security_health': 'UNKNOWN',
                'docker_health': 'UNKNOWN', 'credential_health': 'UNKNOWN'}

    def _run_path(self, profile_id: str, run_id: str) -> Path:
        if type(run_id) is not str or not _RUN.fullmatch(run_id):
            raise ControlError('invalid_resource_id')
        path = self._home(profile_id) / 'plugin-data' / 'implementation_router' / run_id
        _safe_path(path)
        return path

    def run(self, profile_id: str, run_id: str) -> dict:
        path = self._run_path(profile_id, run_id)
        return {'state': 'UNKNOWN' if path.is_dir() else 'ABSENT',
                'reason': 'live_owner_not_observed', 'run_id': run_id}

    def evidence(self, profile_id: str, run_id: str) -> dict:
        self._run_path(profile_id, run_id)
        # Legacy events/receipt digests do not persist the complete verifier
        # evidence required here. Do not export them as test successes.
        return {'state': 'UNSUPPORTED', 'reason': 'typed_evidence_not_published'}
