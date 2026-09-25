"""LM03 / RV04: an approval claim is bound to the live authority state.

Contract: docs/windows/workstation-20260924/cursor-handoff/F01_AUTHORITY_CONTRACT.md.
Every case drives the production journal / approval / owner APIs; a previous
host process is a real subprocess that exits without a clean shutdown.
"""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
import dataclasses
import hashlib
import json
from pathlib import Path
import sqlite3
import subprocess
import sys
from types import SimpleNamespace

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi import FastAPI
import pytest

from downstream.control_mcp import journal as journal_mod
from downstream.control_mcp.contracts import ControlContext, ControlError
from downstream.control_mcp.coordinator import HostControlCoordinator
from downstream.control_mcp.service import HostControlService
from downstream.control_mcp.startup import ControlMCPStartupConfig
from hermes_cli import web_server
from plugins.implementation_router import entrypoint
from plugins.implementation_router.control import EngineeringRunOwner
from tests.control_mcp.conftest import engineering_config
from tools import approval

REPO_ROOT = Path(__file__).resolve().parents[2]
KIND = 'start_engineering_run'
TASK = 'Add a bounded regression test'
SOURCE = 'a' * 40
HUMAN_ONLY_KEYS = frozenset({'request_id'})
MACHINE_CONTROL_KEYS = frozenset({'intent_digest', 'operation_id', 'presentation_digest', 'expires_at'})

# Shared with apps/desktop and ui-tui tests: the UI recomputes this digest over
# the rendered presentation, so both sides must canonicalise byte-identically.
PRESENTATION_PARITY_FIXTURE = {
    'expires_at': 1_700_000_000,
    'grant_revision': 7,
    'kind': KIND,
    'resource': 'https://hermes.invalid/control/mcp',
    'task': 'line1\nline2 "quoted" \\ tab\t ctrl\u0001 \u65e5\u672c\u8a9e \u2028 \U0001F600',
}
PRESENTATION_PARITY_DIGEST = 'c0e7ed6e0c659141be826c9ca6af6dd4a62bf96776dcc8d401440c8cea47eba3'


def make_ctx(**changes):
    values = dict(subject='human-1', client_registration='codex', issuer='https://issuer.invalid',
                  resource='https://hermes.invalid/control/mcp', grant_revision=1, expires_at=10_000,
                  scopes=('hermes:read', 'hermes:run:start'), profiles=('p1',),
                  workspaces=(('p1', 'w1'), ('p1', 'w2'), ('p1', 'w3')))
    values.update(changes)
    return ControlContext(**values)


def make_request(workspace='w1', key=None, task=TASK):
    return {'kind': KIND, 'profile_id': 'p1', 'workspace_id': workspace,
            'idempotency_key': key or f'key-{workspace}', 'expected_revision': 'rev-1',
            'source_sha': SOURCE, 'parameters': {'task': task}}


def open_host(db):
    journal = journal_mod.HostControlJournal(db)
    journal.initialise()
    return journal


def ui_digest(payload):
    """What a UI computes over the presentation it actually rendered."""
    presentation = payload['control']['presentation']
    return hashlib.sha256(json.dumps(presentation, ensure_ascii=False, sort_keys=True,
                                     separators=(',', ':')).encode('utf-8')).hexdigest()


_SESSIONS: set[str] = set()


@pytest.fixture(autouse=True)
def _release_human_sessions():
    yield
    while _SESSIONS:
        approval.unregister_gateway_notify(_SESSIONS.pop())


def present(journal, ctx, operation_id, *, session='lm03-human'):
    """Present one approval and return (ticket, binding, payload seen by the UI)."""
    binding = journal.approval_binding(ctx, operation_id, now=110)
    seen = []
    approval.register_gateway_notify(session, seen.append)
    _SESSIONS.add(session)
    ticket = approval.request_control_consent(binding, session_key=session,
                                              timeout_seconds=60, now=110)
    return ticket, binding, seen[0]


def approve(journal, ctx, operation_id, *, now=111, session='lm03-human'):
    ticket, binding, payload = present(journal, ctx, operation_id, session=session)
    kwargs = dict(session_key=session, request_id=ticket.request_id,
                  intent_digest=binding.intent_digest, choice='once', now=now)
    if 'presentation' in payload['control']:
        kwargs['presentation_digest'] = ui_digest(payload)
    assert approval.resolve_control_consent(**kwargs)
    return journal.approve(ctx, operation_id, approval.take_control_decision(ticket, now=now), now=now)


def visible(payload):
    """Everything a human can read in the approval UI (machine ids excluded)."""
    control = {k: v for k, v in payload['control'].items() if k not in MACHINE_CONTROL_KEYS}
    return {**{k: v for k, v in payload.items() if k not in HUMAN_ONLY_KEYS and k != 'control'},
            'control': control}


