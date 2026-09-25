"""Host admission waits for the existing human approval owner before execution."""
from concurrent.futures import ThreadPoolExecutor
from contextvars import ContextVar
import hashlib
import json
import threading


def rendered_digest(payload):
    # What a human UI computes over the presentation it rendered.
    return hashlib.sha256(json.dumps(payload['control']['presentation'], ensure_ascii=False, sort_keys=True,
                                     separators=(',', ':')).encode('utf-8')).hexdigest()


def test_dispatcher_requires_bound_human_decision_once(
        control_module, control_context, tmp_path, host_config):
    from tests.control_mcp.conftest import engineering_config
    from downstream.control_mcp.coordinator import HostControlCoordinator
    from tools import approval
    from hermes_constants import (get_hermes_home, set_hermes_home_override,
                                  reset_hermes_home_override)

    ctx = control_context(scopes=('hermes:read', 'hermes:run:start'))
    journal = control_module('journal').HostControlJournal(tmp_path / 'control.db')
    journal.initialise()
    request = {'kind': 'start_engineering_run', 'profile_id': 'p1', 'workspace_id': 'w1',
               'idempotency_key': 'dispatch-1', 'expected_revision': 'revision-1',
               'source_sha': 'a' * 40, 'parameters': {'task': 'One bounded change'}}
    displayed = []
    executed = threading.Event()
    calls = []
    sensitive_context = ContextVar('test_secret_must_not_cross', default=None)
    profile_home = tmp_path / 'profile-p1'

    class Owner:
        def start_approved(self, actual_ctx, operation_id):
            assert get_hermes_home() == profile_home
            assert sensitive_context.get() is None
            calls.append(operation_id)
            journal.claim_approved(actual_ctx, operation_id, now=104)
            journal.transition(operation_id, expected_state='RUNNING',
                               new_state='SUCCEEDED', now=105)
            executed.set()

    approval.register_gateway_notify('human-dispatch', displayed.append)
    profile_token = set_hermes_home_override(profile_home)
    host_config(engineering_config())  # the reserving profile's own picker selection
    secret_token = sensitive_context.set('secret')
    try:
        with ThreadPoolExecutor(max_workers=2) as pool:
            coordinator = HostControlCoordinator(
                journal=journal, owner=Owner(),
                select_human_session=lambda profile, workspace: 'human-dispatch',
                submit_background=pool.submit, revalidate_grant=lambda _ctx, *, now: None, clock=lambda: 103)
            first = coordinator.submit(ctx, request)
            second = coordinator.submit(ctx, request)
            assert first['operation_id'] == second['operation_id']
            assert first['state'] == 'PENDING_APPROVAL'
            assert len(displayed) == 1
            assert not executed.is_set()
            assert approval.resolve_control_consent(
                session_key='human-dispatch', request_id=displayed[0]['request_id'],
                intent_digest=first['intent_digest'], choice='once', now=103,
                presentation_digest=rendered_digest(displayed[0]))
            assert executed.wait(5)
        assert calls == [first['operation_id']]
    finally:
        sensitive_context.reset(secret_token)
        reset_hermes_home_override(profile_token)
        approval.unregister_gateway_notify('human-dispatch')


def test_unauthorised_request_never_selects_human_surface(
        control_module, control_context, tmp_path):
    from downstream.control_mcp.coordinator import HostControlCoordinator
    from downstream.control_mcp.contracts import ControlError
    journal = control_module('journal').HostControlJournal(tmp_path / 'control.db')
    journal.initialise()
    selected = []
    coordinator = HostControlCoordinator(journal=journal, owner=object(),
        select_human_session=lambda *args: selected.append(args) or 'human',
        submit_background=lambda *args: None, revalidate_grant=lambda _ctx, *, now: None, clock=lambda: 103)
    request = {'kind': 'start_engineering_run', 'profile_id': 'p1', 'workspace_id': 'w1',
               'idempotency_key': 'dispatch-unauthorised', 'expected_revision': 'r1',
               'source_sha': 'a' * 40, 'parameters': {'task': 'No authority'}}
    try:
        coordinator.submit(control_context(), request)
        assert False, 'unauthorised operation was admitted'
    except ControlError as exc:
        assert exc.code == 'insufficient_scope'
    assert selected == []


