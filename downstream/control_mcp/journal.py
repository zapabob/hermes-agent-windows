"""Host-owned operation metadata: no scheduler and no model-supplied approvals.

Initialisation is explicit at opt-in host startup. Reads open existing data
read-only. UNKNOWN keeps its workspace reservation; external effects are never
replayed merely because a transport or process restarted.
"""
from __future__ import annotations

from contextlib import contextmanager
import json
from pathlib import Path
import re
import sqlite3
import uuid

from .contracts import ControlError, canonical_intent_digest, canonical_json, require_access, valid_id

SCOPES = {
    'start_engineering_run': 'hermes:run:start',
    'cancel_run': 'hermes:run:cancel',
    'reverify': 'hermes:run:verify',
    'patch_routes': 'hermes:config:routes',
    'apply_verified_result': 'hermes:workspace:apply',
    'create_pull_request': 'hermes:repo:pr',
    'merge_pull_request': 'hermes:repo:merge',
}
# This slice implements admission for engineering start only. Other schemas
# are not invented until their existing owner adapters are integrated.
_ADMISSION_KINDS = frozenset({'start_engineering_run'})
_TERMINAL = frozenset({'SUCCEEDED','FAILED','DENIED','EXPIRED','CONFLICT','BLOCKED'})
_EDGES = {'APPROVED': {'RUNNING','CONFLICT','BLOCKED'},
          'RUNNING': {'SUCCEEDED','FAILED','BLOCKED','UNKNOWN'}}


def _validate_request(ctx, request, now):
    if type(request) is not dict or set(request) != {
        'kind','profile_id','workspace_id','idempotency_key','expected_revision','source_sha','parameters'}:
        raise ControlError('invalid_request')
    canonical_json(request)
    kind = request['kind']
    if type(kind) is not str or kind not in _ADMISSION_KINDS:
        raise ControlError('unsupported_operation')
    require_access(ctx,scope=SCOPES[kind],profile_id=request['profile_id'],
                   workspace_id=request['workspace_id'],now=now)
    if not valid_id(request['idempotency_key']) or not valid_id(request['expected_revision']):
        raise ControlError('invalid_request')
    if type(request['source_sha']) is not str or not re.fullmatch('[a-f0-9]{40}',request['source_sha']):
        raise ControlError('invalid_request')
    params = request['parameters']
    if (type(params) is not dict or set(params) != {'task'} or type(params['task']) is not str
            or not params['task'].strip() or len(params['task']) > 16000):
        raise ControlError('invalid_request')
    return canonical_intent_digest(request)


def _public(row):
    return {key:row[key] for key in ('operation_id','profile_id','workspace_id','kind','state',
                                     'intent_digest','expected_revision','source_sha','expires_at')}


