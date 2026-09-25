"""Host-owned operation metadata: no scheduler and no model-supplied approvals.

Initialisation is explicit at opt-in host startup and opens the single owner
epoch (F01_AUTHORITY_CONTRACT.md). Reads open existing data read-only. UNKNOWN
keeps its workspace reservation; external effects are never replayed merely
because a transport or process restarted.
"""
from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path
import re
import sqlite3
import time
import uuid

from hermes_cli.config import load_config_readonly
from plugins.implementation_router.configuration import picker_routes

from .contracts import ControlError, canonical_intent_digest, canonical_json, require_access, valid_id

if os.name == 'nt':
    import msvcrt
else:
    import fcntl

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
# APPROVED -> RUNNING exists only inside claim_approved, after binding and fence checks.
_EDGES = {'APPROVED': {'CONFLICT','BLOCKED'},
          'RUNNING': {'SUCCEEDED','FAILED','BLOCKED','UNKNOWN'}}
_SCHEMA_VERSION = 3
# Outcomes a retry may be answered with; UNKNOWN never carries a result.
_RESULT_STATES = frozenset({'SUCCEEDED', 'FAILED', 'BLOCKED'})
_RESULT_CODE = re.compile(r'[a-z][a-z0-9_]{0,79}\Z')
_APPROVAL_CHOICES = ('once', 'deny')
_APPROVAL_TIMEOUT_BOUNDS = (1, 600)
_PREVIEW_CHARS = 2500
_PRESENTATION_LIMIT = 65_536
_OWNER_LOCK_OFFSET = 1 << 30
_REVISION_COLUMNS = (('policy_revision', 'stale_policy'), ('tool_revision', 'stale_tool'),
                     ('route_revision', 'stale_route'), ('provider_revision', 'stale_provider'))


@dataclass(frozen=True)
class KindContract:
    """Authority inputs one admitted kind binds at approval time."""
    schema_version: int
    policy_version: int
    tool_contract: str
    effect_summary: str
    route_sensitive: bool = False
    effect_route_class: str = ''
    provider_sensitive: bool = False


_KIND_CONTRACTS = {
    'start_engineering_run': KindContract(
        schema_version=1, policy_version=1, tool_contract='start_engineering_run@1',
        effect_summary=('Run one bounded engineering task in an isolated scratch workspace; '
                        'nothing is applied to the destination by this operation.'),
        route_sensitive=True, effect_route_class='code_producing_delegate'),
}


# config.yaml settings of each kind's effect owner that decide whether the kind
# may be admitted and approved. Read exactly as the owner's plugin context
# reads them (settings, then the legacy config subtree), in the active profile.
_POLICY_CONFIG_KEYS = {
    'start_engineering_run': ('implementation_router', ('enabled', 'workspaces')),
}


def _owner_setting(config, plugin_id, key):
    plugins = config.get('plugins') if isinstance(config, dict) else None
    entries = plugins.get('entries') if isinstance(plugins, dict) else None
    entry = entries.get(plugin_id) if isinstance(entries, dict) else None
    if not isinstance(entry, dict):
        return None
    for subtree in ('settings', 'config'):
        values = entry.get(subtree)
        if isinstance(values, dict) and key in values:
            return values[key]
    return None


def _policy_config(kind):
    plugin_id, keys = _POLICY_CONFIG_KEYS.get(kind, ('', ()))
    if not keys:
        return {}
    try:
        config = load_config_readonly() or {}
    except Exception:
        # An unreadable configuration must deny with a code, never crash a worker.
        raise ControlError('policy_unavailable') from None
    return {key: _owner_setting(config, plugin_id, key) for key in keys}


def _engineering_route_state():
    # A code-producing delegate exists only while every engineering slot is
    # selected in the native picker. Model ids stay outside the revision.
    try:
        picker_routes(load_config_readonly() or {})
    except Exception:
        # Malformed or unreadable configuration means no route, never a crash.
        return {}
    return {'effect_route_class': 'code_producing_delegate'}


_ROUTE_RESOLVERS = {'start_engineering_run': _engineering_route_state}


def current_route_state(kind):
    """Semantic route facts the host resolves live for an admitted kind."""
    resolver = _ROUTE_RESOLVERS.get(kind)
    return resolver() if resolver is not None else {}


