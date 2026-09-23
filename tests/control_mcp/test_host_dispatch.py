"""Host admission waits for the existing human approval owner before execution."""
from concurrent.futures import ThreadPoolExecutor
import threading


def test_dispatcher_requires_bound_human_decision_once(
        control_module, control_context, tmp_path):
    from downstream.control_mcp.coordinator import HostControlCoordinator
    from tools import approval

    ctx = control_context(scopes=('hermes:read', 'hermes:run:start'))
    journal = control_module('journal').HostControlJournal(tmp_path / 'control.db')
    journal.initialise()
    request = {'kind': 'start_engineering_run', 'profile_id': 'p1', 'workspace_id': 'w1',
               'idempotency_key': 'dispatch-1', 'expected_revision': 'revision-1',
               'source_sha': 'a' * 40, 'parameters': {'task': 'One bounded change'}}
    displayed = []
    executed = threading.Event()
    calls = []

    class Owner:
        def start_approved(self, actual_ctx, operation_id):
            calls.append(operation_id)
            journal.claim_approved(actual_ctx, operation_id, now=104)
            journal.transition(operation_id, expected_state='RUNNING',
                               new_state='SUCCEEDED', now=105)
            executed.set()

    approval.register_gateway_notify('human-dispatch', displayed.append)
    try:
        with ThreadPoolExecutor(max_workers=2) as pool:
            coordinator = HostControlCoordinator(
                journal=journal, owner=Owner(),
                select_human_session=lambda profile, workspace: 'human-dispatch',
                submit_background=pool.submit, clock=lambda: 103)
            first = coordinator.submit(ctx, request)
            second = coordinator.submit(ctx, request)
            assert first['operation_id'] == second['operation_id']
            assert first['state'] == 'PENDING_APPROVAL'
            assert len(displayed) == 1
            assert not executed.is_set()
            assert approval.resolve_control_consent(
                session_key='human-dispatch', request_id=displayed[0]['request_id'],
                intent_digest=first['intent_digest'], choice='once', now=103)
            assert executed.wait(5)
        assert calls == [first['operation_id']]
    finally:
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
        submit_background=lambda *args: None, clock=lambda: 103)
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
            clock=lambda: 103)
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
                submit_background=submit_later, clock=lambda: now[0])
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