class HostControlJournal:
    def __init__(self,path:Path):
        self.path=Path(path)
        if not self.path.is_absolute():
            raise ControlError('invalid_host_configuration')

    @contextmanager
    def _connection(self,*,readonly=False):
        # URI quoting via as_uri preserves spaces and rejects parameter injection.
        uri=self.path.as_uri()+('?mode=ro' if readonly else '?mode=rw')
        try:
            conn=sqlite3.connect(uri,uri=True,timeout=5,isolation_level=None)
        except sqlite3.Error:
            raise ControlError('journal_unavailable') from None
        conn.row_factory=sqlite3.Row
        try:
            conn.execute('PRAGMA foreign_keys=ON')
            yield conn
        finally:
            conn.close()

    @contextmanager
    def _transaction(self):
        with self._connection() as conn:
            conn.execute('BEGIN IMMEDIATE')
            try:
                yield conn
                conn.execute('COMMIT')
            except BaseException:
                conn.execute('ROLLBACK')
                raise

    def initialise(self):
        """Called explicitly by approved host startup, never by a read tool."""
        self.path.parent.mkdir(parents=True,exist_ok=True)
        conn=sqlite3.connect(self.path)
        try:
            version=conn.execute('PRAGMA user_version').fetchone()[0]
            if version not in (0,1):
                raise ControlError('unsupported_journal_version')
            conn.executescript('''
                PRAGMA journal_mode=DELETE;
                PRAGMA foreign_keys=ON;
                CREATE TABLE IF NOT EXISTS control_operations (
                    operation_id TEXT PRIMARY KEY,
                    subject TEXT NOT NULL, client_registration TEXT NOT NULL,
                    resource TEXT NOT NULL, grant_revision INTEGER NOT NULL,
                    idempotency_key TEXT NOT NULL,
                    profile_id TEXT NOT NULL, workspace_id TEXT NOT NULL,
                    kind TEXT NOT NULL, intent_digest TEXT NOT NULL,
                    request_json TEXT NOT NULL, expected_revision TEXT NOT NULL,
                    source_sha TEXT NOT NULL, expires_at INTEGER NOT NULL,
                    state TEXT NOT NULL, updated_at REAL NOT NULL,
                    UNIQUE(subject,client_registration,idempotency_key)
                );
                CREATE TABLE IF NOT EXISTS control_reservations (
                    profile_id TEXT NOT NULL, workspace_id TEXT NOT NULL,
                    operation_id TEXT NOT NULL REFERENCES control_operations(operation_id),
                    PRIMARY KEY(profile_id,workspace_id)
                );
                PRAGMA user_version=1;
            ''')
            conn.commit()
        finally:
            conn.close()

    def reserve(self,ctx,request,*,now):
        fingerprint=_validate_request(ctx,request,now)
        with self._transaction() as conn:
            old=conn.execute('SELECT * FROM control_operations WHERE subject=? AND client_registration=? AND idempotency_key=?',
                             (ctx.subject,ctx.client_registration,request['idempotency_key'])).fetchone()
            if old is not None:
                if old['intent_digest']!=fingerprint or old['resource']!=ctx.resource:
                    raise ControlError('idempotency_conflict')
                return _public(old)
            # Only provably unexecuted expired intents are released here.
            expired=conn.execute("SELECT operation_id FROM control_operations WHERE state='PENDING_APPROVAL' AND expires_at<=?",(now,)).fetchall()
            for row in expired:
                conn.execute("UPDATE control_operations SET state='EXPIRED',updated_at=? WHERE operation_id=?",(now,row[0]))
                conn.execute('DELETE FROM control_reservations WHERE operation_id=?',(row[0],))
            if conn.execute('SELECT 1 FROM control_reservations WHERE profile_id=? AND workspace_id=?',
                            (request['profile_id'],request['workspace_id'])).fetchone():
                raise ControlError('workspace_busy')
            op='op-'+uuid.uuid4().hex
            deadline=min(ctx.expires_at,int(now)+600)
            conn.execute('INSERT INTO control_operations VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)',
                         (op,ctx.subject,ctx.client_registration,ctx.resource,ctx.grant_revision,
                          request['idempotency_key'],request['profile_id'],request['workspace_id'],request['kind'],
                          fingerprint,canonical_json(request).decode(),request['expected_revision'],
                          request['source_sha'],deadline,'PENDING_APPROVAL',now))
            conn.execute('INSERT INTO control_reservations VALUES (?,?,?)',
                         (request['profile_id'],request['workspace_id'],op))
            return _public(conn.execute('SELECT * FROM control_operations WHERE operation_id=?',(op,)).fetchone())

    def get(self,ctx,operation_id,*,profile_id,workspace_id,now):
        require_access(ctx,scope='hermes:read',profile_id=profile_id,workspace_id=workspace_id,now=now)
        if not valid_id(operation_id):
            raise ControlError('invalid_resource_id')
        if not self.path.exists():
            return {'state':'ABSENT','reason':'journal_absent'}
        with self._connection(readonly=True) as conn:
            row=conn.execute('SELECT * FROM control_operations WHERE operation_id=?',(operation_id,)).fetchone()
            if row is None:
                return {'state':'ABSENT','reason':'operation_absent'}
            if row['profile_id']!=profile_id or row['workspace_id']!=workspace_id or row['resource']!=ctx.resource:
                raise ControlError('resource_denied')
            return _public(row)

    def _owned(self,conn,ctx,operation_id,now):
        row=conn.execute('SELECT * FROM control_operations WHERE operation_id=?',(operation_id,)).fetchone()
        if row is None:
            raise ControlError('resource_denied')
        require_access(ctx,scope=SCOPES[row['kind']],profile_id=row['profile_id'],workspace_id=row['workspace_id'],now=now)
        if (row['subject']!=ctx.subject or row['client_registration']!=ctx.client_registration
                or row['resource']!=ctx.resource or row['grant_revision']!=ctx.grant_revision):
            raise ControlError('resource_denied')
        if row['expires_at']<=now or row['state']!='PENDING_APPROVAL':
            raise ControlError('approval_conflict')
        return row

    @staticmethod
    def _binding(row):
        from tools.approval import ControlApprovalBinding
        request=json.loads(row['request_json'])
        description=(f"{row['kind']} in {row['workspace_id']}; source {row['source_sha']}; "
                     f"expected revision {row['expected_revision']}. Task: "
                     +request['parameters']['task'][:2500])
        return ControlApprovalBinding(operation_id=row['operation_id'],intent_digest=row['intent_digest'],
            subject=row['subject'],client_registration=row['client_registration'],profile_id=row['profile_id'],
            workspace_id=row['workspace_id'],expires_at=row['expires_at'],description=description)

    def approval_binding(self,ctx,operation_id,*,now):
        with self._connection(readonly=True) as conn:
            return self._binding(self._owned(conn,ctx,operation_id,now))

    def approve(self,ctx,operation_id,decision,*,now):
        from tools.approval import consume_control_verdict
        with self._transaction() as conn:
            row=self._owned(conn,ctx,operation_id,now)
            verdict = consume_control_verdict(decision,self._binding(row),now=now)
            if verdict is None:
                raise ControlError('approval_required')
            state = 'APPROVED' if verdict == 'once' else 'DENIED'
            conn.execute("UPDATE control_operations SET state=?,updated_at=? WHERE operation_id=?",(state,now,operation_id))
            if state == 'DENIED':
                conn.execute('DELETE FROM control_reservations WHERE operation_id=?',(operation_id,))
            return _public(conn.execute('SELECT * FROM control_operations WHERE operation_id=?',(operation_id,)).fetchone())

    def transition(self,operation_id,*,expected_state,new_state,now):
        """Trusted host execution only; not an exported tool or arbitrary setter."""
        if new_state not in _EDGES.get(expected_state,set()):
            raise ControlError('invalid_transition')
        with self._transaction() as conn:
            row=conn.execute('SELECT * FROM control_operations WHERE operation_id=?',(operation_id,)).fetchone()
            if row is None or row['state']!=expected_state:
                raise ControlError('operation_conflict')
            if expected_state=='APPROVED' and now>=row['expires_at']:
                raise ControlError('expired_approval')
            conn.execute('UPDATE control_operations SET state=?,updated_at=? WHERE operation_id=?',(new_state,now,operation_id))
            if new_state in _TERMINAL:
                conn.execute('DELETE FROM control_reservations WHERE operation_id=?',(operation_id,))

    def recover_after_restart(self,*,now):
        """Single live host calls this on startup, never a transport reconnect."""
        with self._transaction() as conn:
            # APPROVED must get a new decision after host epoch changes. Keep
            # every reservation until the owner reconciles/denies explicitly.
            conn.execute("UPDATE control_operations SET state='UNKNOWN',updated_at=? WHERE state IN ('APPROVED','RUNNING')",(now,))