def _digest(payload):
    return hashlib.sha256(canonical_json(payload)).hexdigest()


def route_binding(contract, route_state):
    """(route_revision, provider_revision) from semantic fields only.

    Catalogue timestamps, prices and model lists are ignored so a refresh that
    changes nothing an approver judged keeps the approval valid.
    """
    route = provider = ''
    if contract.route_sensitive:
        route_class = route_state.get('effect_route_class')
        if type(route_class) is not str or not valid_id(route_class):
            raise ControlError('route_unavailable')
        route = _digest({'effect_route_class': route_class})
    if contract.provider_sensitive:
        provider_id = route_state.get('provider_id')
        adapter = route_state.get('provider_adapter_contract')
        if not (type(provider_id) is str and valid_id(provider_id)
                and type(adapter) is str and valid_id(adapter)):
            raise ControlError('route_unavailable')
        provider = f'{provider_id}@{adapter}'
    return route, provider


def _current_revisions(kind):
    contract = _KIND_CONTRACTS.get(kind)
    if contract is None:
        raise ControlError('unsupported_operation')
    try:
        policy = _digest({'kind': kind, 'scope': SCOPES[kind], 'schema_version': contract.schema_version,
                          'policy_version': contract.policy_version, 'choices': list(_APPROVAL_CHOICES),
                          'timeout_bounds': list(_APPROVAL_TIMEOUT_BOUNDS),
                          'config': _policy_config(kind)})
    except ControlError:
        raise ControlError('policy_unavailable') from None
    route_state = current_route_state(kind)
    route, provider = route_binding(contract, route_state)
    return {'policy_revision': policy, 'tool_revision': contract.tool_contract,
            'route_revision': route, 'provider_revision': provider,
            'route_effect_class': route_state['effect_route_class'] if contract.route_sensitive else ''}


def approval_presentation(row):
    """Pure projection of the authority row; the UI renders exactly this."""
    contract = _KIND_CONTRACTS.get(row['kind'])
    if contract is None:
        raise ControlError('unsupported_operation')
    request = json.loads(row['request_json'])
    return {'operation_id': row['operation_id'], 'kind': row['kind'],
            'effect_summary': contract.effect_summary,
            'subject': row['subject'], 'client_registration': row['client_registration'],
            'resource': row['resource'], 'grant_revision': row['grant_revision'],
            'profile_id': row['profile_id'], 'workspace_id': row['workspace_id'],
            'expected_revision': row['expected_revision'], 'source_sha': row['source_sha'],
            'task': request['parameters']['task'],
            'policy_revision': row['policy_revision'], 'tool_revision': row['tool_revision'],
            'route_effect_class': row['route_effect_class'],
            'route_revision': row['route_revision'], 'provider_revision': row['provider_revision'],
            'owner_epoch': row['owner_epoch'], 'expires_at': row['expires_at']}


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
    public = {key:row[key] for key in ('operation_id','profile_id','workspace_id','kind','state',
                                       'intent_digest','expected_revision','source_sha','expires_at')}
    if 'result_json' in row.keys() and row['result_json'] is not None:
        public['result'] = json.loads(row['result_json'])
    return public


def _count(value):
    return type(value) is int and 0 <= value <= 2**31


_RESULT_FIELDS = {
    'run_id': valid_id,
    'reason_code': lambda value: type(value) is str and _RESULT_CODE.fullmatch(value) is not None,
    'stage_calls': _count,
    'revision': _count,
}


def _result_json(state, result):
    """The durable answer to a retry: identity and stable codes only.

    Readable by any hermes:read principal, so host paths and diagnostics are
    never stored; an invalid field is dropped rather than blocking the state.
    """
    kept = {'state': state}
    if type(result) is dict:
        for key, valid in _RESULT_FIELDS.items():
            if key in result and (key == 'run_id' or result.get('state') == state) and valid(result[key]):
                kept[key] = result[key]
    return canonical_json(kept).decode('utf-8')


