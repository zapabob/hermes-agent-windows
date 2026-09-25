"""Trusted engineering owner for a single approved native workflow invocation.

This adapter receives the registered PluginContext and an existing host executor.
No public MCP tool can construct or call it directly.
"""
from __future__ import annotations

from concurrent.futures import Future
from dataclasses import dataclass
import json
import logging
import threading
import time
import uuid

from downstream.control_mcp.contracts import ControlError
from downstream.control_mcp.host_context import run_with_profile_home
from hermes_constants import get_hermes_home
from tools.interrupt import set_interrupt

logger = logging.getLogger(__name__)


def _record(write, operation_id, **kwargs):
    try:
        write(operation_id, **kwargs)
    except ControlError as exc:
        # A displaced owner has no journal write authority; the live owner's
        # startup reconciliation records this operation.
        logger.warning('control operation %s not recorded: %s', operation_id, exc.code)


@dataclass(frozen=True)
class RunHandle:
    run_id: str
    owner_generation: str
    future: Future


class EngineeringRunOwner:
    def __init__(self, *, journal, plugin_ctx, submit, validate_intent,
                 verify_result, revalidate_grant, clock=time.time):
        self.journal = journal
        self.plugin_ctx = plugin_ctx
        self.submit = submit
        self.validate_intent = validate_intent
        self.verify_result = verify_result
        self.revalidate_grant = revalidate_grant
        self.clock = clock
        self._lock = threading.RLock()
        self._active = {}

    def start_approved(self, ctx, operation_id: str) -> RunHandle:
        try:
            self.revalidate_grant(ctx, now=self.clock())
        except Exception:
            _record(self.journal.block_unexecuted, operation_id, now=self.clock())
            raise ControlError('revoked_grant') from None
        request = self.journal.claim_approved(ctx, operation_id, now=self.clock())
        run_id = 'eng-' + uuid.uuid4().hex
        generation = uuid.uuid4().hex
        # The request is an immutable journal copy. The owner validates the
        # actual source/policy/route before the native entrypoint can execute.
        with self._lock:
            self._active[run_id] = {'generation': generation, 'thread_id': None,
                                    'cancel_requested': False}
        profile_home = get_hermes_home()
        armed = threading.Event()
        aborted = threading.Event()
        try:
            future = self.submit(self._run_if_armed, profile_home, armed, aborted,
                                 run_id, generation, operation_id, request, ctx)
        except Exception:
            # A scheduler may accept the job and then lose its acknowledgement.
            # Its worker must observe aborted before it can enter native code.
            aborted.set()
            armed.set()
            with self._lock:
                self._active.pop(run_id, None)
            _record(self.journal.transition, operation_id, expected_state='RUNNING',
                    new_state='UNKNOWN', now=self.clock())
            raise ControlError('host_executor_unavailable') from None
        armed.set()
        return RunHandle(run_id, generation, future)

    def _run_if_armed(self, profile_home, armed, aborted, run_id, generation,
                      operation_id, request, ctx):
        armed.wait()
        if aborted.is_set():
            return {'state': 'UNKNOWN', 'run_id': run_id}
        return run_with_profile_home(profile_home, self._execute, run_id,
                                     generation, operation_id, request, ctx)

    def _execute(self, run_id, generation, operation_id, request, ctx):
        tid = threading.get_ident()
        with self._lock:
            active = self._active.get(run_id)
            if active is None or active['generation'] != generation:
                raise ControlError('operation_conflict')
            active['thread_id'] = tid
            if active['cancel_requested']:
                set_interrupt(True, tid, reason='control_cancel')
        state = 'UNKNOWN'
        result = {'state': 'UNKNOWN', 'run_id': run_id}
        try:
            try:
                self.revalidate_grant(ctx, now=self.clock())
                grant_valid = True
            except Exception:
                grant_valid = False
            if not grant_valid or self.validate_intent(request) is not True:
                state = 'BLOCKED'
                result = {'state': state, 'run_id': run_id}
            elif self._cancelled(run_id, generation):
                state = 'BLOCKED'
                result = {'state': state, 'run_id': run_id}
            else:
                from .entrypoint import run_workflow
                raw = run_workflow(self.plugin_ctx,
                    {'workspace': request['workspace_id'],
                     'task': request['parameters']['task']},
                    run_id=run_id, operation_id=operation_id)
                parsed = json.loads(raw)
                if (type(parsed) is dict and parsed.get('run_id') == run_id
                        and parsed.get('state') in ('SUCCEEDED', 'FAILED', 'BLOCKED')):
                    state = parsed['state']
                    result = parsed
                    if state == 'SUCCEEDED' and (self._cancelled(run_id, generation)
                                                 or self.verify_result(request, operation_id, run_id, parsed) is not True):
                        state = 'UNKNOWN'
                        result = {'state': state, 'run_id': run_id}
        except Exception:
            # The native owner may have crossed an external-effect boundary.
            # Keep the workspace reservation for explicit reconciliation.
            state = 'UNKNOWN'
            result = {'state': state, 'run_id': run_id}
        finally:
            with self._lock:
                active = self._active.get(run_id)
                if active is not None and active['generation'] == generation:
                    set_interrupt(False, tid)
                    del self._active[run_id]
            _record(self.journal.transition, operation_id, expected_state='RUNNING',
                    new_state=state, now=self.clock(),
                    result=result if state != 'UNKNOWN' else None)
        return result

    def _cancelled(self, run_id, generation):
        with self._lock:
            active = self._active.get(run_id)
            return (active is not None and active['generation'] == generation
                    and active['cancel_requested'])

    def cancel(self, run_id: str, owner_generation: str) -> bool:
        """Signal only the matching live generation; acknowledgement is not quiescence."""
        with self._lock:
            active = self._active.get(run_id)
            if active is None or active['generation'] != owner_generation:
                return False
            active['cancel_requested'] = True
            if active['thread_id'] is not None:
                set_interrupt(True, active['thread_id'], reason='control_cancel')
            return True
