"""Trusted apply owner: one human apply approval, one destination compare-and-swap.

A successful scratch execute and its host verification are evidence for the
apply decision, never authority for it. The destination port is supplied by
the trusted host; no public MCP tool can construct or call this owner.
"""
from __future__ import annotations

import logging
import time
from typing import Protocol

from downstream.control_mcp.contracts import ControlError

logger = logging.getLogger(__name__)


class DestinationPort(Protocol):
    def head(self, ref: str) -> str: ...

    def compare_and_swap(self, ref: str, *, expected: str, candidate_digest: str) -> str:
        """Move ref from expected to the candidate or raise ControlError('destination_changed')."""


def _record(write, operation_id, **kwargs):
    try:
        write(operation_id, **kwargs)
    except ControlError as exc:
        # A displaced owner has no journal write authority; the live owner's
        # startup reconciliation records this operation.
        logger.warning('control operation %s not recorded: %s', operation_id, exc.code)


class VerifiedApplyOwner:
    def __init__(self, *, journal, destination: DestinationPort, receipt_for,
                 revalidate_grant, clock=time.time):
        self.journal = journal
        self.destination = destination
        self.receipt_for = receipt_for
        self.revalidate_grant = revalidate_grant
        self.clock = clock

    def start_approved(self, ctx, operation_id: str) -> dict:
        try:
            request = self.journal.claim_apply(ctx, operation_id, receipt_for=self.receipt_for,
                                               revalidate_grant=self.revalidate_grant,
                                               now=self.clock())
        except ControlError as exc:
            if exc.code == 'revoked_grant':
                _record(self.journal.block_unexecuted, operation_id, now=self.clock())
            raise
        ref = request['parameters']['destination_ref']
        expected = request['expected_revision']
        candidate = request['parameters']['candidate_digest']
        state, reason = 'UNKNOWN', None
        try:
            # Early refusal only; the compare-and-swap below is the destination fence.
            if self.destination.head(ref) != expected:
                state, reason = 'BLOCKED', 'destination_changed'
            else:
                try:
                    new_revision = self.destination.compare_and_swap(
                        ref, expected=expected, candidate_digest=candidate)
                except ControlError as exc:
                    if exc.code != 'destination_changed':
                        raise
                    state, reason = 'BLOCKED', 'destination_changed'
                else:
                    state, reason = 'SUCCEEDED', 'applied'
                    self._witness(operation_id, ref, expected, new_revision, candidate)
        except Exception:
            # The destination write may have landed: keep the reservation for reconcile.
            state, reason = 'UNKNOWN', None
        finally:
            result = None if reason is None else {'state': state, 'reason_code': reason}
            _record(self.journal.transition, operation_id, expected_state='RUNNING',
                    new_state=state, now=self.clock(), result=result)
        if state != 'SUCCEEDED':
            raise ControlError(reason or 'apply_outcome_unknown')
        return result

    def _witness(self, operation_id, ref, expected, new_revision, candidate):
        # Before the outcome transition, which a displaced owner cannot record.
        # A witness failure must not relabel a landed write as unknown.
        try:
            self.journal.append_effect_evidence(operation_id, now=self.clock(), evidence={
                'outcome': 'destination_written', 'destination_ref': ref,
                'previous_revision': expected, 'new_revision': new_revision,
                'candidate_digest': candidate})
        except Exception as exc:
            logger.warning('destination write for %s not witnessed: %s', operation_id,
                           getattr(exc, 'code', type(exc).__name__))