def state_of(db, operation_id):
    with sqlite3.connect(db) as conn:
        return conn.execute('SELECT state FROM control_operations WHERE operation_id=?',
                            (operation_id,)).fetchone()[0]


def bump_contract(**changes):
    """Change one authority input the host binds; returns an undo callable."""
    contracts = getattr(journal_mod, '_KIND_CONTRACTS', {})
    if KIND not in contracts:
        return lambda: None
    original = contracts[KIND]
    contracts[KIND] = dataclasses.replace(original, **changes)
    return lambda: contracts.__setitem__(KIND, original)


@pytest.fixture
def db(tmp_path):
    return tmp_path / 'state' / 'control.db'


@pytest.fixture
def effects(monkeypatch):
    """Count native engineering effects and build the production run owner."""
    calls = []
    hooks = []

    def native_run(_plugin_ctx, args, *, run_id, operation_id):
        calls.append({'operation_id': operation_id, 'task': args['task']})
        for hook in hooks:
            hook()
        return json.dumps({'state': 'SUCCEEDED', 'run_id': run_id})

    monkeypatch.setattr(entrypoint, 'run_workflow', native_run)
    pool = ThreadPoolExecutor(max_workers=1)

    def owner(journal):
        return EngineeringRunOwner(
            journal=journal, plugin_ctx=object(), submit=pool.submit,
            validate_intent=lambda _request: True, verify_result=lambda *_a: True,
            revalidate_grant=lambda _ctx, *, now: None, clock=lambda: 112)

    yield calls, hooks, owner
    pool.shutdown(wait=True)


def reserve_approved(journal, ctx, workspace='w1', **request_changes):
    operation_id = journal.reserve(ctx, make_request(workspace, **request_changes), now=100)['operation_id']
    approve(journal, ctx, operation_id)
    return operation_id


_PREVIOUS_HOST = r'''
import importlib.util, json, os, sys
spec = importlib.util.spec_from_file_location('lm03_helpers', sys.argv[1])
helpers = importlib.util.module_from_spec(spec)
spec.loader.exec_module(helpers)
from pathlib import Path
journal = helpers.open_host(Path(sys.argv[2]))
ctx = helpers.make_ctx()
out = {}
for step in json.loads(sys.argv[4]):
    op = journal.reserve(ctx, helpers.make_request(step['workspace']), now=100)['operation_id']
    if step['until'] in ('APPROVED', 'RUNNING'):
        helpers.approve(journal, ctx, op)
    if step['until'] == 'RUNNING':
        journal.claim_approved(ctx, op, now=112)
    out[step['workspace']] = op
Path(sys.argv[3]).write_text(json.dumps(out), encoding='utf-8')
os._exit(0)
'''


def previous_host_crashes_after(tmp_path, db, steps):
    """A real earlier host process performs steps then dies without shutdown."""
    out = tmp_path / 'previous-host.json'
    subprocess.run([sys.executable, '-c', _PREVIOUS_HOST, str(Path(__file__).resolve()), str(db),
                    str(out), json.dumps(steps)], cwd=REPO_ROOT, check=True, timeout=120)
    return json.loads(out.read_text(encoding='utf-8'))


# --- B1 / policy + tool revision ------------------------------------------------

def test_b1_stale_policy_revision_denies_claim_with_zero_effect(db, effects):
    calls, _hooks, owner = effects
    journal = open_host(db)
    ctx = make_ctx()
    operation_id = reserve_approved(journal, ctx)
    undo = bump_contract(policy_version=2)
    try:
        with pytest.raises(ControlError) as denied:
            owner(journal).start_approved(ctx, operation_id)
    finally:
        undo()
    assert denied.value.code == 'stale_policy'
    assert calls == []
    assert state_of(db, operation_id) == 'APPROVED'


def test_b1_stale_tool_revision_denies_claim_with_zero_effect(db, effects):
    calls, _hooks, owner = effects
    journal = open_host(db)
    ctx = make_ctx()
    operation_id = reserve_approved(journal, ctx)
    undo = bump_contract(tool_contract=f'{KIND}@2')
    try:
        with pytest.raises(ControlError) as denied:
            owner(journal).start_approved(ctx, operation_id)
    finally:
        undo()
    assert denied.value.code == 'stale_tool'
    assert calls == []