def test_ambiguous_waiter_dispatch_retains_reservation(
        control_module, control_context, tmp_path):
    from downstream.control_mcp.coordinator import HostControlCoordinator
    from downstream.control_mcp.contracts import ControlError
    from tools import approval
    ctx = control_context(scopes=('hermes:read', 'hermes:run:start'))
    journal = control_module('journal').HostControlJournal(tmp_path / 'control.db')
    journal.initialise()
    request = {'kind': 'start_engineering_run', 'profile_id': 'p1', 'workspace_id': 'w1',
               'idempotency_key': 'dispatch-ambiguous', 'expected_revision': 'r1',
               'source_sha': 'a' * 40, 'parameters': {'task': 'Do not replay'}}
    displayed = []
    approval.register_gateway_notify('human-ambiguous', displayed.append)
    try:
        coordinator = HostControlCoordinator(journal=journal, owner=object(),
            select_human_session=lambda *args: 'human-ambiguous',
            submit_background=lambda *args: (_ for _ in ()).throw(RuntimeError('unknown')),
            revalidate_grant=lambda _ctx, *, now: None, clock=lambda: 103)
        try:
            coordinator.submit(ctx, request)
            assert False, 'ambiguous scheduler result was accepted'
        except ControlError as exc:
            assert exc.code == 'host_executor_unavailable'
        row = journal.reserve(ctx, request, now=104)
        assert row['state'] == 'UNKNOWN'
        assert approval.list_gateway_approvals('human-ambiguous') == []
        try:
            journal.reserve(ctx, {**request, 'idempotency_key': 'other'}, now=104)
            assert False, 'uncertain operation released workspace'
        except ControlError as exc:
            assert exc.code == 'workspace_busy'
    finally:
        approval.unregister_gateway_notify('human-ambiguous')


def test_expired_human_window_releases_only_unexecuted_intent(
        control_module, control_context, tmp_path):
    from downstream.control_mcp.coordinator import HostControlCoordinator
    from tools import approval
    ctx = control_context(scopes=('hermes:read', 'hermes:run:start'), expires_at=1000)
    journal = control_module('journal').HostControlJournal(tmp_path / 'control.db')
    journal.initialise()
    request = {'kind': 'start_engineering_run', 'profile_id': 'p1', 'workspace_id': 'w1',
               'idempotency_key': 'dispatch-expire', 'expected_revision': 'r1',
               'source_sha': 'a' * 40, 'parameters': {'task': 'Do not execute'}}
    now = [103]
    done = threading.Event()
    class Owner:
        def start_approved(self, *_):
            done.set()
    approval.register_gateway_notify('human-expire', lambda _: None)
    try:
        with ThreadPoolExecutor(max_workers=1) as pool:
            gate = threading.Event()
            def submit_later(fn, *args):
                return pool.submit(lambda: (gate.wait(5), fn(*args))[1])
            coordinator = HostControlCoordinator(journal=journal, owner=Owner(),
                select_human_session=lambda *args: 'human-expire',
                submit_background=submit_later, revalidate_grant=lambda _ctx, *, now: None, clock=lambda: now[0])
            operation = coordinator.submit(ctx, request)
            now[0] = 224
            gate.set()
        row = journal.get(ctx, operation['operation_id'], profile_id='p1',
                          workspace_id='w1', now=224)
        assert row['state'] == 'EXPIRED'
        assert not done.is_set()
        assert journal.reserve(ctx, {**request, 'idempotency_key': 'new'},
                               now=225)['state'] == 'PENDING_APPROVAL'
    finally:
        approval.unregister_gateway_notify('human-expire')


def test_revoked_grant_after_human_once_never_dispatches(
        control_module, control_context, tmp_path):
    from downstream.control_mcp.coordinator import HostControlCoordinator
    from downstream.control_mcp.contracts import ControlError
    from tools import approval

    ctx = control_context(scopes=('hermes:read', 'hermes:run:start'))
    journal = control_module('journal').HostControlJournal(tmp_path / 'control.db')
    journal.initialise()
    request = {'kind': 'start_engineering_run', 'profile_id': 'p1', 'workspace_id': 'w1',
               'idempotency_key': 'dispatch-revoked', 'expected_revision': 'r1',
               'source_sha': 'a' * 40, 'parameters': {'task': 'Never run'}}
    displayed = []
    revoked = threading.Event()
    executed = []
    futures = []

    def revalidate(_ctx, *, now):
        if revoked.is_set():
            raise ControlError('revoked_grant')

    class Owner:
        def start_approved(self, *_):
            executed.append(True)

    approval.register_gateway_notify('human-revoked', displayed.append)
    try:
        with ThreadPoolExecutor(max_workers=1) as pool:
            def submit(fn, *args):
                future = pool.submit(fn, *args)
                futures.append(future)
                return future
            coordinator = HostControlCoordinator(journal=journal, owner=Owner(),
                select_human_session=lambda *_: 'human-revoked',
                submit_background=submit, revalidate_grant=revalidate, clock=lambda: 103)
            operation = coordinator.submit(ctx, request)
            revoked.set()
            assert approval.resolve_control_consent(
                session_key='human-revoked', request_id=displayed[0]['request_id'],
                intent_digest=operation['intent_digest'], choice='once', now=103,
                presentation_digest=rendered_digest(displayed[0]))
            futures[0].result(timeout=5)
        assert executed == []
        assert journal.get(ctx, operation['operation_id'], profile_id='p1',
                           workspace_id='w1', now=104)['state'] == 'BLOCKED'
    finally:
        approval.unregister_gateway_notify('human-revoked')
