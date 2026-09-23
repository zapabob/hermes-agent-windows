"""Consume the native auxiliary picker; never maintain a second model catalogue."""
from __future__ import annotations

from downstream.implementation_router.routes import ModelRoute, RoutingTable

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
        entries.append((role, ModelRoute(provider.strip(), model.strip())))
    return RoutingTable(True, tuple(entries))
