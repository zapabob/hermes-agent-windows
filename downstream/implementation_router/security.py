"""Host-only admission contract and zero-ambient-inheritance environment builder.

An admission is a receipt from a TRUSTED native adapter, not sandbox evidence
by itself. Never construct one from a prompt, configuration boolean or model
response. The host must actually own inference authentication, contain all
writers, and protect its credential stores before issuing it. This module
neither launches processes nor supplies that missing native adapter.
"""
from __future__ import annotations

from dataclasses import dataclass

from .routes import RoutingTable

CONTRACT = "host-brokered-credential-free-v1"


@dataclass(frozen=True)
class CredentialFreeAdmission:
    run_id: str
    workspace_id: str
    route_fingerprint: str
    contract: str = CONTRACT


def validate_admission(
    receipt: object, run_id: str, workspace_id: str, routes: RoutingTable,
) -> None:
    if (type(receipt) is not CredentialFreeAdmission
            or receipt.contract != CONTRACT
            or receipt.run_id != run_id or receipt.workspace_id != workspace_id
            or receipt.route_fingerprint != routes.fingerprint()):
        raise ValueError("credential_boundary_unavailable")


# Preserve the existing component import while sharing the native launcher policy.
from tools.environments.credential_free import child_environment  # noqa: F401, E402
