# Hermes Agent Windows Workstation Edition

<p align="center">
  <a href="README.md" lang="en-GB"><strong>King's English</strong></a> ·
  <a href="README.ja.md" lang="ja">日本語</a> ·
  <a href="README.zh-CN.md" lang="zh-CN">简体中文</a>
</p>

> [!NOTE]
> This English `README.md` is the canonical project overview. The Japanese and
> Simplified Chinese READMEs mirror the same product boundaries and installation
> contract.

An unofficial, Windows-native downstream of Hermes Agent for people who run
Hermes as a long-lived Windows workstation service: Electron Desktop, CLI,
messaging gateway, profiles, local inference, semantic memory, automation and
optional workstation integrations from one source tree.

This single-maintainer fork is independent of, and not endorsed by, Nous Research.
The downstream is maintained at
[zapabob/hermes-agent-windows](https://github.com/zapabob/hermes-agent-windows).
The original [Hermes Agent](https://github.com/NousResearch/hermes-agent) is
developed by Nous Research. Both the upstream attribution and the
[MIT licence](LICENSE) are retained.

[![Windows Workstation Tier-1 CI](https://github.com/zapabob/hermes-agent-windows/actions/workflows/fork-cicd.yml/badge.svg)](https://github.com/zapabob/hermes-agent-windows/actions/workflows/fork-cicd.yml)

**Current source version: 0.21.5.** Product metadata is aligned with upstream
stable R2 `f97608f178d1ffeca59860195ab7da295f7c8e5f`
(`v2026.9.24`). The downstream still owns its own release identity
(`version_source: downstream`) and retains the historical frozen provenance
snapshot `b51c055a12220f8c7c18660e8599365012e19532`.

The 0.21.5 version string does **not** claim blanket semantic parity with every
later upstream commit. The current semantic-refresh campaign is mapped
contract-by-contract through frozen ceiling
`678a4762b887f3eabe5cad11254b2ab1ae859485`; open families remain open until
their source, tests, mutation evidence, CodeGraph binding and review are closed.
See [the current handoff plan](docs/windows/semantic-refresh-20260926/CURSOR_IMPLEMENTATION_PLAN_20260929.md).

日本語: Windows向けの独立派生版です。今回のソース版は **0.21.5**（上流記録も 0.21.5）です。
下のPowerShell手順から導入できます。既存環境の更新前には作業差分と各プロファイルを保存してください。
旧版の詳説は [日本語](README.ja.md)・[简体中文](README.zh-CN.md) にあります。
今回の版番号と検証状況は、このREADMEを参照してください。
If this Windows-native downstream is useful to you, consider starring the repository — it helps other Windows users discover the project.
このWindowsネイティブ版が役に立ったら、Starで応援していただけると、他のWindowsユーザーにも見つけてもらいやすくなります.

## Setup in 30 seconds

> **TL;DR:** clone the downstream, install the locked environment, configure a
> provider, then start CLI chat. Optional plug-ins and local models can be added
> later.

<<<<<<< HEAD
<details open>
<summary><strong>日本語</strong></summary>

Windows向け独立派生版のソースは0.21.5です。導入手順は第11節をご覧ください。
安定版の公開、署名、クリーン環境の検証は、それぞれ別に確認する必要があります。

</details>
<details>
<summary><strong>简体中文</strong></summary>

这是独立维护的 Windows 衍生版本，当前源码版本为0.21.5。
请参阅第11节安装步骤；源码构建不代表已发布经过完整验证的稳定安装包。

</details>

## 1. Product identity

The source and release identity is Windows Workstation Edition 0.21.5.
Upstream provenance remains independent of the downstream semantic version.

## 2. Windows-first goals

Run directly on Windows with profile isolation, hidden background helpers,
native terminal handling and explicit ownership of restarted processes.

## 3. Who this is for

Windows users who need Desktop, CLI or messaging surfaces and can configure
a remote provider or separately supplied local model runtime.

## 4. Downstream advantages

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

## 5. Verified feature matrix

| Area | Implementation and entry points |
| --- | --- |
| Desktop and terminal | Electron UI, profile-aware Python backend, native process and terminal handling in `apps/desktop/`, `tui_gateway/` and `tools/` |
| CLI and messaging | Shared agent runtime with CLI and platform adapters in `hermes_cli/` and `gateway/` |
| Local inference | llama.cpp/GGUF launch and hot-swap helpers under `scripts/windows/`; models remain operator configuration |
| Recovery | External [Go watchdog](scripts/windows/watchdog-go/README.md) with read-only status and explicit auxiliary ownership; supported destructive scope is watchdog-owned embedding only |
| Memory and retrieval | Profile-scoped state, memory-provider extensions and optional embedding services |
| Optional capabilities | Plug-ins for voice, browser work, research, avatars and Unity/VR workflows |

The [integration inventory](docs/windows/INTEGRATIONS.md) retains the plug-in
and submodule catalogue. These integrations have their own dependencies and
configuration. They are not all enabled or qualified by installing the CLI.
The feature ledger is [FEATURES.yaml](FEATURES.yaml); direct carried changes are
tracked in [CARRY.yaml](CARRY.yaml).

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

## 6. Windows Tier-1 support contract

Windows 11 x64 is the primary target. Native Python, Desktop, installer,
portable, upgrade, watchdog and security checks are separate gates.
Mock-only results and skipped P0 tests cannot qualify Windows support.

## 7. Local AI architecture

The Desktop and gateway can use a remote provider or an operator-managed
llama.cpp server. Hot-swap presets select independently installed GGUF files.
Inference readiness requires a real model response, not only an open port.

## 8. Watchdog and recovery architecture

The Desktop Python backend lifecycle is owned exclusively by Electron main in
the supported Windows topology. Health observation, a PID, a port, a token or
a manifest do not confer destructive lifecycle authority on another component.

The external Go watchdog is an auxiliary supervisor with a read-only status
surface. Its supported destructive scope is limited to an embedding
`llama-server` instance that it explicitly launched and owns; it is not a
second Desktop-backend owner. Legacy watchdog backend-prewarm compatibility
paths are deprecated, disabled in the supported topology and do not qualify as
Windows Tier-1 evidence. See the
[watchdog guide](scripts/windows/watchdog-go/README.md) and the
[Windows platform contract](.codex/WINDOWS_PLATFORM_CONTRACT.md).

## 9. Memory and semantic retrieval

Profiles scope configuration, credentials, sessions and memory. Embedding
services and memory providers are optional and need their own configuration.
No model files or personal memory are included in the source distribution.

## 10. VRChat, Unity, and voice integrations

Avatar, Unity/VRChat and voice plug-ins remain optional integrations. Their
SDKs, applications and hardware must be configured separately. The retained
[inventory](docs/windows/INTEGRATIONS.md) records available integration paths;
it does not certify every path on the current workstation.

## 11. Installation

The target is Windows 11 x64. Use PowerShell, Git, `uv`, and Python 3.11–3.13.
Dependency installation can take several minutes and may require native build
tools for optional extras. WSL is not required for the native application.
=======
Windows 11 x64, PowerShell, Git, `uv` and Python 3.11–3.13 are the native
baseline. Node.js is only required when building Desktop from source.
>>>>>>> origin/main

```powershell
git clone https://github.com/zapabob/hermes-agent-windows.git
Set-Location hermes-agent-windows
uv sync --locked --all-extras
uv run hermes setup
uv run hermes chat
```

Start the packaged Desktop flow from the same checkout with:

```powershell
uv run hermes desktop
```

For an installer or portable ZIP, first confirm that the matching asset exists on
the [downstream Releases page](https://github.com/zapabob/hermes-agent-windows/releases)
and verify `SHA256SUMS.txt`. The canonical Windows procedure is
[docs/windows/INSTALL.md](docs/windows/INSTALL.md).

<details open>
<summary><strong>日本語</strong></summary>

Windows向け独立派生版の現在のソース版は **0.21.5** です。CLI、Electron Desktop、
複数profile、Gateway、OAuth/API key/local llama.cpp、Semantic Graph/Ebbinghaus、
Windows固有のruntime管理を同じHermes coreの上で扱います。0.21.5という版番号は
進行中の上流semantic refresh全件の完了宣言ではありません。詳しくは
[日本語版README](README.ja.md) と
[Windows導入ガイド](docs/windows/INSTALL.md) を参照してください。

</details>
<details>
<summary><strong>简体中文</strong></summary>

当前 Windows 下游源码版本为 **0.21.5**。CLI、Electron Desktop、多 profile、
Gateway、OAuth/API key/local llama.cpp、Semantic Graph/Ebbinghaus 与 Windows
runtime 管理共用同一 Hermes core。版本号 0.21.5 并不表示正在进行的上游
semantic refresh 已全部完成。参见
[简体中文 README](README.zh-CN.md) 与
[Windows 安装指南](docs/windows/INSTALL.md)。

</details>

## What this fork adds

- **Native Windows as a first-class target.** Windows path handling, process
  identity, PowerShell transport, NTFS behaviour, Electron IPC, update recovery,
  installer/portable flows and the Go watchdog have native Windows tests.
- **One Desktop backend owner.** Electron main owns the destructive Desktop
  backend lifecycle. Other components may observe health, but they do not become
  a second backend owner merely because they can see a PID, port or token.
- **Local inference without replacing the Hermes provider model.** The same model
  picker can use remote providers, OAuth-backed providers or local llama.cpp/GGUF.
  Generation and embedding are separate services with separate lifecycle evidence.
- **Provider choice remains normal Hermes behaviour.** OpenAI Codex OAuth,
  Qwen OAuth, xAI, Anthropic, OpenRouter, Nous, Gemini, local/custom endpoints and
  other bundled providers live in the normal provider registry. Fallback chains,
  delegation, MoA and reasoning effort remain independent user-configured
  capabilities.
- **Semantic and cognitive memory.** Semantic Graph supplies graph storage,
  embeddings and hybrid retrieval. Ebbinghaus supplies a separate cognitive
  memory provider through the official memory-provider seam.
- **Desktop workflows that stay on official session/profile contracts.** The
  Desktop includes profile-aware sessions, model/effort controls, Git/review
  surfaces, Security Center and Bot Mode. Bot Mode resolves one canonical
  forever-chat per bot by `(profile, "Bot Chat")`, rather than storing a fragile
  canonical session-id pointer.
- **Long-running messaging and automation.** Gateway platforms, cron, profiles,
  skills, MCP, delegation, kanban and scheduled work share the same core state
  model instead of being separate downstream agents.
- **Workstation integrations at the edges.** VRChat/Unity, voice/TTS, AITuber,
  OSINT/Shinka, local research, Office and other integrations are plug-ins or
  optional components rather than hard-wired core dependencies.
- **Local workstation security.** The Windows Security Center provides scanning,
  evidence, update state and encrypted quarantine with explicit confirmation for
  mutations.
- **Evidence-driven upstream adoption.** Upstream changes are mapped by observable
  behaviour and exact frozen SHAs. This fork does not use a blind merge/rebase as
  proof of compatibility.

## Plug-ins and Git submodules

Hermes capabilities are discovered through the normal plug-in registry. Run:

```powershell
uv run hermes plugins
```

to see the actual enabled inventory for the active profile. The repository
contains top-level workstation plug-ins plus specialised provider families under
`plugins/model-providers/`, `plugins/memory/`, `plugins/platforms/`,
`plugins/web/` and related directories. The current tree includes dozens of
model providers and messaging adapters; runtime enablement still depends on
profile configuration and credentials.

Representative downstream plug-ins include:

| Area | Examples |
| --- | --- |
| Desktop / agent operations | `hermes-bot-mode`, `desktop-dashboard`, `hermes-gpt`, `hermes-antigravity`, `implementation_router` |
| Memory / knowledge | `semantic_graph`, `memory/ebbinghaus`, `memory_llm_wiki`, `surfsense` |
| Local media / XR | `voicevox_tts`, `irodori_tts`, `vrchat-autonomy`, `unity_vrchat_bridge`, `aituber_onair` |
| Research / OSINT | `shinka-osint`, `sitdeck-osint`, `world-intel-osint`, `worldmonitor-osint` |
| Providers / web | `openai-codex`, `qwen-oauth`, `xai`, `hypura`, `cloakbrowser`, `scrapling` |

`implementation_router` is **opt-in**. It is an isolated sequential engineering
workflow that uses the existing auxiliary picker and parent-owned inference. It
does not replace the normal model picker, ordinary delegation, MoA or provider
fallback. It never applies its verified workspace to the source checkout and
never publishes a PR by itself.

Git submodules are optional integrations. Initialise them only when you need the
corresponding external runtime:

```powershell
git submodule update --init --recursive
```

The broader integration inventory is tracked in
[docs/windows/INTEGRATIONS.md](docs/windows/INTEGRATIONS.md). That document is a
snapshot; `uv run hermes plugins` is the better runtime inventory.

## 1. Product identity

Hermes Agent Windows Workstation Edition is a Windows-first downstream
distribution built on the Hermes core. It keeps upstream CLI/session/profile,
provider, tool, skill, MCP and gateway contracts while adding Windows runtime
policy and workstation integrations through downstream-owned edges.

The product ledger is [FEATURES.yaml](FEATURES.yaml). Direct changes carried in
upstream-owned files are tracked in [CARRY.yaml](CARRY.yaml), and upstream
adoption decisions are tracked in `UPSTREAM_ADOPTION.yaml`.

The downstream product version and upstream semantic-adoption state are separate
facts. Version 0.21.5 records the product/release identity; the semantic-refresh
ledger records which upstream behaviours have actually been reviewed and adopted.

## 2. Windows-first goals

The primary runtime target is native Windows 11 x64 with Python, Electron/Node,
PowerShell and optional consumer NVIDIA hardware. WSL is not required for the
main application.

Windows support covers more than path syntax. It includes process incarnation,
locked executables, PowerShell quoting, CP932/UTF-8 boundaries, CRLF, native venv
`Scripts\`, Electron stdio/IPC, scheduled start-up, sleep/resume, update
handoff and loopback service recovery.

Native Windows evidence is kept separate from Linux cross-compilation and from
GPU-less hosted CI.

## 3. Who this is for

This downstream is for operators and developers who want source-level control of
an always-on Windows Hermes workstation: Desktop, local models, multiple profiles,
gateway services, memory, automation and specialised plug-ins.

If you want the simplest official Hermes installation and upstream support model,
use the original project linked in section 15.

## 4. Downstream advantages

The main downstream properties are behavioural rather than cosmetic:

- provider-agnostic auth through the normal picker, including OAuth, API keys and
  local/custom endpoints;
- Windows-native process and update contracts;
- separate, testable lifecycle ownership for Desktop backend, generation model,
  embedding model, gateway, dashboard and watchdog;
- Semantic Graph and Ebbinghaus memory extensions through official seams;
- profile isolation for config, credentials, sessions, memory and gateway state;
- Desktop Bot Mode using a name-based canonical chat registry instead of a
  persisted session-id pin;
- downstream Security Center and security regression coverage;
- optional workstation plug-ins for XR, voice, AITuber, research and OSINT;
- semantic upstream adoption with exact frozen inputs and evidence receipts.

The fork does not create a second source of truth for sessions, profiles, model
catalogue, approvals, gateway state or the tool registry.

## 5. Verified feature matrix

| Area | Current implementation | Evidence / contract |
| --- | --- | --- |
| Windows runtime | Native path/process/IPC/update helpers | `tests/downstream/test_windows_contracts.py` |
| Desktop backend | Electron main is the single destructive lifecycle owner | `apps/desktop/electron/single-owner-backend-lifecycle.test.ts` |
| Desktop Bot Mode | One canonical `Bot Chat` registry row per profile/bot | `apps/desktop/src/plugins/hermes-bots/tests/canonical-chat-registry.test.mjs`, `tests/tui_gateway/test_profiles_list_canonical_session.py` |
| Recovery | External Go watchdog with exact-identity lifecycle fencing | `scripts/windows/Start-HermesGoWatchdog.ps1`, `scripts/windows/watchdog-go/*_test.go` |
| Local inference | llama.cpp/GGUF launch, fallback and hot-swap surfaces | `tests/hermes_cli/test_llama_fallback_runtime.py` |
| Local embeddings | Watchdog-owned embedding lifecycle | `scripts/windows/watchdog-go/embedding_test.go` |
| Providers | Normal Hermes provider registry, OAuth/API-key/custom/local routes | `plugins/model-providers/` |
| Provider resilience | Explicit fallback chains and provider rotation | `tests/hermes_cli/test_fallback_chain.py` |
| Memory | Semantic Graph + Ebbinghaus provider | `tests/plugins/test_semantic_graph_registration.py`, `tests/plugins/test_ebbinghaus_plugin.py` |
| Profiles / gateway | Profile-scoped state and multi-platform messaging | `gateway/`, `tests/tui_gateway/` |
| Automation | Cron, delegation, kanban, skills and MCP on the shared core | `cron/`, `plugins/kanban/`, `tools/delegate_tool.py` |
| Desktop tooling | Git/review and profile-aware Desktop surfaces | `apps/desktop/electron/git-review-ops.test.ts` |
| Security | Security Center, approval fences and security regression tests | `docs/windows/SECURITY_CENTER.md`, `downstream/security/` |
| Optional engineering sandbox | `implementation_router` uses explicit picker routes and isolated workspaces | `plugins/implementation_router/` |
| Control MCP | Auth/journal/coordinator contracts implemented; production write still disabled | `docs/control-mcp/IMPLEMENTATION_LOG.md` |

`FEATURES.yaml` is the product ledger for verified/retired downstream features.
Test counts and local green runs are evidence for their bounded contracts, not a
claim that every optional integration or every upstream commit is qualified.

## 6. Windows Tier-1 support contract

The normative Windows contract is
[.codex/WINDOWS_PLATFORM_CONTRACT.md](.codex/WINDOWS_PLATFORM_CONTRACT.md).
Tier-1 work covers native drive paths, supported MSYS/WSL aliases, NTFS locks,
process trees, applicable Job Object behaviour, PowerShell/native argument
transport, Git Bash boundaries, CRLF, UTF-8/CP932, venv paths and Electron pipes.

Runtime qualification is split into separate gates: Python, Desktop, installer,
portable, upgrade, Go watchdog, security, local runtime and live workstation
evidence. A green unit test, an open port or a merged PR does not automatically
satisfy the other gates.

## 7. Local AI architecture

Hermes' normal provider and model-catalogue contracts remain authoritative.
Local inference is another route through that architecture rather than a forked
agent core.

The Windows workstation can run a separately supplied llama.cpp executable and
GGUF model on loopback. Generation and embedding are intentionally separate:

- generation is a normal model endpoint and has its own operator lifecycle;
- embedding is optional Semantic Graph infrastructure and may be supervised by
  the Go watchdog when the watchdog launched that embedding process itself;
- model readiness requires a real health/model response, not merely a listener.

Operator scripts live under `scripts/windows/`, including llama launch/hot-swap
and Tailscale Serve management. Model weights and private credentials are never
part of the source repository.

## 8. Watchdog and recovery architecture

Electron main is the Desktop backend lifecycle owner. It may stop/restart the
backend instance it owns; the Go watchdog must not become a parallel Desktop
backend owner.

The Go watchdog supplies observation, recovery state, a read-only status plane
and the lifecycle for an embedding `llama-server` that it explicitly created.
Its own launcher uses exact process identity evidence before destructive
replacement. PID strings, command-line substrings or a stale lock file are not
enough authority.

Generation llama, gateway profiles, WebUI, dashboard and Desktop all have
separate lifecycles. A full workstation restart therefore requires explicit
verification of each service, not a single process-exists check.

See [scripts/windows/watchdog-go/README.md](scripts/windows/watchdog-go/README.md).

## 9. Memory and semantic retrieval

Profiles isolate configuration, credentials, sessions and memory. Semantic Graph
adds graph-backed storage, embeddings, hybrid retrieval and cognitive helpers
through the plug-in/memory interfaces. Ebbinghaus is a separate memory provider
for retention/experience policy and can compose with Semantic Graph.

Other bundled memory providers remain available through the standard Hermes
memory configuration. Use:

```powershell
uv run hermes memory
```

and the active profile configuration to see what is actually enabled. No personal
memory database or model file is included in the repository.

## 10. VRChat, Unity, and voice integrations

VRChat autonomy, Unity bridge tooling, local TTS/VOICEVOX/Irodori, AITuber and
related media integrations are downstream-owned plug-ins. They use the same
Hermes tool/plug-in boundaries as other optional capabilities and require their
external runtimes or SDKs to be installed separately.

Publishing, account mutation and other external write actions remain explicit
user-approved operations. Local generation never implies permission to publish.

## 11. Installation

The native target is Windows 11 x64. Install Git, `uv` and Python 3.11–3.13:

```powershell
git clone https://github.com/zapabob/hermes-agent-windows.git
Set-Location hermes-agent-windows
uv sync --locked --all-extras
uv run hermes --version
uv run hermes setup
```

The setup wizard configures the model/provider route. A GPU is optional when
using a remote provider. Local inference requires a separately supplied model
file and compatible runtime.

### Build Desktop

Use a Node.js version accepted by
[`apps/desktop/package.json`](apps/desktop/package.json). Then:

```powershell
npm ci
npm run typecheck --workspace apps/desktop
npm run build --workspace apps/desktop
```

Packaging and replacing the running `Hermes.exe` are separate operations. A
locked running executable must be stopped through its ownership-aware lifecycle
before packaging replaces it.

The release pipeline can produce an NSIS installer and portable ZIP. Stable
publication remains a separate exact-tag qualification step. The official
upstream installer targets the upstream distribution; it is not the installer
for this downstream.

## 12. Update and upstream integration policy

Upstream is an integration input, not a moving source tree that this fork merges
blindly. Each semantic-refresh campaign uses exact frozen SHAs, repository
inventory, source/caller mapping, focused regression evidence, mutation where
needed, CodeGraph and independent review.

For the current campaign:

| Input | SHA | Meaning |
| --- | --- | --- |
| R2 | `f97608f178d1ffeca59860195ab7da295f7c8e5f` | upstream 0.21.5 / `v2026.9.24` stable release |
| U1 | `678a4762b887f3eabe5cad11254b2ab1ae859485` | frozen newer upstream ceiling for the active campaign |
| historical snapshot | `b51c055a12220f8c7c18660e8599365012e19532` | retained provenance anchor |

The current `main` contains multiple mapped Windows/runtime fixes from the active
campaign, including process-identity, relaunch/recovery and Desktop E2E isolation
work. The campaign remains open until every in-scope ledger row is mapped or
explicitly dispositioned. Version 0.21.5 therefore describes the product release
identity, not a shortcut around semantic review.

The built-in updater follows the upstream transactional shape:
`plan → snapshot → apply → restart-per-kind → verify → report`. Update receipts,
fleet version checks and deployment-kind handling are part of the update
contract.

## 13. Architecture

The same `AIAgent` core sits behind CLI, Gateway, TUI and Electron Desktop.
Capabilities are loaded at the edges through plug-ins, skills, MCP, provider
adapters and configured toolsets.

Important architectural boundaries are:

- profile-aware state paths through `HERMES_HOME`;
- one session store and one profile model across surfaces;
- prompt-cache stability during a conversation;
- provider/model selection through the central registry;
- normal delegation, fallback and MoA as distinct capabilities;
- Desktop backend ownership in Electron main;
- optional external supervisors that do not duplicate product ownership;
- explicit approvals and receipts around mutations.

Bot Mode follows the same rule: one bot is one profile plus one canonical session
titled exactly `Bot Chat`. The bot row resolves that registry entry by name on
every open; it does not persist a canonical session-id pin.

## 14. Security

Do not commit secrets, profile databases, personal runtime data, model files,
OAuth tokens, generated credentials or investigation artefacts.

The downstream Security Center provides local scan policy, definition state,
evidence and encrypted quarantine. Mutating Security Center API calls require
explicit confirmation. `hermes security`, `hermes egress` and `hermes secrets`
cover workstation scanning/supply-chain checks, credential-injection egress
policy and external secret stores.

Provider base URLs are masked before logs, and child processes receive bounded
environment maps rather than ambient provider credentials.

### Control MCP status

Control MCP has authentication, strict claims, operation journaling, coordinator
and evidence contracts under `downstream/control_mcp/`, but **production write
remains DISABLED**. The active campaign still records N07-A1, T06 and T12 as
open: the real host grant-revocation writer, grant/claim/effect linearisation,
trusted producer binding, separate apply approval and actual writer fence are not
all closed. Tests or a successful-looking receipt do not authorise enabling that
write path.

See [docs/control-mcp/IMPLEMENTATION_LOG.md](docs/control-mcp/IMPLEMENTATION_LOG.md)
and the semantic-refresh handoff plan for the current gates.

## 15. Upstream project

The original project is
[NousResearch/hermes-agent](https://github.com/NousResearch/hermes-agent).
Upstream documentation, installers, releases and support channels apply to the
upstream distribution. They do not install or endorse this downstream fork.

Upstream contributions retain their authorship and attribution. Where an
upstream behaviour is adopted here, the semantic-refresh ledger records the
source and local evidence rather than rewriting history.

## 16. License and attribution

The original Hermes Agent is developed by Nous Research and licensed under MIT.
This downstream retains that attribution, the original copyright and contributor
history, and the [MIT licence](LICENSE).

Downstream Windows/workstation changes are maintained independently by this
repository. Upstream and downstream issue trackers, releases, support claims and
qualification evidence remain separate.