def test_b1_operator_policy_edit_in_config_yaml_denies_claim_with_zero_effect(db, effects, host_config):
    calls, _hooks, owner = effects
    settings = {'enabled': True, 'workspaces': {'w1': {'path': 'repo-a', 'checks': [{'id': 'unit'}]}}}
    host_config(engineering_config(settings=settings))
    journal = open_host(db)
    ctx = make_ctx()
    kept = reserve_approved(journal, ctx, 'w1')
    tightened = reserve_approved(journal, ctx, 'w2')
    unrelated = {**engineering_config(settings=settings), 'display': {'language': 'ja'}}
    host_config(unrelated)
    owner(journal).start_approved(ctx, kept).future.result(timeout=10)
    settings['workspaces']['w1']['checks'].append({'id': 'lint'})
    host_config({**unrelated, **engineering_config(settings=settings)})
    with pytest.raises(ControlError) as denied:
        owner(journal).start_approved(ctx, tightened)
    assert denied.value.code == 'stale_policy'
    assert [call['operation_id'] for call in calls] == [kept]
    assert state_of(db, tightened) == 'APPROVED'


# --- B2 / owner epoch -------------------------------------------------------------

def test_b2_approval_from_previous_host_epoch_is_stale_authority(tmp_path, db, effects):
    calls, _hooks, owner = effects
    ops = previous_host_crashes_after(tmp_path, db, [{'workspace': 'w1', 'until': 'APPROVED'}])
    journal = open_host(db)
    ctx = make_ctx()
    # Startup reconciliation has already withdrawn the earlier owner's approval.
    with pytest.raises(ControlError) as denied:
        owner(journal).start_approved(ctx, ops['w1'])
    assert denied.value.code == 'operation_conflict'
    # Even if that row were still APPROVED, its epoch is not this owner's.
    with sqlite3.connect(db) as conn:
        conn.execute("UPDATE control_operations SET state='APPROVED' WHERE operation_id=?", (ops['w1'],))
    with pytest.raises(ControlError) as denied:
        owner(journal).start_approved(ctx, ops['w1'])
    assert denied.value.code == 'stale_owner_epoch'
    assert calls == []


def test_b2b_second_concurrent_host_cannot_open_an_epoch(db):
    first = open_host(db)
    try:
        with pytest.raises(ControlError) as busy:
            open_host(db)
        assert busy.value.code == 'owner_epoch_busy'
    finally:
        first.close()
    open_host(db).close()


def test_b2b_closed_host_handle_has_no_write_authority(db):
    journal = open_host(db)
    ctx = make_ctx()
    operation_id = reserve_approved(journal, ctx)
    journal.close()
    with pytest.raises(ControlError) as denied:
        journal.claim_approved(ctx, operation_id, now=112)
    assert denied.value.code in {'owner_epoch_required', 'stale_owner_epoch'}


def test_b2b_displaced_owner_handle_is_fenced_from_every_write(db, effects):
    """A handle whose epoch is no longer the open one (lock lost) cannot write at all."""
    calls, _hooks, owner = effects
    journal = open_host(db)
    ctx = make_ctx()
    approved = reserve_approved(journal, ctx)
    running = reserve_approved(journal, ctx, workspace='w2')
    with sqlite3.connect(db) as conn:
        conn.execute("UPDATE control_operations SET state='RUNNING' WHERE operation_id=?", (running,))
        conn.execute("UPDATE control_owner_epochs SET closed_at=112,close_reason='restart' WHERE closed_at IS NULL")
        conn.execute("INSERT INTO control_owner_epochs(epoch_id,opened_at,owner_pid) VALUES (?,112,0)",
                     ('e' * 32,))
    writes = [
        lambda: journal.reserve(ctx, make_request('w3'), now=113),
        lambda: owner(journal).start_approved(ctx, approved),
        lambda: journal.transition(running, expected_state='RUNNING', new_state='SUCCEEDED', now=113),
    ]
    for write in writes:
        with pytest.raises(ControlError) as denied:
            write()
        assert denied.value.code == 'stale_owner_epoch'
    assert calls == []
    assert (state_of(db, approved), state_of(db, running)) == ('APPROVED', 'RUNNING')
    journal.close()


_LEGACY_V1 = '''
CREATE TABLE control_operations (
    operation_id TEXT PRIMARY KEY, subject TEXT NOT NULL, client_registration TEXT NOT NULL,
    resource TEXT NOT NULL, grant_revision INTEGER NOT NULL, idempotency_key TEXT NOT NULL,
    profile_id TEXT NOT NULL, workspace_id TEXT NOT NULL, kind TEXT NOT NULL,
    intent_digest TEXT NOT NULL, request_json TEXT NOT NULL, expected_revision TEXT NOT NULL,
    source_sha TEXT NOT NULL, expires_at INTEGER NOT NULL, state TEXT NOT NULL,
    updated_at REAL NOT NULL, UNIQUE(subject,client_registration,idempotency_key));
CREATE TABLE control_reservations (
    profile_id TEXT NOT NULL, workspace_id TEXT NOT NULL,
    operation_id TEXT NOT NULL REFERENCES control_operations(operation_id),
    PRIMARY KEY(profile_id,workspace_id));
PRAGMA user_version=1;
'''


