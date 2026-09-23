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


def _read_bytes(path: Path) -> bytes | None:
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
    if len(data) > MAX_EVIDENCE_BYTES:
        raise ControlError('observation_too_large')
    return data


def _read_record(path: Path) -> dict | None:
    data = _read_bytes(path)
    if data is None:
        return None
    value = decode_request(data, limit=MAX_EVIDENCE_BYTES)
    if type(value) is not dict:
        raise ControlError('observation_unavailable')
    return value


def _read_lines(path: Path) -> list[dict] | None:
    data = _read_bytes(path)
    if data is None:
        return None
    if data and not data.endswith(b'\n'):
        raise ControlError('observation_changed')
    rows = []
    for line in data.splitlines():
        value = decode_request(line, limit=MAX_EVIDENCE_BYTES)
        if type(value) is not dict or len(rows) >= 128:
            raise ControlError('observation_unavailable')
        rows.append(value)
    return rows


class HermesObservations:
    workspace_bound_runs = True
    typed_verification_evidence = True

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

    @staticmethod
    def _digest(value):
        return type(value) is str and bool(re.fullmatch(r'[a-f0-9]{64}', value))

    def _manifest(self, profile_id: str, run_id: str):
        path = self._run_path(profile_id, run_id)
        manifest = _read_record(path / 'run-manifest.json')
        if manifest is None:
            return path, None
        checks = manifest.get('required_checks')
        if (manifest.get('schema_version') != 1 or manifest.get('run_id') != run_id
                or not valid_id(manifest.get('workspace_id'))
                or (manifest.get('operation_id') is not None and not re.fullmatch(
                    r'op-[a-f0-9]{32}', str(manifest['operation_id'])))
                or not self._digest(manifest.get('source_digest'))
                or not self._digest(manifest.get('route_fingerprint'))
                or type(checks) is not list or not 1 <= len(checks) <= 16
                or len(set(checks)) != len(checks)
                or any(not valid_id(check) for check in checks)):
            raise ControlError('observation_unavailable')
        return path, manifest

    def workspace_for_run(self, profile_id: str, run_id: str) -> str | None:
        """Read only the native owner manifest before any detailed run data."""
        _, manifest = self._manifest(profile_id, run_id)
        return None if manifest is None else manifest['workspace_id']

    @staticmethod
    def _terminal(path: Path, manifest: dict):
        terminal = _read_record(path / 'run-result.json')
        if terminal is None:
            return None
        if (terminal.get('schema_version') != 1
                or terminal.get('run_id') != manifest['run_id']
                or terminal.get('workspace_id') != manifest['workspace_id']
                or terminal.get('run_state') not in ('SUCCEEDED', 'FAILED', 'BLOCKED', 'CANCELLED')
                or type(terminal.get('reason')) is not str or len(terminal['reason']) > 128):
            raise ControlError('observation_unavailable')
        if terminal['run_state'] == 'SUCCEEDED' and (
                not valid_id(terminal.get('verified_attempt_id'))
                or not HermesObservations._digest(terminal.get('candidate_digest'))):
            raise ControlError('observation_unavailable')
        return terminal

    def run(self, profile_id: str, run_id: str) -> dict:
        path, manifest = self._manifest(profile_id, run_id)
        if manifest is None:
            return {'state': 'UNKNOWN' if path.is_dir() else 'ABSENT',
                    'reason': 'live_owner_not_observed' if path.is_dir() else 'run_absent'}
        terminal = self._terminal(path, manifest)
        common = {'run_id': run_id, 'workspace_id': manifest['workspace_id'],
                  'operation_id': manifest.get('operation_id'),
                  'source_digest': manifest['source_digest'],
                  'route_fingerprint': manifest['route_fingerprint'],
                  'required_checks': manifest['required_checks']}
        if terminal is None:
            return {'state': 'UNKNOWN', 'reason': 'terminal_receipt_absent', **common}
        return {'state': 'AVAILABLE', 'reason': 'native_terminal_receipt', **common,
                'run_state': terminal['run_state'], 'result_reason': terminal['reason'],
                'verified_attempt_id': terminal.get('verified_attempt_id'),
                'candidate_digest': terminal.get('candidate_digest')}

    def evidence(self, profile_id: str, run_id: str) -> dict:
        path, manifest = self._manifest(profile_id, run_id)
        if manifest is None:
            return {'state': 'UNSUPPORTED', 'reason': 'typed_evidence_not_published'}
        terminal = self._terminal(path, manifest)
        rows = _read_lines(path / 'verification.jsonl') or []
        checks = []
        for row in rows:
            if (row.get('schema_version') != 1 or row.get('evidence_type') != 'host_verifier_check'
                    or row.get('run_id') != run_id or row.get('workspace_id') != manifest['workspace_id']
                    or row.get('source_digest') != manifest['source_digest']
                    or row.get('route_fingerprint') != manifest['route_fingerprint']
                    or row.get('check_id') not in manifest['required_checks']
                    or not valid_id(row.get('attempt_id'))
                    or not self._digest(row.get('candidate_digest'))
                    or not self._digest(row.get('snapshot_before'))
                    or not self._digest(row.get('snapshot_after'))
                    or type(row.get('exit_code')) is not int
                    or type(row.get('revision')) is not int
                    or type(row.get('completed')) is not bool
                    or type(row.get('timed_out')) is not bool
                    or type(row.get('approved')) is not bool
                    or type(row.get('platform')) is not str or len(row['platform']) > 32):
                raise ControlError('observation_unavailable')
            checks.append({key: row[key] for key in (
                'attempt_id', 'revision', 'check_id', 'exit_code', 'completed',
                'timed_out', 'approved', 'snapshot_before', 'snapshot_after',
                'candidate_digest', 'platform')})
        selected = [row for row in checks if terminal and row['attempt_id'] == terminal.get('verified_attempt_id')]
        candidate = terminal.get('candidate_digest') if terminal else None
        verified = bool(terminal and terminal['run_state'] == 'SUCCEEDED'
                        and len(selected) == len(manifest['required_checks'])
                        and {row['check_id'] for row in selected} == set(manifest['required_checks'])
                        and len({row['revision'] for row in selected}) == 1
                        and all(row['completed'] and not row['timed_out'] and row['approved']
                                and row['exit_code'] == 0
                                and row['snapshot_before'] == candidate
                                and row['snapshot_after'] == candidate
                                and row['candidate_digest'] == candidate for row in selected))
        return {'state': 'AVAILABLE' if verified else 'PARTIAL',
                'reason': 'verified_host_checks' if verified else 'incomplete_evidence',
                'run_id': run_id, 'workspace_id': manifest['workspace_id'],
                'source_digest': manifest['source_digest'],
                'route_fingerprint': manifest['route_fingerprint'],
                'verified': verified, 'checks': checks}
