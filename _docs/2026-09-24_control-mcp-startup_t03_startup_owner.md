# T03 Control MCP existing-host startup evidence

Date: 2026-09-24

## Scope and source

Implementation worktree: `H:\codex-worktrees\hermes-control-mcp-t03-startup`.

Recovered integrator source SHA: `7299159af3bb65224e047a7bab386befa6ed5b33` on `feat/hermes-control-mcp-c-20260923-recovered`.

The change adds an explicit, typed `ControlMCPStartupConfig` in `downstream/control_mcp/startup.py`. Hermes mounts the host during the existing `web_server._lifespan` only when `app.state.control_mcp_startup_config` is set by trusted bootstrap code. Missing config leaves the endpoint unmounted. The public key map is copied into an immutable mapping; malformed keys or config fail before routes or host state are changed. An already supplied host is preserved when config is absent, and conflicts fail closed.

## TDD evidence

Before implementation, the focused production-startup test failed at the intended behavioral assertion: with explicit config, entering `web_server._lifespan` left `app.state.control_mcp_host` unset. The failing assertion was `application.state.control_mcp_host is not None`; the old lifespan only entered a host that had already been injected. This was the qualified RED. A prior pytest invocation that lacked the dev extra and reported `No module named pytest` was setup-only and is not counted as RED.

The final focused test command was:

```powershell
$env:UV_CACHE_DIR='H:\codex-worktrees\hermes-control-mcp-t03-startup\.uv-cache'
uv run --frozen --extra dev --extra slack python -m pytest tests/control_mcp tests/e2e/test_control_mcp_host.py -q --basetemp='H:\t03-control-mcp-pytest-06'
```

Result: `196 passed, 1 skipped`. The real parent SDK E2E initially failed during collection because the environment lacked optional `aiohttp`; rerunning with the lock-pinned `slack` extra supplied that test dependency inside this worktree’s virtual environment. No dependency or lockfile was edited.

`ruff check hermes_cli/web_server.py downstream/control_mcp/startup.py tests/control_mcp/test_mcp_protocol.py` passed.

## CodeGraph evidence

Pinned `@colbymchenry/codegraph@1.6.0` sync completed on the H: worktree after implementation and focused tests. The post-sync status reported `state=complete`, `pendingChanges={added:0, modified:0, removed:0}`, `pendingRefs=0`, `worktreeMismatch=null`, `builtWithVersion=1.6.0`, `lastIndexed=2026-09-24T06:22:08.005Z`, and 8,913 indexed files.

## Limits

The recovered tree contains no production owner for operator public keys or grant lookup. This change adds no grant store, provider credential flow, YAML or environment setting, listener, or default enablement. A trusted application bootstrap must still supply the issuer, resource, public keys, allowed hosts/origins, service, and live grant lookup before any host is mounted. Tests use temporary profiles and test keys; they do not establish production client admission, deployed reachability, or acceptance by Codex or ChatGPT. The host continues to expose the existing read-only surface only.

## Integrator receipt, 2026-09-24

Independent read-only review of H-worktree commit `cfde4e5e6b3aea88c22a3887e8b5169722a93fbf` returned CLEAR/APPROVE with no code findings and independently reran the relevant SDK suite: 196 passed, 1 skipped. The commit was cherry-picked as `995e453e81` onto the recovered integrator. At that integrated source, `uv run --offline --no-sync python -m pytest tests/control_mcp tests/e2e/test_control_mcp_host.py -q --basetemp H:\hermes-control-mcp-integrated-t03-20260924-01` passed with 196 passed, 1 skipped. This is a default-disabled construction seam; no real operator grant source, endpoint enablement, or desktop client was tested. The unrelated untracked T06 pytest output in the integrator was preserved.
