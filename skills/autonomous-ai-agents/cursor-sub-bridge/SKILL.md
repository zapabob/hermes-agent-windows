---
name: cursor-sub-bridge
description: "Bridge Hermes to Cursor subscription via local MCP."
version: 1.0.0
author: zapabob, Hermes Agent
license: MIT
platforms: [linux, macos, windows]
metadata:
  hermes:
    tags: [Cursor, Subscription, MCP, Local-Proxy, Bridge]
    category: autonomous-ai-agents
    related_skills: [hermes-agent, freellmapi-free-tier]
---

# Cursor Sub Bridge Skill

Route Hermes chat completions through a loopback OpenAI shim. A live Cursor
Agent session answers each request with the Cursor subscription model via MCP
`cursor_sub_poll` / `cursor_sub_respond`. There is no public Cursor Chat API;
this bridge is interactive only.

## When to Use

- You want Hermes to spend Cursor subscription quota instead of a cloud API key
- You can keep a Cursor Agent chat open to drain the queue
- You accept that gateway / cron / unattended Desktop must NOT use this provider

## Prerequisites

- Checkout with `plugins/cursor_sub_bridge/` and `plugins/model-providers/cursor-sub/`
- Plugin enabled: `hermes plugins enable cursor_sub_bridge`
- `.env` contains `CURSOR_SUB_BRIDGE_API_KEY=local-cursor-sub` (or your own shared secret)
- Optional: `CURSOR_SUB_BRIDGE_BASE_URL=http://127.0.0.1:48771/v1`

## How to Run

1. Start the shim:

```
terminal(command="hermes cursor-sub serve")
```

2. In Cursor Settings → MCP, add a stdio server (repo-relative path OK):

```json
{
  "mcpServers": {
    "cursor-sub-bridge": {
      "command": "py",
      "args": ["-3", "-m", "plugins.cursor_sub_bridge", "mcp"],
      "cwd": "C:/Users/downl/Documents/New project/hermes-agent"
    }
  }
}
```

Use the real checkout / worktree path for `cwd`. On this machine the feature
worktree is under `.worktrees/feat-cursor-sub-mcp-proxy` until merged.

3. Open a Cursor Agent chat and instruct it to loop:

```
Call cursor_sub_poll. If a request appears, answer the messages, then
cursor_sub_respond with the same id. Repeat until I stop you.
```

4. Point Hermes at the shim (config.yaml):

```yaml
model:
  provider: cursor-sub
  default: cursor-sub/default
```

Or named provider form:

```yaml
providers:
  cursor-sub:
    api: http://127.0.0.1:48771/v1
    api_key: local-cursor-sub
```

5. Health check:

```
terminal(command="hermes cursor-sub doctor")
```

## Quick Reference

| Action | Command |
|--------|---------|
| Serve OpenAI shim | `hermes cursor-sub serve` |
| MCP drain (stdio) | `hermes cursor-sub mcp` |
| Queue status | `hermes cursor-sub status` |
| Doctor | `hermes cursor-sub doctor` |
| Module entry | `py -3 -m plugins.cursor_sub_bridge serve` |

## Procedure

1. Enable plugin and set the shared loopback API key in `.env`.
2. Start `hermes cursor-sub serve` (binds `127.0.0.1:48771` only).
3. Register the MCP server in Cursor and start an Agent drain loop.
4. Set `model.provider=cursor-sub` for an interactive CLI/Desktop session.
5. Send a Hermes prompt; confirm `cursor_sub_poll` receives messages and
   `cursor_sub_respond` unblocks the shim.

## Pitfalls

- If no Agent calls poll/respond, the shim returns HTTP 504 after
  `CURSOR_SUB_BRIDGE_TIMEOUT` (default 1800s).
- Non-loopback bind hosts are refused.
- Streaming (`stream: true`) is not supported.
- Do not expose port 48771 via Tailscale Funnel or LAN.
- Product ToS may restrict headless reuse of subscription models — keep this
  interactive and personal-machine only.
- Queue files live under `{HERMES_HOME}/cursor_sub/` via `get_hermes_home()`.

## Verification

```
terminal(command="hermes cursor-sub doctor")
terminal(command="hermes cursor-sub status")
```

Expect `ok: true`, writable queue, and pending count returning to 0 after a
successful poll/respond round-trip.
