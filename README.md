# Hermes Agent Windows Workstation Edition

A native Windows workspace for Hermes: an Electron desktop, CLI and messaging
gateway, with optional local inference, memory, voice and automation integrations.

This is the independent Windows downstream maintained at
[zapabob/hermes-agent-windows](https://github.com/zapabob/hermes-agent-windows).
The original [Hermes Agent](https://github.com/NousResearch/hermes-agent) is
developed by Nous Research. This fork is not endorsed by Nous Research.
Both the upstream attribution and the [MIT licence](LICENSE) are retained.

**Current source version: 0.21.1.** This is a downstream patch version; the
recorded upstream release remains 0.21.0. A source version or a main-branch push
does not establish that a stable installer has been published.

日本語: Windows向けの独立派生版です。今回のソース版は **0.21.1** です。
下のPowerShell手順から導入できます。既存環境の更新前には作業差分と各プロファイルを保存してください。
旧版の詳説は [日本語](README.ja.md)・[简体中文](README.zh-CN.md) にあります。
今回の版番号と検証状況は、このREADMEを参照してください。

## Start from source

The target is Windows 11 x64. Use PowerShell, Git, `uv`, and Python 3.11–3.13.
Dependency installation can take several minutes and may require native build
tools for optional extras. WSL is not required for the native application.

```powershell
git clone https://github.com/zapabob/hermes-agent-windows.git
Set-Location hermes-agent-windows
uv sync --locked --all-extras
uv run hermes setup
uv run hermes chat
```

The setup wizard selects a model provider. A GPU is optional when using a
remote provider. Local models require separately supplied model files and a
compatible inference runtime; this repository does not include model weights.

To launch Desktop from the same checkout:

```powershell
uv run hermes desktop
```

For an installer or portable archive, consult the
[downstream Releases page](https://github.com/zapabob/hermes-agent-windows/releases).
Use only an actually published asset with its matching manifest and checksums.
The Windows release workflow produces a per-user NSIS installer and a portable
archive when its publication gates are satisfied; local source builds are separate.
The [installation guide](docs/windows/INSTALL.md) describes the layout and
verification procedure; older version examples are not evidence of a 0.21.1 release.

## What lives in this fork

| Area | Implementation and entry points |
| --- | --- |
| Desktop and terminal | Electron UI, profile-aware Python backend, native process and terminal handling in `apps/desktop/`, `tui_gateway/` and `tools/` |
| CLI and messaging | Shared agent runtime with CLI and platform adapters in `hermes_cli/` and `gateway/` |
| Local inference | llama.cpp/GGUF launch and hot-swap helpers under `scripts/windows/`; models remain operator configuration |
| Recovery | External [Go watchdog](scripts/windows/watchdog-go/README.md) with explicit process ownership |
| Memory and retrieval | Profile-scoped state, memory-provider extensions and optional embedding services |
| Optional capabilities | Plug-ins for voice, browser work, research, avatars and Unity/VR workflows |

The [integration inventory](docs/windows/INTEGRATIONS.md) retains the plug-in
and submodule catalogue. These integrations have their own dependencies and
configuration. They are not all enabled or qualified by installing the CLI.
The feature ledger is [FEATURES.yaml](FEATURES.yaml); direct carried changes are
tracked in [CARRY.yaml](CARRY.yaml).

## Changes in the 0.21.1 work

Windows background Git and web helper calls use hidden-process creation flags
to avoid opening separate console windows. The Git wrapper also separates
non-interactive probes from the user-facing terminal. This addresses known
helper launch paths; it is not a claim that every possible console source has
been eliminated.

Credential leases remain bound to the selected entry, and an empty credential
pool cannot silently start a delegated child with an inherited client.
Telemetry consent follows the owning profile. Process completion and
delegation work preserves parent ownership, durable results and retry state.
Desktop backend exit handling checks the identity of the child it owns.

The reviewed local feature set also includes paused-at-creation cron jobs,
explicit MCP device login, foreign-session browsing/import, and Desktop media,
todo and capability-scope handling. A similarity to upstream code is not used
as a substitute for testing these contracts.

## Build Desktop

Use a Node.js version accepted by
[`apps/desktop/package.json`](apps/desktop/package.json). Install JavaScript
dependencies at the repository root; Desktop is an npm workspace.

```powershell
npm ci
npm run typecheck --workspace apps/desktop
npm run build --workspace apps/desktop
```

The build produces application files. Packaging and installing a new Desktop
binary are separate operations. Do not infer the running version from source
files alone, and do not replace an executable while its process is running.

## Update an existing workstation

Save uncommitted source work before changing commits. Keep credentials,
profile databases, model files and local operational records out of commits.
Record the current commit and retain a rollback copy of the deployed Desktop.

Review the selected downstream commit, test it, then update the checkout and
rebuild the application. Restart only services whose executable path and
process identity are confirmed. The Desktop control backend, messaging gateway,
llama server, embedding server and Go watchdog have distinct lifecycles;
closing one window does not establish that all of them restarted.

After restarting, check the application window, backend response and actual
model readiness. A listening port alone does not prove a successful agent turn.
See [local runtime configuration](docs/local-secretary-runtime.md) and the
[watchdog documentation](scripts/windows/watchdog-go/README.md).

## Validation status and limits

The 2026-09-08 local Windows work has recorded Desktop type checking and 28
focused Desktop tests, native child-process spawn/kill tests, hidden-console
helper probes, credential-routing tests, and loopback completion/OAuth tests.
These are scoped checks, not qualification of every optional integration.

The initial combined Python run had failures and skips. Individual reruns
separated missing test dependencies, blocked test-only loopback traffic,
fixture synchronisation and real integration defects. Skipped POSIX permission
tests do not establish Windows ACL correctness.

Full upstream-history adoption, all private security contracts, clean-machine
installation, signed artifacts, exact-head hosted CI and complete Desktop
first-run readiness remain separate gates. An isolated packaged first-run
probe reached the backend but remained on onboarding; that path is not yet
qualified. Do not interpret this README, a build, or a version bump as a
COMPLETE or stable-release certificate.

## Frozen comparisons and contribution policy

For the 2026-09-08 implementation campaign, the fork comparison base is
`20c7dd9d87fc6d0dc6b5cb2ed675e139b788be34` and the upstream comparison endpoint is
`6e2b8e070d28b1a3381a3fb290b6b8d6cce13cef`. Neither is replaced by a moving main.
The older upstream release/snapshot fields in
[`downstream/distribution.json`](downstream/distribution.json) retain their
own provenance; they are not the campaign endpoint.

Integrate missing behaviour through its canonical owner. Preserve the fork's
profile isolation, prompt caching, approval boundaries and demonstrated
features. Do not use a wholesale upstream merge, rebase or cherry-pick as a
substitute for contract review.

Read [AGENTS.md](AGENTS.md) before implementation. The campaign pins CodeGraph
1.6.0 and obtains its CLI/MCP schema from the installed executable. An index
with extraction limits is incomplete evidence, even if it has no pending
references. See the [release policy](docs/windows/RELEASE_POLICY.md) for the
separate publication gates.
