"""Retired engineering workflow compatibility command."""
from __future__ import annotations

import json


def register(ctx):
    def slash(_raw):
        return json.dumps({
            'state': 'BLOCKED',
            'reason_code': 'legacy_engineering_router_retired',
            'migration': 'Use a normal Hermes session and its standard delegation tools.',
            'legacy_operation': {
                'read_tool': 'hermes_get_operation',
                'read_scope': (
                    'Available only with a mounted Control MCP journal and the same '
                    'profile, workspace, client registration, grant revision, '
                    'subject, and resource.'
                ),
                'stop_status': 'NO_PUBLIC_STOP',
                'guidance': (
                    'Inspect the scoped legacy operation. This command cannot stop it. '
                    'Do not replay UNKNOWN; retain its reservation until an operator '
                    'reconciles the owner and journal.'
                ),
            },
        }, ensure_ascii=False)

    ctx.register_command(
        'engineer', handler=slash,
        description='Explain why the former engineering workflow is retired',
        args_hint='',
    )