_V1_STATEMENTS = (
    '''CREATE TABLE IF NOT EXISTS control_operations (
        operation_id TEXT PRIMARY KEY,
        subject TEXT NOT NULL, client_registration TEXT NOT NULL,
        resource TEXT NOT NULL, grant_revision INTEGER NOT NULL,
        idempotency_key TEXT NOT NULL,
        profile_id TEXT NOT NULL, workspace_id TEXT NOT NULL,
        kind TEXT NOT NULL, intent_digest TEXT NOT NULL,
        request_json TEXT NOT NULL, expected_revision TEXT NOT NULL,
        source_sha TEXT NOT NULL, expires_at INTEGER NOT NULL,
        state TEXT NOT NULL, updated_at REAL NOT NULL,
        UNIQUE(subject,client_registration,idempotency_key))''',
    '''CREATE TABLE IF NOT EXISTS control_reservations (
        profile_id TEXT NOT NULL, workspace_id TEXT NOT NULL,
        operation_id TEXT NOT NULL REFERENCES control_operations(operation_id),
        PRIMARY KEY(profile_id,workspace_id))''',
)
# v1 rows keep NULL authority columns; NULL never equals a live epoch or revision.
_V2_STATEMENTS = tuple(
    f'ALTER TABLE control_operations ADD COLUMN {column} TEXT'
    for column in ('policy_revision', 'tool_revision', 'route_revision', 'provider_revision',
                   'route_effect_class', 'owner_epoch', 'approved_epoch')
) + (
    '''CREATE TABLE control_owner_epochs (
        generation INTEGER PRIMARY KEY AUTOINCREMENT,
        epoch_id TEXT NOT NULL UNIQUE,
        opened_at REAL NOT NULL, closed_at REAL,
        owner_pid INTEGER NOT NULL, close_reason TEXT)''',
    '''CREATE UNIQUE INDEX control_one_open_epoch
        ON control_owner_epochs((closed_at IS NULL)) WHERE closed_at IS NULL''',
)
# The recorded outcome is the only replay cache: it commits with the terminal state.
_V3_STATEMENTS = ('ALTER TABLE control_operations ADD COLUMN result_json TEXT',)


