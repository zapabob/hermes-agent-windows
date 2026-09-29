# Hermes GPT Plugin

This plugin adapts `zapabob/hermes-gpt` to Hermes Agent's plugin contract. It
runs as a sidecar and exposes selected Hermes Agent capabilities to MCP clients
without adding new Hermes core model tools.

Enable it first:

```bash
hermes plugins enable hermes-gpt
```

Check the tool surface:

```bash
hermes hermes-gpt status
```

Start stdio mode:

```bash
hermes hermes-gpt serve
```

Start loopback HTTP mode for local MCP clients (no OAuth):

```bash
hermes hermes-gpt serve --http --host 127.0.0.1 --port 7677
```

Default visible MCP tools are read-only or local metadata oriented:
`hermes_read_file`, `hermes_search_files`, `hermes_memory` search,
`hermes_skill_list`, and `hermes_skill_view`.

High-risk tools remain opt-in through environment variables:
`HERMES_GPT_ENABLE_WRITE=1`, `HERMES_GPT_ENABLE_MEMORY_WRITE=1`,
`HERMES_GPT_ENABLE_TERMINAL=1`, and
`HERMES_GPT_ENABLE_SESSION_SEARCH=1`.

## ChatGPT remote connector

Remote access is limited to Streamable HTTP and requires confidential-client
OAuth authorization-code flow with S256 PKCE. The server publishes OAuth
authorization-server and protected-resource metadata, guards `/mcp` with bearer
tokens, and persists issued credentials through the encrypted Hermes token
store. OAuth secrets are never committed to this repository.

Set these values in the active Hermes profile's secret environment file (or
the service environment), not in this README or `config.yaml`:

```text
HERMES_GPT_OAUTH_ENABLE=1
HERMES_GPT_OAUTH_ISSUER=https://<your-public-host>
HERMES_GPT_OAUTH_CLIENT_ID=<ChatGPT client id>
HERMES_GPT_OAUTH_CLIENT_SECRET=<URL-safe secret, 43-128 characters>
HERMES_GPT_OAUTH_REDIRECT_URI=https://chatgpt.com/connector/oauth/callback
HERMES_GPT_OAUTH_SCOPE=hermes
```

The issuer must be a public HTTPS origin with no path. Register the exact
ChatGPT redirect URI in the client configuration. Put a TLS reverse proxy in
front of a loopback-bound process, or provide `--cert` and `--key` when binding
to a non-loopback interface. Do not use the unsafe no-auth override for a
public endpoint. Remote mode refuses to start without valid OAuth settings.

Start the authenticated endpoint behind the configured HTTPS proxy:

```bash
hermes hermes-gpt serve --http --host 127.0.0.1 --port 7677 --profile remote
```

The ChatGPT connector's server URL is `https://<your-public-host>/mcp`.
Write, memory-write, terminal, and session-search capabilities remain gated by
their existing environment switches; OAuth does not enable them automatically.
