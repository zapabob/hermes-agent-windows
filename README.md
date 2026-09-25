# Hermes Agent Windows Workstation Edition

<p align="center">
  <a href="README.md" lang="en-GB"><strong>King's English</strong></a> ·
  <a href="README.ja.md" lang="ja">日本語</a> ·
  <a href="README.zh-CN.md" lang="zh-CN">简体中文</a>
</p>

> [!NOTE]
> This English `README.md` is the canonical version. The Japanese and
> Simplified Chinese translations follow it section by section.

An unofficial, Windows-native downstream of Hermes Agent, with an Electron desktop,
CLI, messaging gateway and optional local inference, memory and voice integrations.

This single-maintainer fork is independent of, and not endorsed by, Nous Research.
The downstream is maintained at
[zapabob/hermes-agent-windows](https://github.com/zapabob/hermes-agent-windows).
The original [Hermes Agent](https://github.com/NousResearch/hermes-agent) is
developed by Nous Research. Both the upstream attribution and the
[MIT licence](LICENSE) are retained.

[![Windows Workstation Tier-1 CI](https://github.com/zapabob/hermes-agent-windows/actions/workflows/fork-cicd.yml/badge.svg)](https://github.com/zapabob/hermes-agent-windows/actions/workflows/fork-cicd.yml)

**Current source version: 0.21.3.** The recorded upstream release is also
0.21.3 (`v2026.9.14`); this fork keeps `version_source: downstream` and the
frozen upstream snapshot `b51c055a12220f8c7c18660e8599365012e19532`. A source
version or a main-branch push does not establish that a stable installer has
been published. Supported channels are `stable` and `preview`.

If this Windows-native downstream is useful to you, consider starring the
repository; it helps other Windows users discover the project.

## Setup in 30 seconds

> **TL;DR:** run the five commands below in order. The setup wizard configures
> your model provider; the core CLI needs no optional plug-ins or Git submodules.

The source route is available today. Prepare Windows 11 x64, PowerShell, Git,
`uv` and Python 3.11–3.13. Node.js is needed only to build Desktop.

```powershell
git clone https://github.com/zapabob/hermes-agent-windows.git
Set-Location hermes-agent-windows
uv sync --locked --all-extras
uv run hermes setup
uv run hermes chat
```

This is a command path you can read in 30 seconds; the first dependency
download and any native builds take longer. To open Desktop from the same
checkout, run:

```powershell
uv run hermes desktop
```

For an installer or portable ZIP, first confirm that the matching asset has been
published on the
[downstream Releases page](https://github.com/zapabob/hermes-agent-windows/releases)
and check it against `SHA256SUMS.txt`. The full procedure is in the
[Windows installation guide](docs/windows/INSTALL.md).

<details open>
<summary><strong>日本語</strong></summary>

Windows向け独立派生版のソースは0.21.3です。上の5コマンドで導入でき、詳しくは
[日本語版README](README.ja.md) と第11節をご覧ください。安定版の公開、署名、
クリーン環境での検証は、それぞれ別に確認する必要があります。

</details>
<details>
<summary><strong>简体中文</strong></summary>

这是独立维护的 Windows 衍生版本，当前源码版本为0.21.3。可用上面的五条命令安装，
详见[简体中文 README](README.zh-CN.md)与第11节；源码构建不代表已发布经过完整验证的稳定安装包。

</details>

## What this fork adds

- **Bring your own key, OAuth first.** No hosted service is required at runtime.
  Sign in with a subscription through OAuth (OpenAI Codex/ChatGPT, xAI Grok,
  Qwen, MiniMax, Nous Portal and others), supply your own API key for any of the
  42 bundled model providers, or point Hermes at a local llama.cpp server. Nous
  Portal is one optional provider, not a requirement.
- Windows Tier-1 CI for Python, Electron, Go, upstream API compatibility,
  regressions and security locks.
- Installer, portable and upgrade E2E, including non-administrator accounts and
  paths containing spaces.
- A frozen upstream snapshot `b51c055a12220f8c7c18660e8599365012e19532`
  instead of a moving baseline.
- Local llama.cpp/GGUF inference and an embedding lifecycle behind the official
  provider and memory seams.
- A Desktop Python backend owned solely by Electron main, with an external Go
  watchdog limited to the embedding server it launched itself.
- A sequential engineering workflow (`implementation_router`) that reuses the
  existing model picker, parent-owned inference and credential-free Docker
  execution.
- Consumer NVIDIA workstation evidence kept separate from GPU-less hosted CI.

## Plug-ins and Git submodules

Hermes discovers standard directory plug-ins from `plugin.yaml`, `__init__.py`
and `register(ctx)`. The 53 bundled standard root plug-ins are grouped below;
`lmcache` also ships as a legacy manifest with its own registration path. Run
`uv run hermes plugins` to see what is enabled for the current profile.

| Area | Bundled root plug-ins |
| --- | --- |
| Agent and operations | `ai-employee-org`, `ai-partner-os`, `airi`, `aituber-onair`, `aituber-kit`, `book-to-skill`, `desktop-dashboard`, `disk-cleanup`, `freebuff`, `freellmapi`, `google-colab`, `google_meet`, `hermes-antigravity`, `hermes-gpt`, `hermes-bot-mode`, `implementation_router`, `line-ai-bot`, `lm-twitterer`, `memory-llm-wiki`, `notebooklm`, `oh-my-hermes`, `openclaw-vendor`, `openmanus`, `plugin-doctor`, `research-desk`, `scrapling-feeds`, `teams_pipeline`, `warashibe-reselling` |
| Media, voice and XR | `akari-video`, `buzz`, `fish-audio-tts`, `hakua-tts-bridge`, `heygen`, `hyperframes`, `irodori-tts`, `questframe-fh6vr`, `sillytavern`, `spotify`, `unity-cli`, `unity-vrchat-bridge`, `unsloth-studio`, `voicebox`, `voicevox-tts`, `vrchat-autonomy` |
| Knowledge, security and OSINT | `osint-agent`, `security-guidance`, `semantic-graph`, `shinka-osint`, `sitdeck-osint`, `surfsense`, `tookie-osint`, `world-intel-osint`, `worldmonitor-osint` |
| Legacy manifest | `lmcache` |

The retained [integration inventory](docs/windows/INTEGRATIONS.md) records
**154 plug-in manifests** at its documented snapshot; `hermes-antigravity` and
`implementation_router` have been added since, so the current tree carries 156.
Specialised provider families are discovered separately, so only the
capabilities you configure enter a session. Counts describe the tree, not
runtime enablement or qualification.

| Discovery family | Bundled providers and adapters |
| --- | --- |
| Browser (3) | `browser_use`, `browserbase`, `firecrawl` |
| Cron (1) | `chronos` |
| Dashboard auth (4) | `basic`, `drain`, `nous`, `self_hosted` |
| Image generation (7) | `deepinfra`, `fal`, `krea`, `openai`, `openai-codex`, `openrouter`, `xai` |
| Memory (9) | `byterover`, `ebbinghaus`, `hindsight`, `holographic`, `honcho`, `mem0`, `openviking`, `retaindb`, `supermemory` |
| Model providers (42) | `actual`, `ai-gateway`, `alibaba`, `alibaba-coding-plan`, `anthropic`, `arcee`, `azure-foundry`, `bedrock`, `commandcode`, `copilot`, `copilot-acp`, `custom`, `deepinfra`, `deepseek`, `fireworks`, `freebuff`, `freellmapi`, `gemini`, `gmi`, `huggingface`, `hypura`, `kilocode`, `kimi-coding`, `meta-ai`, `minimax`, `nebius-token-factory`, `nous`, `novita`, `nvidia`, `ollama-cloud`, `openai-codex`, `opencode-free`, `opencode-zen`, `openrouter`, `qwen-oauth`, `router`, `stepfun`, `upstage`, `vertex`, `xai`, `xiaomi`, `zai` |
| Observability (1) | `langfuse` |
| Messaging platforms (22) | `a2a`, `buzz`, `dingtalk`, `discord`, `email`, `feishu`, `google_chat`, `homeassistant`, `irc`, `line`, `matrix`, `mattermost`, `ntfy`, `photon`, `raft`, `simplex`, `slack`, `sms`, `teams`, `telegram`, `wecom`, `whatsapp` |
| Video generation (3) | `deepinfra`, `fal`, `xai` |
| Web search and extraction (11) | `brave_free`, `cloakbrowser`, `ddgs`, `exa`, `firecrawl`, `keenable`, `parallel`, `scrapling`, `searxng`, `tavily`, `xai` |

Built-in adapters under `gateway/platforms/` add Signal, BlueBubbles (iMessage),
Weixin, Yuanbao, the WhatsApp Business Cloud API, generic webhooks and an
OpenAI-compatible API server.

Git submodules are optional integrations. Run
`git submodule update --init --recursive` only when you need all of them.

| Path | Repository | Purpose |
| --- | --- | --- |
| `plugins/hermes-bot-mode/desktop` | [Hermes-Bot-Mode](https://github.com/zapabob/Hermes-Bot-Mode.git) | Desktop bot roster UI |
| `plugins/artemis` | [artemis](https://github.com/zapabob/artemis.git) | Android automation from natural-language instructions |
| `vendor/openclaw-mirror/AI-Scientist` | [AI-Scientist](https://github.com/zapabob/AI-Scientist.git) | Scientific agent integration |
| `vendor/openclaw-mirror/ATLAS` | [ATLAS](https://github.com/zapabob/ATLAS.git) | Research agent integration |
| `vendor/openclaw-mirror/ShinkaEvolve` | [ShinkaEvolve](https://github.com/zapabob/ShinkaEvolve.git) | Evolutionary workflow integration |
| `vendor/neuro-sdk` | [neuro-sdk](https://github.com/zapabob/neuro-sdk.git) | Neuro integration SDK |
| `vendor/openmanus` | [OpenManus](https://github.com/zapabob/OpenManus.git) | OpenManus runtime |
| `vendor/SillyTavern` | [SillyTavern](https://github.com/zapabob/SillyTavern.git) | Local character chat front end |
| `vendor/shinka-osint` | [ShinkaEvolve-OSINT](https://github.com/zapabob/ShinkaEvolve-OSINT.git) | OSINT analysis runtime (private repository; initialisation needs access) |
| `vendor/buzz` | [buzz](https://github.com/zapabob/buzz.git) | Speech transcription runtime |
| `vendor/officecli` | [OfficeCLI](https://github.com/zapabob/OfficeCLI.git) | Office document CLI |
| `vendor/akari-video` | [akari-video](https://github.com/zapabob/akari-video.git) | AI video editor |
| `vendor/cloakbrowser` | [cloakbrowser](https://github.com/zapabob/cloakbrowser.git) | Browser automation runtime |
| `vendor/airi` | [airi](https://github.com/zapabob/airi.git) | Avatar and companion runtime |
| `vendor/oh-my-hermes` | [oh-my-hermes](https://github.com/zapabob/oh-my-hermes.git) | Hermes workflow extensions |
| `vendor/OpenMausBot` | [OpenMausBot](https://github.com/zapabob/OpenMausBot.git) | Desktop automation bot |
| `vendor/heygen-cli` | [heygen-cli](https://github.com/heygen-com/heygen-cli.git) | HeyGen CLI client |

## 1. Product identity

Hermes Agent Windows Workstation Edition is a Windows-first downstream
distribution for an always-on local AI workstation. It keeps the Hermes CLI
commands, public contracts, plug-in model and upstream history, and sets an
explicit downstream policy for native Windows behaviour, local models, memory,
voice, VR/Unity and recovery.

The product ledger is [FEATURES.yaml](FEATURES.yaml). Direct patches carried
in upstream-owned files are tracked separately in [CARRY.yaml](CARRY.yaml), and
upstream commits are classified in `UPSTREAM_ADOPTION.yaml`. The policy summary
is [DOWNSTREAM_POLICY.md](DOWNSTREAM_POLICY.md).

## 2. Windows-first goals

The primary target is Windows 11 x64 with native Python, native Node/Electron,
an interactive desktop and a consumer NVIDIA GPU. The design covers continuous
operation with local LLM and embedding services, voice services, VRChat/Unity
integration and remote administration.

Windows is a Tier-1 target independently of upstream platform priorities.
Native behaviour is tested on `windows-latest`; cross-compilation on Linux is not
accepted as Windows runtime evidence. Background Git and web helper calls use
hidden-process creation flags, and the Git wrapper separates non-interactive
probes from the user-facing terminal. This covers the known helper launch paths;
it is not a claim that every possible console source has been eliminated.

## 3. Who this is for

Operators and developers who run a Windows AI workstation and need source-level
control over local inference, long-running services, memory, desktop behaviour
and recovery. Familiarity with PowerShell, Git, Python environments, Node tooling
and reading CI results is assumed.

If you want the simplest official Hermes installation and the upstream support
model, use the original project linked in section 15.

## 4. Downstream advantages

- **No vendor lock-in.** Every provider is optional. OAuth sign-in (OpenAI
  Codex/ChatGPT, xAI Grok, Qwen, MiniMax, Nous Portal), existing Claude Code
  OAuth credentials, your own API keys, or a local llama.cpp server all work
  through the same provider registry. `hermes proxy` exposes OAuth providers as a local OpenAI-compatible
  endpoint, and `hermes fallback` chains providers when the primary fails.
- **Windows runtime and recovery contracts**, with a single owner for the
  Desktop backend and an auxiliary Go watchdog (section 8).
- **Local inference**: llama.cpp/GGUF fallback, hot-swap presets and
  GPU-specific launchers under `scripts/windows/`, plus the Hypura provider and
  harness (`hermes harness`).
- **Memory**: Semantic Graph hybrid retrieval and the Ebbinghaus cognitive
  memory provider (section 9).
- **Engineering workflow**: the `implementation_router` plug-in runs planner,
  worker, deterministic verification and reviewer stages through the existing
  auxiliary model picker, using `engineering_run` or `/engineer`.
- **Integrations**: local secretary, VRChat/Unity, local voice, AITuber,
  OSINT/Shinka, a Desktop Git/review pane and an isolated Antigravity CLI
  bridge (`hermes-antigravity`).
- **Credential hygiene**: credential leases stay bound to the selected entry, an
  empty credential pool cannot start a delegated child with an inherited client,
  and provider base URLs are masked before they reach logs.

These capabilities compose with the official Hermes APIs. The fork does not
create a parallel source of truth for sessions, approvals, profiles, the
gateway, the model catalogue or the tool registry.

## 5. Verified feature matrix

| Area | Verified implementation | Contract evidence |
| --- | --- | --- |
| Windows runtime | Native paths, processes, IPC, NTFS handoff, terminal, credentials, power and GPU helpers | `tests/downstream/test_windows_contracts.py` |
| Desktop backend | Single-owner backend lifecycle in Electron main | `apps/desktop/electron/single-owner-backend-lifecycle.test.ts` |
| Recovery | External Go watchdog with read-only status and exact-identity authority | `scripts/windows/watchdog-go/authority_test.go` |
| Local inference | llama.cpp/GGUF fallback and hot-swap scripts | `tests/hermes_cli/test_llama_fallback_runtime.py` |
| Local embeddings | Watchdog embedding lifecycle and Semantic Graph backend | `scripts/windows/watchdog-go/embedding_test.go` |
| Local secretary | Read/write action separation on the official agent boundary | `tests/downstream/test_upstream_api_contracts.py` |
| Providers | Hypura/local provider integration | `tests/fork/test_hypura_oai_proxy.py` |
| Provider fallback | Fallback chains and provider rotation | `tests/hermes_cli/test_fallback_chain.py` |
| Memory | Semantic Graph hybrid retrieval and the Ebbinghaus cognitive extension | `tests/plugins/test_semantic_graph_registration.py`, `tests/plugins/test_ebbinghaus_plugin.py` |
| Engineering workflow | Sequential planner/worker/reviewer router with route admission | `tests/implementation_router/test_route_admission.py` |
| VR and Unity | VRChat autonomy tooling and Unity bridge | `tests/plugins/test_vrchat_autonomy_plugin.py` |
| Voice | Irodori, VOICEVOX and local TTS routes | `tests/plugins/test_irodori_tts_plugin.py` |
| AITuber | AITuber OnAir and AITuber Kit plug-ins | `tests/plugins/test_aituber_onair_plugin.py` |
| OSINT/Shinka | Shinka, SitDeck, WorldMonitor and OSINT plug-in surfaces | `tests/plugins/test_shinka_osint_plugin.py` |
| Desktop | Git/review extension on the official Desktop IPC and pane contracts | `apps/desktop/electron/git-review-ops.test.ts` |
| Security | Security guidance and hardened approval/execution boundaries | `tests/plugins/test_security_guidance_plugin.py` |

Owners, public surfaces, upstream overlap, Windows requirements, tests and the
integration policy for each feature are recorded in `FEATURES.yaml`. The former
watchdog-managed Desktop backend is listed there as retired. These are scoped
checks, not qualification of every optional integration.

## 6. Windows Tier-1 support contract

Tier-1 covers native drive paths, MSYS `/c/...` and supported WSL `/mnt/c/...`
aliases, NTFS locks, updating locked executables and extension modules, process
trees, applicable Job Object behaviour, PowerShell quoting, the Git Bash
boundary, the CP932/UTF-8 boundary, CRLF, venv `Scripts\` and Electron stdio
pipes.

Runtime qualification covers sleep/resume, network and loopback provider
recovery, Desktop relaunch, updater handoff, watchdog recovery, llama restart
and hot-swap, embedding restart, and profile/session persistence. The normative
contract is [.codex/WINDOWS_PLATFORM_CONTRACT.md](.codex/WINDOWS_PLATFORM_CONTRACT.md).
Native Python, Desktop, installer, portable, upgrade, watchdog and security
checks are separate gates; mock-only results and skipped P0 tests cannot
qualify Windows support.

## 7. Local AI architecture

The official Hermes provider and model catalogue contracts remain authoritative.
The downstream local runtime plugs into them: llama.cpp/GGUF as the local
fallback runtime, Hypura as a provider plug-in seam, and local embeddings as the
Semantic Graph backend with a watchdog-managed loopback service. Hot-swap
presets select independently installed GGUF files; inference readiness requires
a real model response, not merely an open port.

Operator scripts live under `scripts/windows/` (for example
`start-llama-hotswap.ps1`, `switch-llama-hotswap.ps1` and the GPU-specific
`start-hermes-llama-fallback-*.ps1` launchers). Runtime plug-in entry points
stay under `plugins/` so that official discovery keeps working. Remote access
to local services is configured with `Manage-HermesTailscaleServe.ps1`
(Tailscale Serve), which also has a verification-only mode.

## 8. Watchdog and recovery architecture

The Desktop Python backend lifecycle is owned exclusively by Electron main in
the supported Windows topology. Health observation, a PID, a port, a token or
a manifest do not confer destructive lifecycle authority on another component.

The external Go watchdog is an auxiliary supervisor with a read-only status
surface. Its supported destructive scope is limited to an embedding
`llama-server` instance that it explicitly launched and owns; it is not a
second Desktop-backend owner. The legacy watchdog backend-owner and Desktop
relaunch paths have been removed. See the
[watchdog guide](scripts/windows/watchdog-go/README.md) and the
[Windows platform contract](.codex/WINDOWS_PLATFORM_CONTRACT.md).

Downstream Python service modules are side-effect-free contracts. Actual
operator start-up and deployment remain in the PowerShell and Go surfaces under
`scripts/windows/`.

## 9. Memory and semantic retrieval

Profiles scope configuration, credentials, sessions and memory. The Semantic
Graph plug-in provides graph storage, hybrid retrieval, embeddings, fusion,
abstention and cognitive helpers through the official plug-in and memory
interfaces. The Ebbinghaus provider adds experience and retention policy and can
bridge to Semantic Graph. Both keep their own plug-in entry points and focused
test suites.

External memory providers (Honcho, Mem0, Supermemory, Hindsight and others in
the table above) are selected with `hermes memory`, and `hermes journey` shows
learned skills and memories over time. No model files or personal memory are
included in the source distribution.

## 10. VRChat, Unity, and voice integrations

VRChat autonomy tools, observation/relay helpers, the Unity bridge package,
VOICEVOX, Irodori and other local TTS routes are downstream-owned features. They
use the official plug-in, tool and TTS contracts rather than turning the core
into a VR- or voice-specific runtime. Their SDKs, applications and hardware must
be configured separately.

External publishing and write actions still require explicit approval. Local
generation does not authorise publishing to, or changing, external accounts.

## 11. Installation

The target is Windows 11 x64. Use PowerShell, Git, `uv`, and Python 3.11–3.13.
Dependency installation can take several minutes and may require native build
tools for optional extras. WSL is not required for the native application.

```powershell
git clone https://github.com/zapabob/hermes-agent-windows.git
Set-Location hermes-agent-windows
uv sync --locked --all-extras
uv run hermes --version
uv run hermes setup
```

The setup wizard selects a model provider. A GPU is optional when using a
remote provider. Local models require separately supplied model files and a
compatible inference runtime; this repository does not include model weights.

The Windows release workflow produces a per-user NSIS installer and a portable
ZIP, and runs clean-install, launch and upgrade E2E before publishing on a
stable tag. Obtain published artefacts only from the
[downstream Releases page](https://github.com/zapabob/hermes-agent-windows/releases)
and verify `SHA256SUMS.txt`. Current candidates are unsigned unless
`release-manifest.json` records otherwise. The
[installation guide](docs/windows/INSTALL.md) is the canonical procedure; older
version examples in it are not evidence of a 0.21.3 release.

The official upstream installer targets the upstream product; use this
downstream repository or its published release assets for this distribution.

### Build Desktop

Use a Node.js version accepted by
[`apps/desktop/package.json`](apps/desktop/package.json). Install JavaScript
dependencies at the repository root; Desktop is an npm workspace.

```powershell
npm ci
npm run typecheck --workspace apps/desktop
npm run build --workspace apps/desktop
```

The build produces application files. Packaging and installing a new Desktop
binary are separate operations. Do not replace an executable while its process
is running.

Review the configuration before enabling any always-on service or Scheduled
Task. Store API keys and tokens in the profile's Hermes secret store or in
`.env` as the Hermes documentation describes; non-secret settings belong in
`config.yaml`.

## 12. Update and upstream integration policy

Upstream is integration input, not the authority for the downstream product.
Each campaign pins an exact SHA in `.codex/UPSTREAM_SNAPSHOT.json`, classifies
commits in `UPSTREAM_ADOPTION.yaml` and records directly carried changes in
`CARRY.yaml`. `scripts/upstream/snapshot_sync.py` takes an explicit SHA and never
resolves a moving latest branch. The retained release-provenance snapshot is
`b51c055a12220f8c7c18660e8599365012e19532`.

Prefer the official public APIs. Security and data-integrity fixes are combined
with stronger, verified downstream properties. A downstream feature is not
removed merely because upstream gained a similarly named one; replacement needs
parity evidence. Do not use a wholesale upstream merge, rebase or cherry-pick as
a substitute for contract review.

Before updating a running workstation, save uncommitted work and each profile,
record the current commit and keep a rollback copy of the deployed Desktop. The
Desktop control backend, messaging gateway, llama server, embedding server and
Go watchdog have distinct lifecycles; closing one window does not establish that
all of them restarted. After restarting, check the application window, backend
response and actual model readiness. See
[local runtime configuration](docs/local-secretary-runtime.md), the
[release policy](docs/windows/RELEASE_POLICY.md) and [AGENTS.md](AGENTS.md).

## 13. Architecture

Fork-owned Python boundaries live under `downstream/`: `compat/hermes` delegates
to the official contracts, `platform/windows` owns native policy, `services`
defines long-lived service contracts and `features` validates the product
ledger. There is deliberately no top-level Python package named `platform`.

The shared agent core sits behind the CLI, messaging gateway, TUI and Electron
Desktop. Around it sit the central slash-command registry, cron scheduling,
the multi-profile kanban board, subagent delegation, the skill curator, Mixture
of Agents (`hermes moa`), MCP client and server (`hermes mcp`), ACP and profiles.
The core stays a narrow waist: plug-ins and skills hold capability,
profile-aware official path helpers own state paths, and the prompt-cache and
message-role invariants are mandatory.

## 14. Security

Do not commit secrets, personal runtime data, profile databases, model files,
local artefacts or generated credentials. Write, publish, destructive and shell
actions stay behind explicit approval. Child service environments receive only
the variables they need, never ambient credentials.

Provider base URLs are masked before logging. Relay 0.8 trace-context headers
(`traceparent`, `tracestate`, `baggage`) are stripped from provider calls unless
`telemetry.relay.propagate_trace_headers: true` is set in `config.yaml`.
`hermes security` runs a supply-chain audit and Windows workstation malware
protection, `hermes egress` manages the credential-injection egress firewall,
and `hermes secrets` connects external secret sources such as Bitwarden and
1Password.

The security gate checks the locked Python graph, Python advisories, production
npm advisories, Go module integrity, OSV results, supply-chain policy and this
repository's security regression tests. Green local unit tests do not replace
exact-head CI or live runtime evidence. Read [SECURITY.md](SECURITY.md);
unresolved private contracts remain unqualified.

## 15. Upstream project

The original project is [NousResearch/hermes-agent](https://github.com/NousResearch/hermes-agent).
The official upstream installer, website, documentation, issue tracker and
support channels apply to the upstream distribution; they do not install or
endorse this downstream repository. Upstream contributions retain their
authorship and attribution.

## 16. License and attribution

The original Hermes Agent is developed by Nous Research and licensed under MIT.
This downstream retains that attribution, the original copyright and contributor
history, and the [MIT licence](LICENSE). Downstream work is maintained
independently; upstream and downstream issues, releases and product claims must
be kept clearly apart.