def test_b2b_legacy_row_without_epoch_is_never_promoted_to_current(db, effects):
    calls, _hooks, owner = effects
    ctx = make_ctx()
    request = make_request()
    db.parent.mkdir(parents=True)
    with sqlite3.connect(db) as conn:
        conn.executescript(_LEGACY_V1)
        conn.execute('INSERT INTO control_operations VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)',
                     ('op-legacy', ctx.subject, ctx.client_registration, ctx.resource, ctx.grant_revision,
                      request['idempotency_key'], 'p1', 'w1', KIND,
                      journal_mod.canonical_intent_digest(request),
                      journal_mod.canonical_json(request).decode(), 'rev-1', SOURCE, 700, 'APPROVED', 100.0))
        conn.execute("INSERT INTO control_reservations VALUES ('p1','w1','op-legacy')")
    journal = open_host(db)
    assert state_of(db, 'op-legacy') == 'BLOCKED'
    with sqlite3.connect(db) as conn:
        conn.execute("UPDATE control_operations SET state='APPROVED' WHERE operation_id='op-legacy'")
    with pytest.raises(ControlError) as denied:
        owner(journal).start_approved(ctx, 'op-legacy')
    assert denied.value.code == 'stale_owner_epoch'
    assert calls == []


def test_g1_owner_epoch_is_persisted_with_the_binding_and_read_back(db):
    journal = open_host(db)
    ctx = make_ctx()
    operation_id = journal.reserve(ctx, make_request(), now=100)['operation_id']
    binding = journal.approval_binding(ctx, operation_id, now=110)
    with sqlite3.connect(db) as conn:
        open_epoch = conn.execute(
            'SELECT epoch_id FROM control_owner_epochs WHERE closed_at IS NULL').fetchone()[0]
        row_epoch = conn.execute('SELECT owner_epoch FROM control_operations WHERE operation_id=?',
                                 (operation_id,)).fetchone()[0]
    assert binding.owner_epoch == row_epoch == open_epoch
    approve(journal, ctx, operation_id)
    with sqlite3.connect(db) as conn:
        approved_epoch = conn.execute('SELECT approved_epoch FROM control_operations WHERE operation_id=?',
                                      (operation_id,)).fetchone()[0]
    assert approved_epoch == open_epoch


# --- B4 / arguments -----------------------------------------------------------------

def test_b4_arguments_changed_after_approval_are_denied_canonically(db, effects):
    calls, _hooks, owner = effects
    journal = open_host(db)
    ctx = make_ctx()
    operation_id = reserve_approved(journal, ctx)
    tampered = make_request(task=TASK + ' and push to main')
    with sqlite3.connect(db) as conn:
        conn.execute('UPDATE control_operations SET request_json=? WHERE operation_id=?',
                     (json.dumps(tampered), operation_id))
    with pytest.raises(ControlError) as denied:
        owner(journal).start_approved(ctx, operation_id)
    assert denied.value.code == 'argument_mismatch'
    assert calls == []


def test_b4_non_canonical_spelling_of_the_same_arguments_is_accepted(db, effects):
    calls, _hooks, owner = effects
    journal = open_host(db)
    ctx = make_ctx()
    operation_id = reserve_approved(journal, ctx)
    reordered = json.dumps(dict(reversed(list(make_request().items()))), indent=2)
    with sqlite3.connect(db) as conn:
        conn.execute('UPDATE control_operations SET request_json=? WHERE operation_id=?',
                     (reordered, operation_id))
    owner(journal).start_approved(ctx, operation_id).future.result(timeout=10)
    assert [call['task'] for call in calls] == [TASK]


def test_b4_same_idempotency_key_with_different_arguments_conflicts(db):
    journal = open_host(db)
    ctx = make_ctx()
    journal.reserve(ctx, make_request(key='k'), now=100)
    with pytest.raises(ControlError) as conflict:
        journal.reserve(ctx, make_request(key='k', task=TASK + '!'), now=101)
    assert conflict.value.code == 'idempotency_conflict'


# --- B6 / principal, client, profile ---------------------------------------------------

@pytest.mark.parametrize('changes', [
    {'client_registration': 'other-client'},
    {'subject': 'human-2'},
    {'profiles': ('p2',), 'workspaces': (('p2', 'w1'),)},
    {'grant_revision': 2},
])
def test_b6_claim_by_a_different_principal_client_or_profile_is_denied(db, effects, changes):
    calls, _hooks, owner = effects
    journal = open_host(db)
    operation_id = reserve_approved(journal, make_ctx())
    with pytest.raises(ControlError) as denied:
        owner(journal).start_approved(make_ctx(**changes), operation_id)
    assert denied.value.code == 'resource_denied'
    assert calls == []


