# Hermes Agent Windows Workstation Edition

<p align="center">
  <a href="README.md" lang="en-GB"><strong>King's English</strong></a> ·
  <a href="README.ja.md" lang="ja">日本語</a> ·
  <a href="README.zh-CN.md" lang="zh-CN">简体中文</a>
</p>

> [!NOTE]
> This English `README.md` is the canonical overview. The Japanese and
> Simplified Chinese READMEs mirror the same product boundaries and install
> contract.

**Unofficial Windows-native downstream of [Hermes Agent](https://github.com/NousResearch/hermes-agent)**
for operators who run Hermes as a long-lived workstation: Electron Desktop,
CLI, messaging gateway, profiles, local inference, semantic memory, automation
and optional edge integrations — one source tree, one core.

Maintained independently at
[zapabob/hermes-agent-windows](https://github.com/zapabob/hermes-agent-windows).
Not affiliated with or endorsed by Nous Research. Upstream attribution and the
[MIT licence](LICENSE) are retained.

[![Windows Workstation Tier-1 CI](https://github.com/zapabob/hermes-agent-windows/actions/workflows/fork-cicd.yml/badge.svg)](https://github.com/zapabob/hermes-agent-windows/actions/workflows/fork-cicd.yml)

**Source version: 0.23.0** (`2026.10.28`) · channels: `stable`, `preview`

<details>
<summary><strong>日本語 / 简体中文 — short note</strong></summary>

- **日本語:** Windows 常時稼働向けの非公式派生です。CLI・Desktop・Gateway・profile・
  ローカル推論・記憶・自動化を同一 core で扱います。詳細は [日本語版](README.ja.md)。
- **简体中文:** 面向 Windows 常驻工作站的非官方下游。CLI、Desktop、Gateway、profile、
  本地推理、记忆与自动化共用同一 core。详见 [简体中文版](README.zh-CN.md)。

</details>

---

## At a glance

| You get | You keep |
| --- | --- |
| Native Windows 11 x64 as a Tier-1 target | Official Hermes CLI / session / profile / tool / MCP contracts |
| Electron Desktop with a single backend owner | Upstream MIT history and contributor credit |
| Local llama.cpp/GGUF beside remote providers | Evidence-based upstream adoption (exact SHAs, not blind merges) |
| Semantic Graph + Ebbinghaus memory seams | Profile isolation for config, secrets, sessions and gateway state |
| Gateway, cron, skills, MCP, delegation, kanban | Prompt-cache stability and role-alternation invariants |

Version `0.23.0` is the **downstream product identity**. It does **not** claim
blanket semantic parity with every later upstream commit. Open semantic-refresh
families stay open until source, tests, mutation evidence, CodeGraph and review
are closed. See [Version & provenance](#version--provenance).

---

## Quick start (source route)

**Requirements:** Windows 11 x64 · PowerShell · Git · [`uv`](https://docs.astral.sh/uv/) · Python 3.11–3.13  
Node.js is required only when building Desktop from source.

```powershell
git clone https://github.com/zapabob/hermes-agent-windows.git
Set-Location hermes-agent-windows
uv sync --locked --all-extras
uv run hermes setup
uv run hermes chat
```

Same checkout, packaged Desktop flow:

```powershell
uv run hermes desktop
```

Installer / portable ZIP: confirm the asset on
[Releases](https://github.com/zapabob/hermes-agent-windows/releases), verify
`SHA256SUMS.txt`, then follow
[docs/windows/INSTALL.md](docs/windows/INSTALL.md).

> First `uv sync` and native builds take longer than the command list suggests.
> A push to `main` is **not** proof that a stable installer was published.

Workstation restart from the Documents checkout only — **never** from `.worktrees/`:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts\windows\Restart-HermesFullStack.ps1
```

---

## Surfaces

One `AIAgent` core behind four operators:

| Surface | Role |
| --- | --- |
| **CLI** | Interactive chat, setup wizard, tools, skills, update, doctor |
| **Electron Desktop** | Native chat UI, profiles, Security Center, Bot Mode, Git/review panes |
| **Gateway** | Long-lived messaging across Telegram, Discord, Slack, LINE, Signal, … |
| **TUI** | Ink terminal UI over stdio JSON-RPC |

Capabilities grow at the **edges** (plug-ins, skills, MCP, service-gated tools) —
not by inflating the core tool footprint on every API call.

---

## What's new in 0.23.0

Windows-native feature intake —
[`docs/windows/feature-intake-20261028/`](docs/windows/feature-intake-20261028/):

| Area | Behaviour |
| --- | --- |
| Subagent settings | Dedicated Desktop Settings page; one Apply saves the full `delegation` draft after server-side validate→merge |
| Plugin OAuth | Manifest `oauth:` + `hermes auth …`; host attaches Bearer — plugins never receive tokens |
| `ask_choice` | `PluginContext.ask_choice` binds to each surface's clarify prompt; unbound/headless → `None` |
| Vault keychain | Opt-in `vault.key_storage: keychain`; default remains `file` |
| `ctx.files` | Desktop grant API: picker-only roots, opaque handles, Windows path hardening |
| MCP / updates / compaction | Call-unit progress sink, shared plugin-update core, durable `post_compaction` hooks |

### Local-model stability (128K llama-server)

Auto-compaction against a large local context used to fail with
`context_compression_timeout` when the KV cache spilled out of VRAM. This tree:

- clamps context to a VRAM-resident budget via
  `scripts/windows/Get-LlamaContextBudget.ps1`;
- bounds summarizer input in **tokens** (not characters) for CJK-safe compression;
- widens local no-progress / total ceilings;
- supports deferred tool schemas to shrink request baselines;
- keeps compression timeouts retryable without dropping the user turn.

Measured effect on the reference 27B workstation path: prefill recovered from
~11 tok/s to ~550–1,000 tok/s and auto-compaction completes again.

---

## Why this fork exists

- **Windows as a first-class runtime** — paths, process identity, PowerShell
  transport, NTFS locks, Electron IPC, update handoff, installer/portable and
  the Go watchdog have native Windows tests. Linux cross-compile is not Windows
  evidence.
- **One Desktop backend owner** — Electron main owns the destructive Desktop
  backend lifecycle. Observing a PID, port or token does **not** grant a second
  owner authority.
- **Local inference without forking the provider model** — the same picker
  reaches remote providers, OAuth routes or local llama.cpp/GGUF. Generation and
  embedding are separate services with separate readiness evidence.
- **Memory at official seams** — Semantic Graph (graph + embeddings + hybrid
  retrieval) and Ebbinghaus (cognitive retention) compose through the Hermes
  memory-provider contract.
- **Bot Mode by name, not by dangling pointer** — one bot = one forever-chat
  resolved as `(profile, session titled exactly "Bot Chat")`. No canonical
  session-id pin.
- **Long-lived automation** — Gateway, cron, skills, MCP, delegation and kanban
  share the same session/profile state model.
- **Edge integrations** — VRChat/Unity, voice/TTS, AITuber, OSINT/Shinka, Office
  and similar live as plug-ins or optionals, not hard-wired core deps.
- **Security Center** — deterministic scan, evidence, update state and encrypted
  quarantine; mutations require explicit confirmation.
- **Evidence-driven upstream intake** — exact frozen SHAs and observable
  contracts. Blind merge/rebase or a version string alone is not compatibility
  proof.

Product ledger: [`FEATURES.yaml`](FEATURES.yaml) · carried patches:
[`CARRY.yaml`](CARRY.yaml) · adoption map: `UPSTREAM_ADOPTION.yaml` · policy:
[`DOWNSTREAM_POLICY.md`](DOWNSTREAM_POLICY.md)

---

## Architecture in brief

```text
┌─────────────┐  ┌──────────────┐  ┌──────────┐  ┌─────────┐
│ CLI / setup │  │ Electron UI  │  │ Gateway  │  │   TUI   │
└──────┬──────┘  └──────┬───────┘  └────┬─────┘  └────┬────┘
       │                │               │             │
       └────────────┬───┴───────────────┴─────────────┘
                    ▼
              AIAgent core
     (prompt cache · tools · memory · providers)
                    │
     ┌──────────────┼──────────────────────────┐
     ▼              ▼                          ▼
 plugins/skills   MCP / cron / kanban     local llama / embeddings
```

Sacred invariants (do not break casually):

1. **Per-conversation prompt caching** — mutating past context or swapping
   toolsets mid-turn destroys the KV cache and multiplies API cost.
2. **Narrow waist, capability at the edges** — new work prefers CLI/skill →
   service-gated tool → plug-in → MCP before a new core tool.
3. **Session-scoped surface capability** — Desktop features resolve from
   `session.platform`, not a static `HERMES_DESKTOP` environment bit.
4. **Deterministic, reversible execution** — destructive ops need recovery paths,
   auditability and approvals.

Normative Windows contract:
[`.codex/WINDOWS_PLATFORM_CONTRACT.md`](.codex/WINDOWS_PLATFORM_CONTRACT.md)

---

## Ownership & recovery

| Component | Lifecycle owner |
| --- | --- |
| Desktop `serve` backend | Electron main only |
| Generation llama-server | Operator / launcher scripts |
| Embedding llama-server (when watchdog-spawned) | Go watchdog |
| Messaging gateway | Gateway process (survives Desktop quit by design) |
| WebUI / fixed-port dashboard | Separate from Desktop `serve --port 0` |

The Go watchdog observes health and may manage an embedding server **it**
started. It must not become a parallel Desktop backend owner. Exact process
identity beats argv-substring guesses.

Guide: [`scripts/windows/watchdog-go/README.md`](scripts/windows/watchdog-go/README.md)

---

## Plug-ins & submodules

```powershell
uv run hermes plugins
```

Representative families (counts change; runtime enablement depends on profile +
credentials):

| Area | Examples |
| --- | --- |
| Desktop / ops | `hermes-bot-mode`, `desktop-dashboard`, `implementation_router` |
| Memory | `semantic_graph`, `memory/ebbinghaus`, `surfsense` |
| Media / XR | `voicevox_tts`, `vrchat-autonomy`, `unity_vrchat_bridge`, `aituber_onair` |
| Research | `shinka-osint`, `world-intel-osint` |
| Providers | `openai-codex`, `qwen-oauth`, `xai`, `hypura` |

`implementation_router` is **opt-in**: isolated planner→worker→verify→reviewer
workflow. It does not replace the normal picker, delegation, MoA or fallback,
and never auto-applies or publishes.

Optional Git submodules (only when you need that external runtime):

```powershell
git submodule update --init --recursive
```

Snapshot inventory: [`docs/windows/INTEGRATIONS.md`](docs/windows/INTEGRATIONS.md)

---

## Install & Desktop build

```powershell
git clone https://github.com/zapabob/hermes-agent-windows.git
Set-Location hermes-agent-windows
uv sync --locked --all-extras
uv run hermes --version
uv run hermes setup
```

Desktop from source (Node version per
[`apps/desktop/package.json`](apps/desktop/package.json)):

```powershell
npm ci
npm run typecheck --workspace apps/desktop
npm run build --workspace apps/desktop
```

Packaging / replacing a running `Hermes.exe` is a separate, ownership-aware
step. Stop the owned process before swapping the binary.

Secrets live in profile `.env` (or external secret stores). Non-secret settings
live in `config.yaml`. Never commit model weights, profile DBs or tokens.

---

## Version & provenance

| Fact | Value |
| --- | --- |
| Downstream product version | `0.23.0` (`version_source: downstream`) |
| Upstream stable reference (R2) | `f97608f178d1ffeca59860195ab7da295f7c8e5f` (`0.21.5` / `v2026.9.24`) |
| Active semantic-refresh ceiling (U1) | `678a4762b887f3eabe5cad11254b2ab1ae859485` |
| Historical provenance snapshot | `b51c055a12220f8c7c18660e8599365012e19532` |

Handoff plan:
[`docs/windows/semantic-refresh-20260926/CURSOR_IMPLEMENTATION_PLAN_20260929.md`](docs/windows/semantic-refresh-20260926/CURSOR_IMPLEMENTATION_PLAN_20260929.md)

Built-in updater shape:
`plan → snapshot → apply → restart-per-kind → verify → report`.

---

## Security

- Do not commit secrets, personal runtime data, model files or investigation artefacts.
- Mutating Security Center APIs require explicit confirmation.
- `hermes security`, `hermes egress`, `hermes secrets` cover scan / egress policy /
  external vaults.
- Provider base URLs are masked before logs; children receive bounded env maps.

**Control MCP:** auth / journal / coordinator contracts exist, but **production
write remains DISABLED** until host grant-revocation, linearisation, trusted
producer binding and writer fences are all closed. Tests alone do not authorise
enabling that path. See
[`docs/control-mcp/IMPLEMENTATION_LOG.md`](docs/control-mcp/IMPLEMENTATION_LOG.md).

---

## Docs map

| Doc | Purpose |
| --- | --- |
| [`docs/windows/INSTALL.md`](docs/windows/INSTALL.md) | Canonical Windows install |
| [`docs/windows/INTEGRATIONS.md`](docs/windows/INTEGRATIONS.md) | Optional integrations snapshot |
| [`docs/windows/SECURITY_CENTER.md`](docs/windows/SECURITY_CENTER.md) | Security Center |
| [`docs/windows/feature-intake-20261028/`](docs/windows/feature-intake-20261028/) | 0.23.0 intake notes |
| [`AGENTS.md`](AGENTS.md) | Engineering contracts for assistants & developers |
| [`SECURITY.md`](SECURITY.md) | Security policy |

---

## Upstream project

Original project: [NousResearch/hermes-agent](https://github.com/NousResearch/hermes-agent).  
Upstream docs, installers, releases and support apply to **upstream** only —
they do not install or endorse this downstream.

---

## Licence & attribution

Hermes Agent is developed by Nous Research under the MIT Licence. This
downstream retains that attribution, copyright and contributor history, and
ships under the same [MIT licence](LICENSE).

Windows / workstation changes are maintained independently here. Issue
trackers, releases, support claims and qualification evidence for upstream and
downstream remain separate.
