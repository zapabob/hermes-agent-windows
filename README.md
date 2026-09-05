# Hermes Agent Windows Workstation Edition
A Windows-native AI workstation, built on Hermes Agent.
Agent runtime · IDE workspace · Local AI · Memory · Browser · Security · Voice · VR/Unity
<p align="center"><strong>Language · 言語 · 语言</strong></p>

<details open>
<summary><strong>King's English</strong></summary>

Run the five commands in <a href="#setup-in-30-seconds">Setup in 30 seconds</a>.
The shared <a href="#plug-ins-and-git-submodules">plug-in and submodule inventory</a>
lists every bundled integration. The complete British English guide continues
below.

</details>

<details>
<summary><strong>日本語</strong> — README内で30秒導入を表示</summary>

Windows 11 x64、PowerShell、Git、<code>uv</code>、Python 3.11–3.13を用意し、
次の5コマンドを実行します。基本CLIに任意のGitサブモジュールは不要です。

```powershell
git clone https://github.com/zapabob/hermes-agent-windows.git
Set-Location hermes-agent-windows
uv sync --locked --all-extras
uv run hermes setup
uv run hermes chat
```

Desktopは <code>uv run hermes desktop</code> で起動できます。標準ルートプラグイン
51件、全154件のmanifest、Gitサブモジュール16件は
<a href="#plug-ins-and-git-submodules">共通一覧</a>に掲載しています。
詳説は <a href="README.ja.md">日本語版README</a> を参照してください。

</details>

<details>
<summary><strong>简体中文</strong> — 在README内查看30秒安装</summary>

准备Windows 11 x64、PowerShell、Git、<code>uv</code>和Python 3.11–3.13，
然后运行以下五条命令。核心CLI不要求初始化可选Git子模块。

```powershell
git clone https://github.com/zapabob/hermes-agent-windows.git
Set-Location hermes-agent-windows
uv sync --locked --all-extras
uv run hermes setup
uv run hermes chat
```

使用 <code>uv run hermes desktop</code> 启动Desktop。51个标准根插件、全部154个
manifest及16个Git子模块列于<a href="#plug-ins-and-git-submodules">共用清单</a>。
完整说明请参阅<a href="README.zh-CN.md">简体中文版README</a>。

</details>

> [!NOTE]
> `README.md` is the canonical British English document. The Japanese and Simplified Chinese translations follow this file.

An unofficial, Windows-native downstream of Hermes Agent for Windows 11 AI workstations.

This single-maintainer fork is independent of, and not endorsed by, Nous Research.
The original Hermes Agent is developed by Nous Research and licensed under MIT.
Developed as a **generic agent harness** and **Windows universal AI workstation base** — upstream is `NousResearch/hermes-agent` until its development stalls.

