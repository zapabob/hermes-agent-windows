"""Trusted host admission: a request cannot become execution without human consent."""
from __future__ import annotations

import logging
import threading
import time

from downstream.control_mcp.contracts import ControlError
from downstream.control_mcp.host_context import run_with_profile_home
from hermes_constants import get_hermes_home
from tools.approval import (cancel_control_consent, request_control_consent,
                            take_control_decision)

logger = logging.getLogger(__name__)


def _record(write, operation_id, **kwargs):
    try:
        write(operation_id, **kwargs)
    except ControlError as exc:
        # A displaced owner has no journal write authority; the live owner's
        # startup reconciliation records this operation.
        logger.warning('control operation %s not recorded: %s', operation_id, exc.code)


class HostControlCoordinator:
    def __init__(self, *, journal, owner, select_human_session,
                 submit_background, revalidate_grant, clock=time.time):
        self.journal = journal
        self.owner = owner
        self.select_human_session = select_human_session
        self.submit_background = submit_background
        self.revalidate_grant = revalidate_grant
        self.clock = clock
        self._lock = threading.RLock()

    def submit(self, ctx, request):
        self.revalidate_grant(ctx, now=self.clock())
        with self._lock:
            operation, created = self.journal.reserve(ctx, request,
                now=self.clock(), with_created=True)
            if not created:
                return operation
            op_id = operation['operation_id']
            try:
                session_key = self.select_human_session(
                    operation['profile_id'], operation['workspace_id'])
                if type(session_key) is not str or not session_key:
                    raise ControlError('human_surface_unavailable')
                binding = self.journal.approval_binding(ctx, op_id, now=self.clock())
                ticket = request_control_consent(binding, session_key=session_key,
                    timeout_seconds=120, now=self.clock())
            except Exception:
                self.journal.withdraw_unpresented(ctx, op_id, now=self.clock())
                raise ControlError('human_surface_unavailable') from None
            armed = threading.Event()
            aborted = threading.Event()
            try:
                profile_home = get_hermes_home()
                self.submit_background(run_with_profile_home, profile_home,
                                       self._await_decision, ctx, op_id, ticket,
                                       armed, aborted)
            except Exception:
                # The executor may have accepted the job before reporting an
                # error. The worker cannot pass its gate until we release it.
                aborted.set()
                armed.set()
                cancel_control_consent(ticket)
                self.journal.mark_admission_unknown(op_id, now=self.clock())
                raise ControlError('host_executor_unavailable') from None
            armed.set()
            return operation

    def _await_decision(self, ctx, operation_id, ticket, armed, aborted):
        armed.wait()
        if aborted.is_set():
            return
        timeout = max(0.0, ticket._entry.deadline - self.clock())
        ticket._entry.event.wait(timeout)
        current = self.clock()
        decision = take_control_decision(ticket, now=current)
        if current >= ticket._entry.deadline:
            _record(self.journal.expire_pending, operation_id, now=current)
            return
        if decision is None:
            return
        try:
            self.revalidate_grant(ctx, now=self.clock())
        except Exception:
            _record(self.journal.block_unexecuted, operation_id, now=self.clock())
            return
        try:
            operation = self.journal.approve(ctx, operation_id, decision,
                                             now=self.clock())
            if operation['state'] == 'APPROVED':
                self.owner.start_approved(ctx, operation_id)
        except ControlError:
            # Revoked/expired grants, stale authority or a conflicting state never execute.
            _record(self.journal.block_unexecuted, operation_id, now=self.clock())
            return
