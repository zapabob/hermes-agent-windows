"""Explicit, in-memory startup wiring for the opt-in Control MCP host."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
import time
from types import MappingProxyType

from .auth import HostGrant, ResourceVerifier
from .contracts import ControlError
from .service import HostControlService
from .transport import ControlMCPHost, create_control_mcp


@dataclass(frozen=True)
class ControlMCPStartupConfig:
    """Trusted host inputs supplied by an operator-owned bootstrap path.

    This config deliberately has no file, environment, network, or provider
    credential loader. The application remains disabled unless its bootstrap
    explicitly places one on ``app.state.control_mcp_startup_config``.
    """

    service: HostControlService
    issuer: str
    resource: str
    public_keys: Mapping[str, bytes]
    grant_lookup: Callable[[str, str], HostGrant | None]
    allowed_hosts: tuple[str, ...]
    allowed_origins: tuple[str, ...]
    clock: Callable[[], float] = time.time
    max_token_lifetime: int = 3600

    def __post_init__(self) -> None:
        if (
            type(self.service) is not HostControlService
            or not callable(self.grant_lookup)
            or not callable(self.clock)
            or type(self.allowed_hosts) is not tuple
            or type(self.allowed_origins) is not tuple
        ):
            raise ControlError("invalid_host_configuration")
        if not isinstance(self.public_keys, Mapping):
            raise ControlError("invalid_host_configuration")
        try:
            immutable_keys = MappingProxyType(dict(self.public_keys))
        except (TypeError, ValueError):
            raise ControlError("invalid_host_configuration") from None
        object.__setattr__(self, "public_keys", immutable_keys)


def build_control_mcp_host(config: ControlMCPStartupConfig) -> ControlMCPHost:
    """Build the dedicated-token resource adapter from explicit trusted input."""
    if type(config) is not ControlMCPStartupConfig:
        raise ControlError("invalid_host_configuration")
    verifier = ResourceVerifier(
        issuer=config.issuer,
        resource=config.resource,
        public_keys=config.public_keys,
        grant_lookup=config.grant_lookup,
        max_token_lifetime=config.max_token_lifetime,
    )
    return create_control_mcp(
        config.service,
        verifier=verifier,
        allowed_hosts=config.allowed_hosts,
        allowed_origins=config.allowed_origins,
        clock=config.clock,
    )
