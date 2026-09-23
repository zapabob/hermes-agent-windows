"""Consume the native auxiliary picker; never maintain a second model catalogue."""
from __future__ import annotations

from downstream.implementation_router.routes import ModelRoute, RoutingTable
from hermes_constants import parse_reasoning_effort

ROLES = ('planner', 'worker', 'reviewer')
SLOTS = {role: f'engineering_{role}' for role in ROLES}


def picker_routes(config: dict) -> RoutingTable:
    entries = []
    auxiliary = config.get('auxiliary', {})
    for role in ROLES:
        raw = auxiliary.get(SLOTS[role], {})
        if not isinstance(raw, dict):
            raise ValueError('Select all engineering models in the native model picker')
        provider, model = raw.get('provider'), raw.get('model')
        if (not isinstance(provider, str) or not isinstance(model, str)
                or not provider.strip() or not model.strip()
                or provider.lower() in {'auto', 'main'} or model.lower() == 'auto'):
            raise ValueError('Select all engineering models in the native model picker')
        effort = raw.get('reasoning_effort')
        if effort is None or (isinstance(effort, str) and not effort.strip()):
            selected_effort = None
        else:
            parsed = parse_reasoning_effort(effort)
            if parsed is None:
                raise ValueError('invalid_engineering_reasoning_effort')
            selected_effort = parsed.get('effort') if parsed.get('enabled') else 'none'
            extra = raw.get('extra_body')
            if isinstance(extra, dict) and 'reasoning' in extra and extra['reasoning'] != parsed:
                raise ValueError('conflicting_engineering_reasoning_settings')
        entries.append((role, ModelRoute(provider.strip(), model.strip(), selected_effort)))
    return RoutingTable(True, tuple(entries))