# --- B7 / G2 / restart ------------------------------------------------------------------

def start_production_host(db):
    """Start the host exactly as the web server lifespan does, from trusted config."""
    public_key = rsa.generate_private_key(public_exponent=65537, key_size=2048).public_key()
    journal = journal_mod.HostControlJournal(db)
    service = HostControlService(source=SimpleNamespace(), clock=lambda: 115, journal=journal)
    application = FastAPI()
    application.state.control_mcp_startup_config = ControlMCPStartupConfig(
        service=service, issuer='https://issuer.invalid',
        resource='https://hermes.invalid/api/control/mcp',
        public_keys={'key-1': public_key.public_bytes(
            serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo)},
        grant_lookup=lambda _subject, _client: None,
        allowed_hosts=('hermes.invalid',), allowed_origins=('https://chatgpt.com',),
        clock=lambda: 115)
    first = web_server._prepare_control_mcp_host(application)
    epoch = journal._epoch_id
    # A lifespan restart on the same config reuses the host: no second epoch opener.
    assert web_server._prepare_control_mcp_host(application) is first
    assert epoch is not None and journal._epoch_id == epoch
    return journal


def test_b7_g2_host_startup_reconciles_previous_epoch_without_re_execution(tmp_path, db, effects):
    calls, _hooks, owner = effects
    ops = previous_host_crashes_after(tmp_path, db, [
        {'workspace': 'w1', 'until': 'RUNNING'},
        {'workspace': 'w2', 'until': 'APPROVED'},
        {'workspace': 'w3', 'until': 'PENDING'},
    ])
    journal = start_production_host(db)  # no explicit initialise or recover call
    ctx = make_ctx()
    assert state_of(db, ops['w1']) == 'UNKNOWN'
    assert state_of(db, ops['w2']) == 'BLOCKED'
    assert state_of(db, ops['w3']) == 'BLOCKED'
    for operation_id in ops.values():
        with pytest.raises(ControlError):
            owner(journal).start_approved(ctx, operation_id)
    assert calls == []
    with pytest.raises(ControlError) as busy:
        journal.reserve(ctx, make_request('w1', key='fresh-w1'), now=120)
    assert busy.value.code == 'workspace_busy'
    assert journal.reserve(ctx, make_request('w2', key='fresh-w2'), now=120)['state'] == 'PENDING_APPROVAL'


def test_b7_invalid_startup_config_fails_before_taking_the_owner_epoch(db):
    journal = journal_mod.HostControlJournal(db)
    config = dict(issuer='https://issuer.invalid', resource='https://hermes.invalid/api/control/mcp',
                  public_keys={}, grant_lookup=lambda _subject, _client: None,
                  allowed_hosts=('hermes.invalid',), allowed_origins=('https://chatgpt.com',))
    application = FastAPI()
    application.state.control_mcp_startup_config = ControlMCPStartupConfig(
        service=HostControlService(source=SimpleNamespace(), journal=journal), **config)
    with pytest.raises(ControlError) as invalid:
        web_server._prepare_control_mcp_host(application)
    assert invalid.value.code == 'invalid_host_configuration'
    assert journal._epoch_id is None
    open_host(db).close()  # the owner lock was never taken
    with pytest.raises(ControlError):
        ControlMCPStartupConfig(service=HostControlService(source=SimpleNamespace(), journal=object()),
                                **config)


# --- G3 / long tasks --------------------------------------------------------------------

def test_g3_tasks_sharing_a_long_prefix_are_distinguishable_to_the_human(db):
    journal = open_host(db)
    ctx = make_ctx()
    prefix = 'x' * 2500
    first = journal.reserve(ctx, make_request('w1', task=prefix + ' then delete build cache'), now=100)
    second = journal.reserve(ctx, make_request('w2', task=prefix + ' then force-push main'), now=100)
    _t1, binding_a, payload_a = present(journal, ctx, first['operation_id'], session='g3-a')
    _t2, binding_b, payload_b = present(journal, ctx, second['operation_id'], session='g3-b')
    assert binding_a.intent_digest != binding_b.intent_digest
    assert visible(payload_a) != visible(payload_b)
    assert 'force-push main' in json.dumps(visible(payload_b), ensure_ascii=False)
    assert 'force-push main' not in json.dumps(visible(payload_a), ensure_ascii=False)


# --- B8 / G5 / presentation parity -------------------------------------------------------

