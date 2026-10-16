# MCP 2.2 update and endpoint migration

The pinned MCP SDK moves from 2.0.0 to 2.2.0 to include the upstream
CVE-2026-59951 session-retention fix. Stateful servers have bounded live
sessions and idle-session reclamation. Hermes' existing stateless servers
remain stateless; the update does not turn session persistence on.

## Redirects and existing endpoints

SDK 2.2 follows redirects within the configured origin and refuses redirects
to a different host or port, or from HTTPS to HTTP. This applies even when
`strict_redirect_headers: false` was previously used to allow forwarding
custom headers. That option cannot override the SDK's origin boundary.
An existing endpoint that redirects to another origin needs an explicit
configuration change after the update.

The MCP connection status includes the SDK's explanation and the proposed
endpoint: `use that URL as the endpoint`. Verify the intended endpoint with
the server operator before changing `mcp_servers.<name>.url` in the active
profile's `config.yaml`. Keep the existing server name and other settings.
Only retain credentials that are intended for the verified destination;
the redirect itself does not authorize sending credentials there.

After saving, use `/mcp refresh` in the CLI or restart the consuming Hermes
instance. This closes the old transport, clears its connection cooldown,
and discovers the saved endpoint afresh. With OAuth, authorize again when
requested for the changed endpoint. Existing generation fences reject a
pending authorization for the former configuration, including A→B→A
configuration changes. No automatic URL rewrite or credential forwarding
to the redirect destination is performed.

The native regression exercises public discovery and status on the old
redirecting endpoint, verifies that no request reaches the other origin,
then saves the explicit final endpoint, closes the old loop, discovers
again, and completes a nonce-bound tool call. Separate native OAuth tests
cover callback, refresh, stale-writer rejection and final teardown. The
credentials and peers used by these tests are synthetic loopback fixtures.
