"""Read-only Streamable HTTP adapter using the repository-locked MCP SDK."""
from __future__ import annotations

from contextlib import asynccontextmanager
from dataclasses import dataclass
import json
from urllib.parse import urlsplit

from mcp.server import MCPServer
from mcp.server.transport_security import TransportSecuritySettings
from mcp.types import CallToolResult, TextContent, ToolAnnotations

from .contracts import ControlError
from .http_boundary import AuthenticatedControlASGI, current_control_context


@dataclass(frozen=True)
class ControlMCPHost:
    app: object
    server: MCPServer

    @asynccontextmanager
    async def lifespan(self):
        """The parent host must enter this once; an ASGI mount does not do so."""
        async with self.server.session_manager.run():
            yield


def _read(service, name: str, args: dict) -> CallToolResult:
    try:
        result = service.read(current_control_context(), name, args)
    except ControlError as exc:
        return CallToolResult(
            content=[TextContent(text=exc.code)], isError=True,
        )
    return CallToolResult(
        content=[TextContent(text=json.dumps(result, ensure_ascii=False, separators=(",", ":")))],
        structuredContent=result,
    )


def create_control_mcp(service, *, verifier, allowed_hosts, allowed_origins, clock):
    """Create a bounded resource adapter; the caller owns enablement and mount."""
    server = MCPServer(
        name="Hermes Control",
        instructions=(
            "Inspect capabilities and state first. Control writes require a "
            "separate human decision and are unavailable until the host wires them."
        ),
    )
    readonly = ToolAnnotations(
        readOnlyHint=True, destructiveHint=False, idempotentHint=True,
        openWorldHint=False,
    )

    @server.tool(name="hermes_get_capabilities", annotations=readonly)
    def get_capabilities(profile_id: str) -> CallToolResult:
        return _read(service, "hermes_get_capabilities", {"profile_id": profile_id})

    @server.tool(name="hermes_get_runtime_status", annotations=readonly)
    def get_runtime_status(profile_id: str) -> CallToolResult:
        return _read(service, "hermes_get_runtime_status", {"profile_id": profile_id})

    @server.tool(name="hermes_get_routes", annotations=readonly)
    def get_routes(profile_id: str) -> CallToolResult:
        return _read(service, "hermes_get_routes", {"profile_id": profile_id})

    @server.tool(name="hermes_get_run", annotations=readonly)
    def get_run(profile_id: str, workspace_id: str, run_id: str) -> CallToolResult:
        return _read(service, "hermes_get_run", {"profile_id": profile_id,
                     "workspace_id": workspace_id, "run_id": run_id})

    @server.tool(name="hermes_get_evidence", annotations=readonly)
    def get_evidence(profile_id: str, workspace_id: str, run_id: str) -> CallToolResult:
        return _read(service, "hermes_get_evidence", {"profile_id": profile_id,
                     "workspace_id": workspace_id, "run_id": run_id})

    @server.tool(name="hermes_get_operation", annotations=readonly)
    def get_operation(profile_id: str, workspace_id: str, operation_id: str) -> CallToolResult:
        return _read(service, "hermes_get_operation", {"profile_id": profile_id,
                     "workspace_id": workspace_id, "operation_id": operation_id})

    @server.tool(name="hermes_list_approvals", annotations=readonly)
    def list_approvals(profile_id: str) -> CallToolResult:
        return _read(service, "hermes_list_approvals", {"profile_id": profile_id})

    @server.tool(name="hermes_poll_events", annotations=readonly)
    def poll_events(profile_id: str, after_cursor: int = 0,
                    producer_epoch: str = "") -> CallToolResult:
        return _read(service, "hermes_poll_events", {"profile_id": profile_id,
                     "after_cursor": after_cursor, "producer_epoch": producer_epoch})

    sdk_app = server.streamable_http_app(
        streamable_http_path=urlsplit(verifier.resource).path,
        json_response=True, stateless_http=True,
        transport_security=TransportSecuritySettings(
            enable_dns_rebinding_protection=True,
            allowed_hosts=list(allowed_hosts), allowed_origins=list(allowed_origins),
        ),
        host="localhost",
    )
    app = AuthenticatedControlASGI(
        sdk_app, verifier=verifier, allowed_hosts=allowed_hosts,
        allowed_origins=allowed_origins, clock=clock,
    )
    return ControlMCPHost(app=app, server=server)