def _row(**changes):
    request = make_request()
    row = dict(operation_id='op-' + '1' * 32, subject='human-1', client_registration='codex',
               resource='https://hermes.invalid/control/mcp', grant_revision=1, profile_id='p1',
               workspace_id='w1', kind=KIND, request_json=json.dumps(request), expected_revision='rev-1',
               source_sha=SOURCE, expires_at=700, policy_revision='p' * 64, tool_revision=f'{KIND}@1',
               route_revision='r' * 64, provider_revision='', route_effect_class='code_producing_delegate',
               owner_epoch='e' * 32)
    row.update(changes)
    return row


@pytest.mark.parametrize('column, value', [
    ('resource', 'https://elsewhere.invalid/control/mcp'),
    ('workspace_id', 'w9'),
    ('profile_id', 'p9'),
    ('expected_revision', 'rev-2'),
    ('source_sha', 'b' * 40),
    ('client_registration', 'other-client'),
    ('subject', 'human-2'),
    ('grant_revision', 2),
    ('request_json', json.dumps(make_request(task=TASK + ' but also rm -rf'))),
    ('policy_revision', 'q' * 64),
    ('tool_revision', f'{KIND}@2'),
    ('route_effect_class', 'read_only_analysis'),
    ('route_revision', 's' * 64),
    ('provider_revision', 'provider@2'),
    ('owner_epoch', 'f' * 32),
    ('expires_at', 701),
    ('operation_id', 'op-' + '2' * 32),
])
def test_b8_every_authority_field_reaches_the_projection(column, value):
    base = journal_mod.approval_presentation(_row())
    assert journal_mod.approval_presentation(_row(**{column: value})) != base, column


def test_b8_a_kind_without_a_contract_has_no_projection():
    with pytest.raises(ControlError) as denied:
        journal_mod.approval_presentation(_row(kind='merge_pull_request'))
    assert denied.value.code == 'unsupported_operation'


@pytest.mark.parametrize('changes', [
    {'client_registration': 'other-client'},
    {'subject': 'human-2'},
    {'profile_id': 'p2'},
])
def test_b8_identity_the_human_approves_for_is_visible_in_the_ui_payload(db, changes):
    journal = open_host(db)
    base_ctx = make_ctx()
    operation_id = journal.reserve(base_ctx, make_request(), now=100)['operation_id']
    _t, _b, base_payload = present(journal, base_ctx, operation_id, session='b8-base')
    ctx_changes = {k: v for k, v in changes.items() if k != 'profile_id'}
    if 'profile_id' in changes:
        ctx_changes.update(profiles=(changes['profile_id'],), workspaces=((changes['profile_id'], 'w1'),))
    with sqlite3.connect(db) as conn:
        for column, value in changes.items():
            conn.execute(f'UPDATE control_operations SET {column}=? WHERE operation_id=?', (value, operation_id))
    _t, _b, mutated = present(journal, make_ctx(**ctx_changes), operation_id, session='b8-mutated')
    assert visible(mutated) != visible(base_payload)


def test_b8_approval_requires_the_digest_of_the_rendered_presentation(db):
    journal = open_host(db)
    ctx = make_ctx()
    operation_id = journal.reserve(ctx, make_request(), now=100)['operation_id']
    ticket, binding, payload = present(journal, ctx, operation_id)
    base = dict(session_key='lm03-human', request_id=ticket.request_id,
                intent_digest=binding.intent_digest, choice='once', now=111)
    assert not approval.resolve_control_consent(**base)
    assert not approval.resolve_control_consent(**base, presentation_digest='0' * 64)
    edited = json.loads(json.dumps(payload))
    edited['control']['presentation']['workspace_id'] = 'w9'
    assert not approval.resolve_control_consent(**base, presentation_digest=ui_digest(edited))
    assert approval.resolve_control_consent(**base, presentation_digest=ui_digest(payload))


def test_b8_deny_needs_no_presentation_digest(db):
    journal = open_host(db)
    ctx = make_ctx()
    operation_id = journal.reserve(ctx, make_request(), now=100)['operation_id']
    ticket, binding, _payload = present(journal, ctx, operation_id)
    assert approval.resolve_control_consent(session_key='lm03-human', request_id=ticket.request_id,
                                            intent_digest=binding.intent_digest, choice='deny', now=111)


def test_b8_long_task_is_full_in_presentation_and_bounded_in_preview(db):
    journal = open_host(db)
    ctx = make_ctx()
    task = 'y' * 15_000 + ' TAIL'
    operation_id = journal.reserve(ctx, make_request(task=task), now=100)['operation_id']
    _t, binding, payload = present(journal, ctx, operation_id)
    assert payload['control']['presentation']['task'] == task
    assert len(payload['description']) <= 6144
    assert 'truncated' in payload['description']
    assert 'presentation_digest' not in payload['control']
    assert binding.presentation_digest == ui_digest(payload)


