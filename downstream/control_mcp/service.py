"""Shared, scoped read facade; unwired controls are never advertised as working."""
from __future__ import annotations

from datetime import datetime, timezone
import time
import uuid

from .contracts import ControlContext, ControlError, MAX_EVIDENCE_BYTES, canonical_json, require_access, valid_id

_READS = {
    'hermes_get_capabilities': (set(), set()),
    'hermes_get_runtime_status': (set(), set()),
    'hermes_get_routes': (set(), set()),
    'hermes_get_run': ({'run_id', 'workspace_id'}, set()),
    'hermes_get_evidence': ({'run_id', 'workspace_id'}, set()),
    'hermes_get_operation': ({'operation_id', 'workspace_id'}, set()),
    'hermes_list_approvals': (set(), set()),
    'hermes_poll_events': (set(), {'after_cursor', 'producer_epoch'}),
}


class HostControlService:
    def __init__(self, *, source, clock=time.time, producer_version='control-mcp/0.1.0', journal=None):
        self.source = source
        self.clock = clock
        self.producer_version = producer_version
        self.producer_epoch = uuid.uuid4().hex
        self.journal = journal

    def read(self, ctx: ControlContext, name: str, args: dict) -> dict:
        if name not in _READS or type(args) is not dict:
            raise ControlError('invalid_request')
        canonical_json(args)
        required, optional = _READS[name]
        required = required | {'profile_id'}
        if not required <= args.keys() or set(args) - required - optional:
            raise ControlError('invalid_request')
        now = self.clock()
        require_access(ctx, scope='hermes:read', profile_id=args['profile_id'],
                       workspace_id=args.get('workspace_id'), now=now)
        profile = args['profile_id']
        for key in ('run_id', 'operation_id'):
            if key in args and not valid_id(args[key]):
                raise ControlError('invalid_resource_id')
        if name == 'hermes_get_capabilities':
            data = {'state': 'AVAILABLE', 'reason': 'read_facade',
                    'capabilities': {'read': True, 'write': False, 'resume': False, 'pause': False,
                                     'live_run_observation': False, 'typed_verification_evidence': False}}
        elif name == 'hermes_get_runtime_status':
            data = self.source.runtime(profile)
        elif name == 'hermes_get_routes':
            data = self.source.routes(profile)
        elif name == 'hermes_get_run':
            data = self.source.run(profile, args['run_id'])
        elif name == 'hermes_get_evidence':
            data = self.source.evidence(profile, args['run_id'])
        elif name == 'hermes_get_operation' and self.journal is not None:
            data = self.journal.get(ctx, args['operation_id'], profile_id=profile,
                                    workspace_id=args['workspace_id'], now=now)
        elif name == 'hermes_poll_events':
            cursor = args.get('after_cursor', 0)
            epoch = args.get('producer_epoch', '')
            if type(cursor) is not int or not 0 <= cursor <= 2**63 - 1 or type(epoch) is not str or len(epoch) > 128:
                raise ControlError('invalid_request')
            data = {'state': 'UNSUPPORTED', 'reason': 'host_event_feed_unwired',
                    'gap': bool(cursor or epoch), 'events': []}
        else:
            data = {'state': 'UNSUPPORTED', 'reason': 'host_control_unwired'}
        result = dict(data)
        result.update(schema_version=1, observed_at=datetime.fromtimestamp(now,timezone.utc).isoformat(),
                      producer_epoch=self.producer_epoch, producer_version=self.producer_version,
                      profile_id=profile)
        canonical_json(result, limit=MAX_EVIDENCE_BYTES)
        return result