class HostControlJournal:
    def __init__(self,path:Path):
        self.path=Path(path)
        if not self.path.is_absolute():
            raise ControlError('invalid_host_configuration')
        self._lock_path=self.path.with_name(self.path.name+'.owner.lock')
        self._owner_lock=None
        self._epoch_id=None

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

    def _acquire_owner_lock(self):
        # Held until close() or process exit; the OS drops it when the owner dies,
        # so acquiring it proves no earlier owner of this journal is still alive.
        handle=open(self._lock_path,'a+b')
        try:
            if os.name=='nt':
                # Windows byte locks are mandatory; lock past EOF so reading the file stays possible.
                handle.seek(_OWNER_LOCK_OFFSET)
                msvcrt.locking(handle.fileno(),msvcrt.LK_NBLCK,1)
            else:
                fcntl.flock(handle.fileno(),fcntl.LOCK_EX|fcntl.LOCK_NB)
        except OSError:
            handle.close()
            raise ControlError('owner_epoch_busy') from None
        self._owner_lock=handle

    def _release_owner_lock(self):
        handle,self._owner_lock=self._owner_lock,None
        if handle is None:
            return
        try:
            if os.name=='nt':
                handle.seek(_OWNER_LOCK_OFFSET)
                msvcrt.locking(handle.fileno(),msvcrt.LK_UNLCK,1)
            else:
                fcntl.flock(handle.fileno(),fcntl.LOCK_UN)
        except OSError:
            pass  # closing the handle below releases the lock regardless
        finally:
            handle.close()

    def initialise(self,*,now=None):
        """Approved host startup only: schema, owner lock, new epoch, reconcile."""
        if self._epoch_id is not None:
            return self._epoch_id
        stamp=time.time() if now is None else now
        self.path.parent.mkdir(parents=True,exist_ok=True)
        self._acquire_owner_lock()
        try:
            epoch=uuid.uuid4().hex
            conn=sqlite3.connect(self.path,isolation_level=None)
            try:
                conn.execute('PRAGMA journal_mode=DELETE')
                conn.execute('PRAGMA foreign_keys=ON')
                conn.execute('BEGIN IMMEDIATE')
                try:
                    version=conn.execute('PRAGMA user_version').fetchone()[0]
                    if version not in (0,1,2,_SCHEMA_VERSION):
                        raise ControlError('unsupported_journal_version')
                    for statement in ((_V1_STATEMENTS if version<1 else ())
                                      +(_V2_STATEMENTS if version<2 else ())
                                      +(_V3_STATEMENTS if version<3 else ())):
                        conn.execute(statement)
                    conn.execute(f'PRAGMA user_version={_SCHEMA_VERSION}')
                    conn.execute("UPDATE control_owner_epochs SET closed_at=?,close_reason='restart' WHERE closed_at IS NULL",(stamp,))
                    conn.execute('INSERT INTO control_owner_epochs(epoch_id,opened_at,owner_pid) VALUES (?,?,?)',
                                 (epoch,stamp,os.getpid()))
                    self._reconcile_previous_epochs(conn,stamp)
                    conn.execute('COMMIT')
                except BaseException:
                    conn.execute('ROLLBACK')
                    raise
            finally:
                conn.close()
        except BaseException:
            self._release_owner_lock()
            raise
        self._epoch_id=epoch
        return epoch

    @staticmethod
    def _reconcile_previous_epochs(conn,now):
        # Runs in the epoch-opening transaction, so every existing row belongs to
        # an earlier (or legacy, epoch-less) owner. Nothing is re-executed.
        released=[row[0] for row in conn.execute(
            "SELECT operation_id FROM control_operations WHERE state IN ('PENDING_APPROVAL','APPROVED')")]
        conn.execute("UPDATE control_operations SET state='BLOCKED',updated_at=? WHERE state IN ('PENDING_APPROVAL','APPROVED')",(now,))
        conn.executemany('DELETE FROM control_reservations WHERE operation_id=?',[(op,) for op in released])
        # An incomplete effect may have crossed its boundary: UNKNOWN, reservation held.
        conn.execute("UPDATE control_operations SET state='UNKNOWN',updated_at=? WHERE state='RUNNING'",(now,))

    def close(self,*,now=None):
        """Host shutdown: close this epoch and release the owner lock."""
        epoch,self._epoch_id=self._epoch_id,None
        if epoch is None:
            return
        stamp=time.time() if now is None else now
        try:
            with self._transaction() as conn:
                conn.execute("UPDATE control_owner_epochs SET closed_at=?,close_reason='shutdown' WHERE epoch_id=? AND closed_at IS NULL",
                             (stamp,epoch))
        finally:
            self._release_owner_lock()

    def _require_epoch(self,conn):
        if self._epoch_id is None:
            raise ControlError('owner_epoch_required')
        row=conn.execute('SELECT epoch_id FROM control_owner_epochs WHERE closed_at IS NULL').fetchone()
        if row is None or row[0]!=self._epoch_id:
            raise ControlError('stale_owner_epoch')

    def _check_authority(self,row,*,epoch_column):
        if row[epoch_column] is None or row[epoch_column]!=self._epoch_id:
            raise ControlError('stale_owner_epoch')
        current=_current_revisions(row['kind'])
        for column,code in _REVISION_COLUMNS:
            if row[column]!=current[column]:
                raise ControlError(code)

    def reserve(self,ctx,request,*,now,with_created=False):
        fingerprint=_validate_request(ctx,request,now)
        with self._transaction() as conn:
            self._require_epoch(conn)
            old=conn.execute('SELECT * FROM control_operations WHERE subject=? AND client_registration=? AND idempotency_key=?',
                             (ctx.subject,ctx.client_registration,request['idempotency_key'])).fetchone()
            if old is not None:
                if (old['intent_digest']!=fingerprint or old['resource']!=ctx.resource
                        or old['grant_revision']!=ctx.grant_revision):
                    raise ControlError('idempotency_conflict')
                if old['state']=='PENDING_APPROVAL' and old['expires_at']<=now:
                    conn.execute("UPDATE control_operations SET state='EXPIRED',updated_at=? WHERE operation_id=?",(now,old['operation_id']))
                    conn.execute('DELETE FROM control_reservations WHERE operation_id=?',(old['operation_id'],))
                    old=conn.execute('SELECT * FROM control_operations WHERE operation_id=?',(old['operation_id'],)).fetchone()
                public = _public(old)
                return (public, False) if with_created else public
            # Only provably unexecuted expired intents are released here.
            expired=conn.execute("SELECT operation_id FROM control_operations WHERE state='PENDING_APPROVAL' AND expires_at<=?",(now,)).fetchall()
            for row in expired:
                conn.execute("UPDATE control_operations SET state='EXPIRED',updated_at=? WHERE operation_id=?",(now,row[0]))
                conn.execute('DELETE FROM control_reservations WHERE operation_id=?',(row[0],))
            if conn.execute('SELECT 1 FROM control_reservations WHERE profile_id=? AND workspace_id=?',
                            (request['profile_id'],request['workspace_id'])).fetchone():
                raise ControlError('workspace_busy')
            revisions=_current_revisions(request['kind'])
            op='op-'+uuid.uuid4().hex
            deadline=min(ctx.expires_at,int(now)+600)
            conn.execute('''INSERT INTO control_operations (
                    operation_id,subject,client_registration,resource,grant_revision,idempotency_key,
                    profile_id,workspace_id,kind,intent_digest,request_json,expected_revision,source_sha,
                    expires_at,state,updated_at,policy_revision,tool_revision,route_revision,
                    provider_revision,route_effect_class,owner_epoch,approved_epoch)
                    VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,NULL)''',
                         (op,ctx.subject,ctx.client_registration,ctx.resource,ctx.grant_revision,
                          request['idempotency_key'],request['profile_id'],request['workspace_id'],request['kind'],
                          fingerprint,canonical_json(request).decode(),request['expected_revision'],
                          request['source_sha'],deadline,'PENDING_APPROVAL',now,
                          revisions['policy_revision'],revisions['tool_revision'],revisions['route_revision'],
                          revisions['provider_revision'],revisions['route_effect_class'],self._epoch_id))
            conn.execute('INSERT INTO control_reservations VALUES (?,?,?)',
                         (request['profile_id'],request['workspace_id'],op))
            public = _public(conn.execute('SELECT * FROM control_operations WHERE operation_id=?',(op,)).fetchone())
            return (public, True) if with_created else public

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
            if (row['profile_id']!=profile_id or row['workspace_id']!=workspace_id
                    or row['resource']!=ctx.resource or row['subject']!=ctx.subject
                    or row['client_registration']!=ctx.client_registration
                    or row['grant_revision']!=ctx.grant_revision):
                raise ControlError('resource_denied')
            return _public(row)

    def _owned(self,conn,ctx,operation_id,now,*,check_authority=True):
        self._require_epoch(conn)
        row=conn.execute('SELECT * FROM control_operations WHERE operation_id=?',(operation_id,)).fetchone()
        if row is None:
            raise ControlError('resource_denied')
        require_access(ctx,scope=SCOPES[row['kind']],profile_id=row['profile_id'],workspace_id=row['workspace_id'],now=now)
        if (row['subject']!=ctx.subject or row['client_registration']!=ctx.client_registration
                or row['resource']!=ctx.resource or row['grant_revision']!=ctx.grant_revision):
            raise ControlError('resource_denied')
        if row['expires_at']<=now or row['state']!='PENDING_APPROVAL':
            raise ControlError('approval_conflict')
        if check_authority:
            self._check_authority(row,epoch_column='owner_epoch')
        return row

    @staticmethod
    def _binding(row):
        from tools.approval import ControlApprovalBinding
        presentation=approval_presentation(row)
        presentation_json=canonical_json(presentation,limit=_PRESENTATION_LIMIT).decode('utf-8')
        task=presentation['task']
        preview=task[:_PREVIEW_CHARS]
        if len(task)>_PREVIEW_CHARS:
            # Display bound only; authority is the full presentation and its digest.
            preview+=f' ... [truncated preview of {len(task)} chars; the full task is in the approval presentation]'
        description=(f"{row['kind']} for resource {row['resource']} "
                     f"(grant revision {row['grant_revision']}) in {row['workspace_id']}; "
                     f"source {row['source_sha']}; "
                     f"expected revision {row['expected_revision']}. Task: "
                     +preview)
        return ControlApprovalBinding(operation_id=row['operation_id'],intent_digest=row['intent_digest'],
            subject=row['subject'],client_registration=row['client_registration'],
            resource=row['resource'],grant_revision=row['grant_revision'],
            profile_id=row['profile_id'],workspace_id=row['workspace_id'],
            expires_at=row['expires_at'],description=description,
            owner_epoch=row['owner_epoch'],policy_revision=row['policy_revision'],
            tool_revision=row['tool_revision'],route_revision=row['route_revision'],
            provider_revision=row['provider_revision'],presentation_json=presentation_json,
            presentation_digest=hashlib.sha256(presentation_json.encode('utf-8')).hexdigest())

    def approval_binding(self,ctx,operation_id,*,now):
        with self._connection(readonly=True) as conn:
            return self._binding(self._owned(conn,ctx,operation_id,now))

    def _repeated_denial(self,conn,ctx,operation_id,decision,now):
        """A duplicated deny for this exact operation answers DENIED without a transition."""
        from tools.approval import ControlDecision
        self._require_epoch(conn)
        row=conn.execute('SELECT * FROM control_operations WHERE operation_id=?',(operation_id,)).fetchone()
        if (row is None or row['state']!='DENIED' or type(decision) is not ControlDecision
                or decision.choice!='deny' or decision.binding.operation_id!=operation_id):
            return None
        require_access(ctx,scope=SCOPES[row['kind']],profile_id=row['profile_id'],workspace_id=row['workspace_id'],now=now)
        if (row['subject']!=ctx.subject or row['client_registration']!=ctx.client_registration
                or row['resource']!=ctx.resource or row['grant_revision']!=ctx.grant_revision):
            raise ControlError('resource_denied')
        if decision.binding!=self._binding(row):
            raise ControlError('approval_required')
        return _public(row)

    def approve(self,ctx,operation_id,decision,*,now):
        from tools.approval import consume_control_verdict
        with self._transaction() as conn:
            repeated=self._repeated_denial(conn,ctx,operation_id,decision,now)
            if repeated is not None:
                return repeated
            row=self._owned(conn,ctx,operation_id,now)
            verdict = consume_control_verdict(decision,self._binding(row),now=now)
            if verdict is None:
                raise ControlError('approval_required')
            if verdict == 'once':
                conn.execute("UPDATE control_operations SET state='APPROVED',approved_epoch=?,updated_at=? WHERE operation_id=?",
                             (self._epoch_id,now,operation_id))
            else:
                conn.execute("UPDATE control_operations SET state='DENIED',updated_at=? WHERE operation_id=?",(now,operation_id))
                conn.execute('DELETE FROM control_reservations WHERE operation_id=?',(operation_id,))
            return _public(conn.execute('SELECT * FROM control_operations WHERE operation_id=?',(operation_id,)).fetchone())

    def expire_pending(self, operation_id, *, now):
        """Close a timed-out human window without touching any running effect."""
        with self._transaction() as conn:
            self._require_epoch(conn)
            row = conn.execute('SELECT state FROM control_operations WHERE operation_id=?',
                               (operation_id,)).fetchone()
            if row is None or row['state'] != 'PENDING_APPROVAL':
                return False
            conn.execute("UPDATE control_operations SET state='EXPIRED',updated_at=? WHERE operation_id=?",
                         (now, operation_id))
            conn.execute('DELETE FROM control_reservations WHERE operation_id=?', (operation_id,))
            return True

    def block_unexecuted(self, operation_id, *, now):
        """Trusted host closes a revoked intent only before native execution.

        Outcome evidence only: checks the owner epoch, never the authority
        revisions, and confers no approval or effect authority.
        """
        with self._transaction() as conn:
            self._require_epoch(conn)
            row = conn.execute('SELECT state FROM control_operations WHERE operation_id=?',
                               (operation_id,)).fetchone()
            if row is None or row['state'] not in ('PENDING_APPROVAL', 'APPROVED'):
                return False
            conn.execute("UPDATE control_operations SET state='BLOCKED',updated_at=? WHERE operation_id=?",
                         (now, operation_id))
            conn.execute('DELETE FROM control_reservations WHERE operation_id=?',
                         (operation_id,))
            return True

    def mark_admission_unknown(self, operation_id, *, now):
        """Keep the reservation when host background-dispatch outcome is unsure."""
        with self._transaction() as conn:
            self._require_epoch(conn)
            row = conn.execute('SELECT state FROM control_operations WHERE operation_id=?',
                               (operation_id,)).fetchone()
            if row is None or row['state'] != 'PENDING_APPROVAL':
                raise ControlError('operation_conflict')
            conn.execute("UPDATE control_operations SET state='UNKNOWN',updated_at=? WHERE operation_id=?",
                         (now, operation_id))

    def withdraw_unpresented(self, ctx, operation_id, *, now):
        """Release only a newly admitted intent that never reached a human UI.

        Outcome evidence: stale authority revisions must not keep the reservation.
        """
        with self._transaction() as conn:
            row = self._owned(conn, ctx, operation_id, now, check_authority=False)
            conn.execute("UPDATE control_operations SET state='BLOCKED',updated_at=? WHERE operation_id=?",
                         (now, operation_id))
            conn.execute('DELETE FROM control_reservations WHERE operation_id=?', (operation_id,))
            return _public(conn.execute('SELECT * FROM control_operations WHERE operation_id=?',
                                        (operation_id,)).fetchone())

    def claim_approved(self, ctx, operation_id, *, now):
        """The only APPROVED -> RUNNING path: principal, arguments, state, fence, then RUNNING.

        Binding checks precede state so a replay of a consumed approval is
        classified by who and what it names before it learns the outcome.
        """
        with self._transaction() as conn:
            self._require_epoch(conn)
            row = conn.execute('SELECT * FROM control_operations WHERE operation_id=?',
                               (operation_id,)).fetchone()
            if row is None:
                raise ControlError('resource_denied')
            require_access(ctx, scope=SCOPES[row['kind']], profile_id=row['profile_id'],
                           workspace_id=row['workspace_id'], now=now)
            if (row['subject'] != ctx.subject or row['client_registration'] != ctx.client_registration
                    or row['resource'] != ctx.resource or row['grant_revision'] != ctx.grant_revision):
                raise ControlError('resource_denied')
            try:
                request = json.loads(row['request_json'])
                matches = canonical_intent_digest(request) == row['intent_digest']
            except (ValueError, TypeError, ControlError):
                matches = False
            if not matches:
                raise ControlError('argument_mismatch')
            if (row['kind'] != 'start_engineering_run' or row['state'] != 'APPROVED'
                    or row['expires_at'] <= now):
                raise ControlError('operation_conflict')
            self._check_authority(row, epoch_column='approved_epoch')
            claimed = conn.execute("UPDATE control_operations SET state='RUNNING',updated_at=? "
                                   "WHERE operation_id=? AND state='APPROVED'", (now, operation_id))
            if claimed.rowcount != 1:
                raise ControlError('operation_conflict')
            return request

    def transition(self,operation_id,*,expected_state,new_state,now,result=None):
        """Trusted host outcome recording only; not an exported tool or arbitrary setter.

        Checks the owner epoch but not authority revisions: an outcome of an
        already-claimed effect must be recordable after a policy change. Only a
        known outcome of a claimed run stores a result, atomically with its
        state; a recorded result is never replaced.
        """
        if new_state not in _EDGES.get(expected_state,set()):
            raise ControlError('invalid_transition')
        known=result is not None and expected_state=='RUNNING' and new_state in _RESULT_STATES
        stored=_result_json(new_state,result) if known else None
        with self._transaction() as conn:
            self._require_epoch(conn)
            row=conn.execute('SELECT * FROM control_operations WHERE operation_id=?',(operation_id,)).fetchone()
            if row is None or row['state']!=expected_state:
                raise ControlError('operation_conflict')
            if expected_state=='APPROVED' and now>=row['expires_at']:
                raise ControlError('expired_approval')
            conn.execute('UPDATE control_operations SET state=?,updated_at=?,result_json=COALESCE(result_json,?) '
                         'WHERE operation_id=?',
                         (new_state,now,stored,operation_id))
            if new_state in _TERMINAL:
                conn.execute('DELETE FROM control_reservations WHERE operation_id=?',(operation_id,))