def test_presentation_canonicalisation_matches_the_ui_parity_fixture():
    rendered = journal_mod.canonical_json(PRESENTATION_PARITY_FIXTURE, limit=65_536)
    assert hashlib.sha256(rendered).hexdigest() == PRESENTATION_PARITY_DIGEST


# --- I-CLAIM ------------------------------------------------------------------------------

def test_i_claim_generic_transition_cannot_start_an_approved_operation(db):
    journal = open_host(db)
    ctx = make_ctx()
    operation_id = reserve_approved(journal, ctx)
    with pytest.raises(ControlError):
        journal.transition(operation_id, expected_state='APPROVED', new_state='RUNNING', now=112)
    assert state_of(db, operation_id) == 'APPROVED'
    assert journal.claim_approved(ctx, operation_id, now=112) == make_request()
    assert state_of(db, operation_id) == 'RUNNING'
    journal.transition(operation_id, expected_state='RUNNING', new_state='SUCCEEDED', now=113)
    assert state_of(db, operation_id) == 'SUCCEEDED'


def test_i_claim_non_start_edges_stay_available(db):
    journal = open_host(db)
    ctx = make_ctx()
    blocked = reserve_approved(journal, ctx, 'w1')
    journal.transition(blocked, expected_state='APPROVED', new_state='BLOCKED', now=112)
    unknown = reserve_approved(journal, ctx, 'w2')
    journal.claim_approved(ctx, unknown, now=112)
    journal.transition(unknown, expected_state='RUNNING', new_state='UNKNOWN', now=113)
    assert (state_of(db, blocked), state_of(db, unknown)) == ('BLOCKED', 'UNKNOWN')


# --- §8.2 fence vs outcome ------------------------------------------------------------------

def run_through_coordinator(journal, ctx, owner, *, before_decision=lambda: None,
                            revalidate_grant=lambda _ctx, *, now: None, session='lm03-coordinator'):
    """Drive the production admission path: submit, human "once", background decision."""
    seen = []
    approval.register_gateway_notify(session, seen.append)
    _SESSIONS.add(session)
    jobs = []
    with ThreadPoolExecutor(max_workers=1) as pool:
        coordinator = HostControlCoordinator(
            journal=journal, owner=owner, select_human_session=lambda _p, _w: session,
            submit_background=lambda *job: jobs.append(pool.submit(*job)),
            revalidate_grant=revalidate_grant, clock=lambda: 112)
        operation_id = coordinator.submit(ctx, make_request())['operation_id']
        payload = seen[0]
        before_decision()
        assert approval.resolve_control_consent(
            session_key=session, request_id=payload['request_id'],
            intent_digest=payload['control']['intent_digest'], choice='once',
            presentation_digest=ui_digest(payload), now=112)
        assert jobs[0].result(timeout=30) is None
    return operation_id


def test_s82_stale_fence_blocks_the_effect_and_the_rejection_is_recorded(db, effects):
    calls, _hooks, owner = effects
    journal = open_host(db)
    ctx = make_ctx()
    run_owner = owner(journal)
    undo = []
    claim = run_owner.start_approved

    def policy_changes_between_approval_and_claim(ctx_, operation_id):
        undo.append(bump_contract(policy_version=3))
        return claim(ctx_, operation_id)

    run_owner.start_approved = policy_changes_between_approval_and_claim
    try:
        operation_id = run_through_coordinator(journal, ctx, run_owner)
    finally:
        for step in undo:
            step()
    assert undo, 'the approval must reach the claim'
    assert calls == []
    assert state_of(db, operation_id) == 'BLOCKED'
    assert journal.reserve(ctx, make_request(key='after-block'), now=114)['state'] == 'PENDING_APPROVAL'


def test_s82_displaced_owner_worker_records_nothing_and_does_not_raise(db, effects, caplog):
    calls, _hooks, owner = effects
    journal = open_host(db)
    ctx = make_ctx()
    revoked = []

    def displace_owner_and_revoke_grant():
        with sqlite3.connect(db) as conn:
            conn.execute("UPDATE control_owner_epochs SET closed_at=112,close_reason='restart' WHERE closed_at IS NULL")
            conn.execute("INSERT INTO control_owner_epochs(epoch_id,opened_at,owner_pid) VALUES (?,112,0)",
                         ('e' * 32,))
        revoked.append(True)

    def revalidate_grant(_ctx, *, now):
        if revoked:
            raise ControlError('revoked_grant')

    with caplog.at_level('WARNING', logger='downstream.control_mcp.coordinator'):
        operation_id = run_through_coordinator(journal, ctx, owner(journal),
                                               before_decision=displace_owner_and_revoke_grant,
                                               revalidate_grant=revalidate_grant)
    assert calls == []
    assert state_of(db, operation_id) == 'PENDING_APPROVAL'
    assert f'control operation {operation_id} not recorded: stale_owner_epoch' in caplog.text
    journal.close()