[![Windows Workstation Tier-1 CI](https://github.com/zapabob/hermes-agent-windows/actions/workflows/fork-cicd.yml/badge.svg)](https://github.com/zapabob/hermes-agent-windows/actions/workflows/fork-cicd.yml)

## Setup in 30 seconds

> **TL;DR:** Run the five commands below. The wizard asks for a model provider;
> optional plug-ins and Git submodules are not required for the core CLI.

Use the source route today. You need Windows 11 x64, PowerShell, Git, `uv`,
and Python 3.11-3.13. Node.js is needed only when building the Desktop app.

```powershell
git clone https://github.com/zapabob/hermes-agent-windows.git
Set-Location hermes-agent-windows
uv sync --locked --all-extras
uv run hermes setup
uv run hermes chat
```

This is the 30-second command path; dependency downloads and compilation may
take longer on a fresh workstation.

The setup wizard configures your model provider. The last command opens the
CLI chat. To open the Desktop app from the same checkout, run:

```powershell
uv run hermes desktop
```

Prefer an installer or portable ZIP? Use a matching asset from the
[downstream Releases page](https://github.com/zapabob/hermes-agent-windows/releases)
only when it is published, and verify it against `SHA256SUMS.txt`. The complete
procedure is in the [Windows installation guide](docs/windows/INSTALL.md).

## What this fork adds

- Native Windows Tier-1 CI for Python, Electron, Go, upstream API compatibility, regressions, and security locks.
- Qualified installer, portable, and prior-version upgrade paths with spaces and non-admin operation.
- Frozen upstream snapshot `b51c055a12220f8c7c18660e8599365012e19532`, never a moving release baseline.
- Local llama.cpp/GGUF and embedding lifecycles through official provider and memory seams.
- External Go watchdog for bounded Desktop/backend and optional embedding recovery.
- Consumer NVIDIA workstation evidence kept separate from GPU-free hosted CI.

Release candidate: `0.21.0`. This version follows the official Hermes release;
downstream revisions are identified by commit SHA rather than a forked version
suffix. Supported channels are `stable` and `preview`. Qualified artifacts are
published only from the matching official-form version tag on the
[downstream Releases page](https://github.com/zapabob/hermes-agent-windows/releases).
Until the first stable asset is present there, use the source route above. See
the [release policy](docs/windows/RELEASE_POLICY.md) and
[official upstream](https://github.com/NousResearch/hermes-agent).

## Plug-ins and Git submodules

Hermes discovers standard directory plug-ins through `plugin.yaml`,
`__init__.py`, and `register(ctx)`. The 51 bundled standard root plug-ins are
grouped below; `lmcache` is also shipped as a legacy manifest with its own
registration path. Run `uv run hermes plugins` to see what is enabled for the
active profile.

| Area | Bundled root plug-ins |
| --- | --- |
| Agents and operations | `ai-employee-org`, `ai-partner-os`, `airi`, `aituber-onair`, `aituber-kit`, `book-to-skill`, `desktop-dashboard`, `disk-cleanup`, `freebuff`, `freellmapi`, `google-colab`, `google_meet`, `hermes-gpt`, `hermes-bot-mode`, `line-ai-bot`, `lm-twitterer`, `memory-llm-wiki`, `notebooklm`, `oh-my-hermes`, `openclaw-vendor`, `openmanus`, `plugin-doctor`, `research-desk`, `scrapling-feeds`, `teams_pipeline`, `warashibe-reselling` |
| Media, voice and XR | `akari-video`, `buzz`, `fish-audio-tts`, `hakua-tts-bridge`, `heygen`, `hyperframes`, `irodori-tts`, `questframe-fh6vr`, `sillytavern`, `spotify`, `unity-cli`, `unity-vrchat-bridge`, `unsloth-studio`, `voicebox`, `voicevox-tts`, `vrchat-autonomy` |
| Knowledge, security and OSINT | `osint-agent`, `security-guidance`, `semantic-graph`, `shinka-osint`, `sitdeck-osint`, `surfsense`, `tookie-osint`, `world-intel-osint`, `worldmonitor-osint` |
| Legacy manifest | `lmcache` |

The repository contains 154 plug-in manifests in total. Specialised discovery
families are kept separate so that only configured capabilities enter a
session.

| Discovery family | Included providers/adapters |
| --- | --- |
| Browser (3) | `browser_use`, `browserbase`, `firecrawl` |
| Cron (1) | `chronos` |
| Dashboard authentication (4) | `basic`, `drain`, `nous`, `self_hosted` |
| Image generation (7) | `deepinfra`, `fal`, `krea`, `openai`, `openai-codex`, `openrouter`, `xai` |
| Memory (9) | `byterover`, `ebbinghaus`, `hindsight`, `holographic`, `honcho`, `mem0`, `openviking`, `retaindb`, `supermemory` |
| Model providers (42) | `actual`, `ai-gateway`, `alibaba`, `alibaba-coding-plan`, `anthropic`, `arcee`, `azure-foundry`, `bedrock`, `commandcode`, `copilot`, `copilot-acp`, `custom`, `deepinfra`, `deepseek`, `fireworks`, `freebuff`, `freellmapi`, `gemini`, `gmi`, `huggingface`, `hypura`, `kilocode`, `kimi-coding`, `meta-ai`, `minimax`, `nebius-token-factory`, `nous`, `novita`, `nvidia`, `ollama-cloud`, `openai-codex`, `opencode-free`, `opencode-zen`, `openrouter`, `qwen-oauth`, `router`, `stepfun`, `upstage`, `vertex`, `xai`, `xiaomi`, `zai` |
| Observability (1) | `langfuse` |
| Messaging platforms (22) | `a2a`, `buzz`, `dingtalk`, `discord`, `email`, `feishu`, `google_chat`, `homeassistant`, `irc`, `line`, `matrix`, `mattermost`, `ntfy`, `photon`, `raft`, `simplex`, `slack`, `sms`, `teams`, `telegram`, `wecom`, `whatsapp` |
| Video generation (3) | `deepinfra`, `fal`, `xai` |
| Web search/extraction (11) | `brave_free`, `cloakbrowser`, `ddgs`, `exa`, `firecrawl`, `keenable`, `parallel`, `scrapling`, `searxng`, `tavily`, `xai` |

Git submodules are optional integrations. Initialise all of them only when you
need their features: `git submodule update --init --recursive`.

| Path | Repository | Purpose |
| --- | --- | --- |
| `plugins/hermes-bot-mode/desktop` | [Hermes-Bot-Mode](https://github.com/zapabob/Hermes-Bot-Mode.git) | Desktop bot roster UI |
| `vendor/openclaw-mirror/AI-Scientist` | [AI-Scientist](https://github.com/zapabob/AI-Scientist.git) | Scientific-agent vendor mirror |
| `vendor/openclaw-mirror/ATLAS` | [ATLAS](https://github.com/zapabob/ATLAS.git) | Research-agent vendor mirror |
| `vendor/openclaw-mirror/ShinkaEvolve` | [ShinkaEvolve](https://github.com/zapabob/ShinkaEvolve.git) | Evolution workflow vendor mirror |
| `vendor/neuro-sdk` | [neuro-sdk](https://github.com/zapabob/neuro-sdk.git) | Neuro integration SDK |
| `vendor/openmanus` | [OpenManus](https://github.com/zapabob/OpenManus.git) | OpenManus runtime |
| `vendor/SillyTavern` | [SillyTavern](https://github.com/zapabob/SillyTavern.git) | Local character-chat frontend |
| `vendor/shinka-osint` | [ShinkaEvolve-OSINT](https://github.com/zapabob/ShinkaEvolve-OSINT.git) | OSINT analysis runtime |
| `vendor/buzz` | [buzz](https://github.com/zapabob/buzz.git) | Speech transcription runtime |
| `vendor/officecli` | [OfficeCLI](https://github.com/zapabob/OfficeCLI.git) | Office document command-line tools |
| `vendor/akari-video` | [akari-video](https://github.com/zapabob/akari-video.git) | AI video editor |
| `vendor/cloakbrowser` | [cloakbrowser](https://github.com/zapabob/cloakbrowser.git) | Browser automation runtime |
| `vendor/airi` | [airi](https://github.com/zapabob/airi.git) | Avatar and companion runtime |
| `vendor/oh-my-hermes` | [oh-my-hermes](https://github.com/zapabob/oh-my-hermes.git) | Hermes workflow extension |
| `vendor/OpenMausBot` | [OpenMausBot](https://github.com/zapabob/OpenMausBot.git) | Desktop automation bot |
| `vendor/heygen-cli` | [heygen-cli](https://github.com/heygen-com/heygen-cli.git) | HeyGen command-line client |

## 1. Product identity

Hermes Agent Windows Workstation Edition is a feature-rich Windows-first
downstream distribution for persistent local AI workstations. It retains the
Hermes CLI command, public contracts, plugin model, and upstream history while
maintaining an explicit downstream policy for native Windows operation, local
models, memory, voice, VR/Unity, and recovery.

The product ledger is [FEATURES.yaml](FEATURES.yaml). Direct patches carried in
upstream-owned files are tracked separately in [CARRY.yaml](CARRY.yaml).

## 2. Windows-first goals

The primary target is Windows 11 x64 with native Python, native Node/Electron,
an interactive desktop, and a consumer NVIDIA GPU. The design supports
continuous operation with local LLM and embedding services, voice services,
VRChat/Unity integrations, and remote management.

Windows is a Tier-1 target independently of upstream platform priorities.
Native behavior is tested on `windows-latest`; Linux cross-compilation is not
accepted as Windows runtime evidence.

## 3. Who this is for

This distribution is intended for operators and developers who maintain a
Windows AI workstation and need source-level control over local inference,
long-lived services, memory, desktop behavior, and recovery. It assumes comfort
with PowerShell, Git, Python environments, Node tooling, and reading CI results.

For the simplest official Hermes installation and the upstream support model,
use the original project linked in section 15.

## 4. Downstream advantages

The downstream adds native Windows runtime and recovery contracts, an external
Go watchdog, local llama.cpp/GGUF and embedding lifecycles, local secretary and
provider integrations, semantic and cognitive memory extensions, VRChat/Unity
and local voice routes, OSINT/Shinka extensions, Desktop Git/review surfaces,
and additional security and provider-fallback coverage.

These capabilities compose with official Hermes APIs. The fork does not create
parallel session, approval, profile, gateway, model-catalogue, or tool-registry
authorities.

## 5. Verified feature matrix

| Area | Verified implementation | Contract evidence |
| --- | --- | --- |
| Windows runtime | Native path, process, IPC, NTFS handoff, terminal, credentials, power and GPU helpers | `tests/downstream/test_windows_contracts.py` |
| Recovery | External Go watchdog and watchdog-managed Desktop backend | `scripts/windows/watchdog-go/*_test.go` |
| Local inference | llama.cpp/GGUF fallback and hot-swap scripts | `tests/hermes_cli/test_llama_fallback_runtime.py` |
| Local embeddings | Watchdog embedding lifecycle and semantic graph backends | `scripts/windows/watchdog-go/embedding_test.go` |
| Local secretary | Read/write action separation over official agent boundaries | `tests/downstream/test_upstream_api_contracts.py` |
| Providers | Hypura/local provider integration and provider rotation/fallbacks | `tests/fork/test_hypura_oai_proxy.py` |
| Memory | Semantic Graph hybrid retrieval and Ebbinghaus cognitive extensions | `tests/plugins/test_semantic_graph_registration.py` |
| VR and Unity | VRChat autonomy tooling and Unity bridge | `tests/plugins/test_vrchat_autonomy_plugin.py` |
| Voice | Irodori, VOICEVOX, and local TTS routes | `tests/plugins/test_irodori_tts_plugin.py` |
| AITuber | AITuber OnAir and AITuber Kit plugins | `tests/plugins/test_aituber_onair_plugin.py` |
| OSINT/Shinka | Shinka, SitDeck, WorldMonitor, and OSINT plugin surfaces | `tests/plugins/test_shinka_osint_plugin.py` |
| Desktop | Git/review extensions through official Desktop IPC and pane contracts | `apps/desktop/electron/git-review-ops.test.ts` |
| Security | Security guidance plus hardened approval and execution boundaries | `tests/plugins/test_security_guidance_plugin.py` |

The complete per-feature owner, public surface, upstream overlap, Windows
requirement, tests, and integration policy are recorded in `FEATURES.yaml`.

## 6. Windows Tier-1 support contract

Tier-1 coverage includes native drive paths, MSYS `/c/...` and supported WSL
`/mnt/c/...` aliases, NTFS locks, locked executable and extension-module
updates, process trees, applicable Job Object behavior, PowerShell quoting, Git
Bash boundaries, CP932/UTF-8 boundaries, CRLF, venv `Scripts\`, and Electron
stdio pipes.

Runtime qualification covers sleep/resume, network and loopback-provider
recovery, Desktop relaunch, updater handoff, watchdog recovery, llama restart
and hot-swap, embedding restart, and profile/session persistence. The normative
contract is [.codex/WINDOWS_PLATFORM_CONTRACT.md](.codex/WINDOWS_PLATFORM_CONTRACT.md).

## 7. Local AI architecture

Official Hermes provider and model-catalogue contracts remain authoritative.
Downstream local runtimes connect through those contracts: llama.cpp/GGUF via
the local fallback runtime, Hypura through the provider plugin seam, and local
embeddings through Semantic Graph backends and the watchdog-managed loopback
service.

Operator scripts remain under `scripts/windows/`. Runtime plugin entrypoints
remain under `plugins/` so official discovery continues to work.

## 8. Watchdog and recovery architecture

`scripts/windows/watchdog-go` is the sole outer automatic restart authority. It
can supervise the packaged Desktop, publish the prewarmed backend manifest, and
coordinate the configured local embedding process. Desktop, backend, llama,
and embedding components may expose health or request recovery, but they do not
form independent automatic restart loops.

The downstream Python service modules are side-effect-free contracts. Actual
operator startup and deployment remain in the PowerShell and Go surfaces under
`scripts/windows/`.

## 9. Memory and semantic retrieval

The Semantic Graph plugin provides graph storage, hybrid retrieval, embeddings,
fusion, abstention, and cognitive helpers through official plugin and memory
interfaces. The Ebbinghaus provider adds experience and retention policies and
can bridge to Semantic Graph. Both retain isolated plugin entrypoints and
focused test suites.

## 10. VRChat, Unity, and voice integrations

VRChat autonomy tools, observation and relay helpers, the Unity bridge package,
VOICEVOX, Irodori, and other local TTS routes remain downstream-owned features.
They use official plugin, tool, and TTS contracts rather than modifying the core
into a VR- or voice-specific runtime.

External publishing and write actions remain approval-gated. Local generation
does not imply authorization to publish or mutate an external account.

## 11. Installation

The Windows release workflow produces a per-user NSIS installer and a portable
ZIP, then runs clean-install, launch, and upgrade E2E before a stable tag may
publish them. Obtain published artifacts only from the
[downstream Releases page](https://github.com/zapabob/hermes-agent-windows/releases)
and verify `SHA256SUMS.txt`. The current candidate is reported as unsigned
unless its `release-manifest.json` says otherwise. Full instructions are in
[docs/windows/INSTALL.md](docs/windows/INSTALL.md).

The source/development route remains available in PowerShell:

```powershell
git clone https://github.com/zapabob/hermes-agent-windows.git
Set-Location hermes-agent-windows
uv sync --locked --all-extras
uv run hermes --version
uv run hermes setup
```

For Desktop development and a source build:

```powershell
npm ci
npm --workspace apps/desktop run typecheck
npm --workspace apps/desktop run build
```

Review configuration before enabling any 24/7 service or Scheduled Task. API
keys and tokens belong in the profile-scoped Hermes secret store or `.env` as
documented by Hermes; non-secret settings belong in `config.yaml`.

## 12. Update and upstream integration policy

Upstream is an integration input, not the downstream product authority. Each
campaign freezes an exact SHA in `.codex/UPSTREAM_SNAPSHOT.json`, classifies its
commits in `UPSTREAM_ADOPTION.yaml`, and records direct carry in `CARRY.yaml`.
`scripts/upstream/snapshot_sync.py` accepts an explicit SHA and never resolves a
moving latest branch.

Official public APIs are preferred. Security and data-integrity fixes are
composed with stronger verified downstream properties. A downstream feature is
not removed merely because upstream adds a similar name; replacement requires
parity evidence.

## 13. Architecture

Fork-owned Python boundaries live under `downstream/`: `compat/hermes` delegates
to official contracts, `platform/windows` owns native policy, `services` defines
long-lived service contracts, and `features` validates the product ledger.
There is deliberately no top-level Python package named `platform`.

Core Hermes remains the narrow waist. Plugins and skills hold capabilities,
profile-aware official path helpers own state paths, and prompt-cache and
message-role invariants remain mandatory.

## 14. Security

Do not commit secrets, personal runtime data, profile databases, model files,
local artifacts, or generated credentials. Keep write, publish, destructive,
and shell actions behind explicit approval. Child service environments should
project only required variables rather than inherit ambient credentials.

Security gates check the locked Python graph, Python advisories, production npm
advisories, Go module integrity, OSV results, supply-chain policies, and the
repository's security regression tests. A green local unit test is not a
substitute for exact-head CI or live runtime evidence.

## 15. Upstream project

Original Hermes Agent is maintained by Nous Research:
[NousResearch/hermes-agent](https://github.com/NousResearch/hermes-agent).

The official upstream installer, website, documentation, issue tracker, and
support channels apply to the upstream distribution. They do not install or
endorse this downstream repository.

## 16. License and attribution

This downstream remains licensed under the repository's MIT License. Original
Hermes Agent copyright and contributor history are preserved. Downstream work
is maintained independently by the fork contributors; upstream and downstream
issues, releases, and product claims must remain clearly distinguished.