def test_s82_revision_change_during_the_run_still_records_the_outcome(db, effects):
    calls, hooks, owner = effects
    journal = open_host(db)
    ctx = make_ctx()
    operation_id = reserve_approved(journal, ctx)
    undo = []
    hooks.append(lambda: undo.append(bump_contract(policy_version=4, tool_contract=f'{KIND}@9')))
    try:
        owner(journal).start_approved(ctx, operation_id).future.result(timeout=10)
    finally:
        for step in undo:
            step()
    assert len(calls) == 1
    assert state_of(db, operation_id) == 'SUCCEEDED'


# --- route / provider revision -----------------------------------------------------------------

def test_b9_picker_model_change_keeps_the_approval_but_losing_the_route_does_not(db, effects, host_config):
    calls, _hooks, owner = effects
    journal = open_host(db)
    ctx = make_ctx()
    remodelled = reserve_approved(journal, ctx, 'w1')
    unrouted = reserve_approved(journal, ctx, 'w2')
    host_config(engineering_config(model='model-b'))
    owner(journal).start_approved(ctx, remodelled).future.result(timeout=10)
    host_config(engineering_config(roles=('planner', 'reviewer')))
    with pytest.raises(ControlError) as denied:
        owner(journal).start_approved(ctx, unrouted)
    assert denied.value.code == 'route_unavailable'
    assert [call['operation_id'] for call in calls] == [remodelled]
    assert state_of(db, unrouted) == 'APPROVED'


@pytest.mark.parametrize('malformed', [
    {'auxiliary': None},
    {'plugins': ['implementation_router'], 'auxiliary': None},
    {'plugins': {'entries': ['implementation_router']}, 'auxiliary': 'none'},
])
def test_b9_malformed_config_blocks_the_approval_instead_of_stranding_it(db, effects, host_config, malformed):
    calls, _hooks, owner = effects
    journal = open_host(db)
    ctx = make_ctx()
    run_owner = owner(journal)
    claim = run_owner.start_approved

    def config_breaks_between_approval_and_claim(ctx_, operation_id):
        host_config(malformed)
        return claim(ctx_, operation_id)

    run_owner.start_approved = config_breaks_between_approval_and_claim
    operation_id = run_through_coordinator(journal, ctx, run_owner)
    assert calls == []
    assert state_of(db, operation_id) == 'BLOCKED'


def test_b9_catalogue_refresh_keeps_the_approval_but_a_route_class_change_does_not(db, effects, monkeypatch):
    calls, _hooks, owner = effects
    journal = open_host(db)
    ctx = make_ctx()
    refreshed = reserve_approved(journal, ctx, 'w1')
    rerouted = reserve_approved(journal, ctx, 'w2')
    monkeypatch.setattr(journal_mod, 'current_route_state', lambda _kind: {
        'effect_route_class': 'code_producing_delegate', 'catalogue_refreshed_at': 999,
        'models': ['other-model'], 'price_per_mtok': 1.5}, raising=False)
    owner(journal).start_approved(ctx, refreshed).future.result(timeout=10)
    monkeypatch.setattr(journal_mod, 'current_route_state',
                        lambda _kind: {'effect_route_class': 'read_only_analysis'}, raising=False)
    with pytest.raises(ControlError) as denied:
        owner(journal).start_approved(ctx, rerouted)
    assert denied.value.code == 'stale_route'
    assert [call['operation_id'] for call in calls] == [refreshed]


def test_b9_provider_revision_tracks_adapter_contract_not_catalogue_noise():
    contract = journal_mod.KindContract(schema_version=1, policy_version=1, tool_contract='x@1',
                                        effect_summary='x', provider_sensitive=True)
    state = {'provider_id': 'openai', 'provider_adapter_contract': '3', 'models': ['a'], 'price': 1}
    base = journal_mod.route_binding(contract, state)
    assert journal_mod.route_binding(contract, {**state, 'models': ['b'], 'price': 2}) == base
    assert journal_mod.route_binding(contract, {**state, 'provider_adapter_contract': '4'}) != base
    assert journal_mod.route_binding(contract, {**state, 'provider_id': 'anthropic'}) != base
    with pytest.raises(ControlError):
        journal_mod.route_binding(contract, {'models': ['a']})
