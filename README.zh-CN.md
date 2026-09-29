# Hermes Agent Windows Workstation Edition

<p align="center">
  <a href="README.md" lang="en-GB">King's English</a> ·
  <a href="README.ja.md" lang="ja">日本語</a> ·
  <a href="README.zh-CN.md" lang="zh-CN"><strong>简体中文</strong></a>
</p>

> [!NOTE]
> 英文版 `README.md` 是规范正本。本简体中文版逐节跟随英文版更新。

Hermes Agent 的非官方 Windows 原生下游版本，提供 Electron 桌面端、CLI、消息 gateway，
以及可选的本地推理、记忆与语音集成。

这个 fork 由一名维护者独立维护，不隶属于 Nous Research，也未获得其认可。下游仓库位于
[zapabob/hermes-agent-windows](https://github.com/zapabob/hermes-agent-windows)。
原版 [Hermes Agent](https://github.com/NousResearch/hermes-agent) 由 Nous Research 开发；
本仓库保留 upstream 归属声明与 [MIT License](LICENSE)。

[![Windows Workstation Tier-1 CI](https://github.com/zapabob/hermes-agent-windows/actions/workflows/fork-cicd.yml/badge.svg)](https://github.com/zapabob/hermes-agent-windows/actions/workflows/fork-cicd.yml)

**当前源码版本：0.21.5。** 产品元数据与 upstream stable R2
`f97608f178d1ffeca59860195ab7da295f7c8e5f`（`v2026.9.24`）保持一致。
本 fork 继续使用 `version_source: downstream`，并保留历史 provenance snapshot
`b51c055a12220f8c7c18660e8599365012e19532`。

版本号 0.21.5 并不表示已经对之后所有 upstream commit 完成语义等价审查。当前
semantic-refresh campaign 固定到 ceiling
`678a4762b887f3eabe5cad11254b2ab1ae859485`，按 family 分别核对 source、test、mutation、
CodeGraph 与 review 证据。当前交接计划见
[docs/windows/semantic-refresh-20260926/CURSOR_IMPLEMENTATION_PLAN_20260929.md](docs/windows/semantic-refresh-20260926/CURSOR_IMPLEMENTATION_PLAN_20260929.md)。
支持的 channel 为 `stable` 与 `preview`；main 分支的 push 本身不是 stable installer 已发布的证据。

## 30 秒看懂安装

> **TL;DR：**依次运行下面五条命令。模型提供商可在设置向导中配置；核心CLI无需安装
> 可选插件或初始化Git子模块。

当前可立即使用的是源码安装。请准备 Windows 11 x64、PowerShell、Git、`uv` 和
Python 3.11–3.13。只有构建 Desktop 时才需要 Node.js。

```powershell
git clone https://github.com/zapabob/hermes-agent-windows.git
Set-Location hermes-agent-windows
uv sync --locked --all-extras
uv run hermes setup
uv run hermes chat
```

这是可在30秒内读完的命令路径；首次下载依赖和原生构建需要更长时间。要从同一 checkout
启动 Desktop，请运行：

```powershell
uv run hermes desktop
```

如果需要 installer 或 portable ZIP，请先确认
[下游 Releases](https://github.com/zapabob/hermes-agent-windows/releases)
已经发布对应 asset，并用 `SHA256SUMS.txt` 校验。完整步骤见
[Windows 安装指南](docs/windows/INSTALL.md)。

## 这个 fork 增加了什么

- **把 Windows 作为一级运行目标。** 对 path、process identity、PowerShell、NTFS、
  Electron IPC、update/relaunch、installer/portable 与 Go watchdog 进行原生 Windows 验证。
- **Desktop backend 只有一个破坏性 lifecycle owner。** Electron main 负责 Desktop backend；
  Go watchdog 负责辅助 status/recovery，并且只有对它自己启动和拥有的 embedding
  `llama-server` 才具有破坏性管理权限。
- **保留正常的 Hermes provider/model picker。** OAuth、API key、custom/local endpoint 与
  llama.cpp/GGUF 都走同一 provider architecture；fallback、普通 delegation、MoA 与
  reasoning effort 仍是相互独立的功能。
- **Semantic Graph 与 Ebbinghaus。** 可在官方 memory seam 上组合 graph storage、embedding、
  hybrid retrieval 与独立 cognitive-memory provider。
- **保持 Desktop 的 profile/session 契约。** Bot Mode 的 canonical forever-chat 通过
  `(profile, "Bot Chat")` 解析，不持久化 canonical session-id pointer。
- **长时间运行的 Gateway 与 automation。** messaging、cron、skills、MCP、delegation、
  kanban 共用同一 core/session/profile model。
- **VRChat/Unity、voice/TTS、AITuber、OSINT/Shinka 等保留在 edge integration。**
  它们通过 plug-in/skill/provider seam 扩展，而不是分叉 core。
- **Security Center。** 提供确定性的 scan、evidence、update state 与 encrypted quarantine，
  mutation 必须经过明确确认。
- **以证据方式吸收 upstream。** 使用 exact SHA 与 observable contract，整体 merge/rebase 或
  版本号本身都不作为 compatibility 证明。

## 插件与Git子模块

按 profile 查看实际启用的插件：

```powershell
uv run hermes plugins
```

仓库包含 workstation root plug-in，以及 `plugins/model-providers/`、`plugins/memory/`、
`plugins/platforms/`、`plugins/web/` 等专用 family。数量会随代码树变化，因此 README 不再把
固定计数当作契约。代表性的能力包括 `hermes-bot-mode`、`desktop-dashboard`、
`semantic-graph`、`implementation_router`、`vrchat-autonomy`、`unity-vrchat-bridge`、
`shinka-osint`、`openai-codex` 与 `qwen-oauth`。

`implementation_router` 是 **opt-in** 的隔离顺序式 engineering workflow。它使用现有
auxiliary picker 与 parent-owned inference，不替代普通 model picker、delegation、MoA 或
fallback；也不会自动把验证后的 workspace 应用到 source checkout，或自行发布 PR。

Git submodule 只用于可选 integration；需要相应外部 runtime 时再初始化：

```powershell
git submodule update --init --recursive
```

更广泛的清单见 [docs/windows/INTEGRATIONS.md](docs/windows/INTEGRATIONS.md)。该文档是 snapshot；
当前 runtime inventory 应以 `uv run hermes plugins` 为准。

## 1. 产品定位

Hermes Agent Windows Workstation Edition 是面向持续运行的本地 AI 工作站的 Windows 优先
下游发行版。它保留 Hermes CLI 命令、公开契约、插件模型和 upstream 历史，同时为 Windows
原生行为、本地模型、记忆、语音、VR/Unity 与恢复机制维护明确的下游策略。

产品功能台账位于 [FEATURES.yaml](FEATURES.yaml)。保留在 upstream 所有文件中的直接补丁由
[CARRY.yaml](CARRY.yaml) 单独追踪，upstream commit 在 `UPSTREAM_ADOPTION.yaml` 中分类。
策略摘要见 [DOWNSTREAM_POLICY.md](DOWNSTREAM_POLICY.md)。

## 2. Windows 优先目标

主要目标平台是配备原生 Python、原生 Node/Electron、交互式桌面和消费级 NVIDIA GPU 的
Windows 11 x64。设计支持本地 LLM 与 embedding 服务、语音服务、VRChat/Unity 集成及
远程管理的持续运行。

无论 upstream 如何安排平台优先级，Windows 都是独立的 Tier-1 目标。原生行为在
`windows-latest` 上测试；Linux 交叉编译不能作为 Windows 运行时证据。后台 Git 与 web
helper 调用使用隐藏进程创建标志，Git wrapper 将非交互 probe 与面向用户的 terminal 分离。
这针对的是已知的 helper 启动路径，并不意味着已消除所有可能的控制台来源。

## 3. 适用人群

本发行版面向维护 Windows AI 工作站，并需要从源码层面控制本地推理、长期运行服务、记忆、
桌面行为与恢复机制的运维人员和开发者。使用者应熟悉 PowerShell、Git、Python 环境、
Node 工具以及 CI 结果的阅读。

如果需要最简洁的 Hermes 官方安装方式和 upstream 支持模式，请使用第 15 节链接的原版项目。

## 4. 下游优势

- **无供应商锁定。** 所有 provider 均为可选。OAuth 登录（OpenAI Codex/ChatGPT、xAI Grok、
  Qwen、MiniMax、Nous Portal）、已有的 Claude Code OAuth 凭据、自己的 API key 或本地
  llama.cpp server 都通过同一个 provider registry 工作。`hermes proxy` 把 OAuth provider
  暴露为本地 OpenAI 兼容 endpoint，`hermes fallback` 在主 provider 失败时串联其他 provider。
- **Windows 运行时与恢复契约。** Desktop backend 只有一个所有者，Go watchdog 仅作辅助
  （第 8 节）。
- **本地推理。** `scripts/windows/` 下的 llama.cpp/GGUF fallback、hot-swap preset 与
  按 GPU 区分的 launcher，以及 Hypura provider 与 harness（`hermes harness`）。
- **记忆。** Semantic Graph hybrid retrieval 与 Ebbinghaus cognitive memory provider
  （第 9 节）。
- **工程 workflow。** `implementation_router` plugin 通过现有 auxiliary model picker
  依次运行 planner、worker、确定性验证与 reviewer 阶段，入口为 `engineering_run` 或
  `/engineer`。它是 opt-in 的隔离 workflow，不替代普通 model picker、delegation、MoA、
  fallback，也不会自动 apply 或 publish。
- **集成。** 本地秘书、VRChat/Unity、本地语音、AITuber、OSINT/Shinka、Desktop 的
  Git/review pane，以及隔离的 Antigravity CLI bridge（`hermes-antigravity`）。
- **凭据卫生。** credential lease 始终绑定所选 entry；空的 credential pool 无法以继承的
  client 启动委派 child；provider base URL 在写入日志前会被遮蔽。

这些能力通过官方 Hermes API 组合运行。本 fork 不会为 session、approval、profile、
gateway、model catalogue 或 tool registry 建立并行的权威来源。

## 5. 已验证功能矩阵

| 领域 | 已验证实现 | 契约证据 |
| --- | --- | --- |
| Windows runtime | 原生 path、process、IPC、NTFS handoff、terminal、credential、power 与 GPU helper | `tests/downstream/test_windows_contracts.py` |
| Desktop backend | 由 Electron main 负责的单一所有者 backend lifecycle | `apps/desktop/electron/single-owner-backend-lifecycle.test.ts` |
| Recovery | 具备只读 status 与精确 identity 权限的外部 Go watchdog | `scripts/windows/watchdog-go/authority_test.go` |
| Local inference | llama.cpp/GGUF fallback 与 hot-swap script | `tests/hermes_cli/test_llama_fallback_runtime.py` |
| Local embeddings | watchdog embedding lifecycle 与 Semantic Graph backend | `scripts/windows/watchdog-go/embedding_test.go` |
| Local secretary | 基于官方 agent boundary 的 read/write action 分离 | `tests/downstream/test_upstream_api_contracts.py` |
| Providers | Hypura/local provider 集成 | `tests/fork/test_hypura_oai_proxy.py` |
| Provider fallback | fallback chain 与 provider rotation | `tests/hermes_cli/test_fallback_chain.py` |
| Memory | Semantic Graph hybrid retrieval 与 Ebbinghaus cognitive extension | `tests/plugins/test_semantic_graph_registration.py`, `tests/plugins/test_ebbinghaus_plugin.py` |
| Engineering workflow | 带 route admission 的顺序式 planner/worker/reviewer router | `tests/implementation_router/test_route_admission.py` |
| VR and Unity | VRChat autonomy tooling 与 Unity bridge | `tests/plugins/test_vrchat_autonomy_plugin.py` |
| Voice | Irodori、VOICEVOX 与 local TTS route | `tests/plugins/test_irodori_tts_plugin.py` |
| AITuber | AITuber OnAir 与 AITuber Kit plugin | `tests/plugins/test_aituber_onair_plugin.py` |
| OSINT/Shinka | Shinka、SitDeck、WorldMonitor 与 OSINT plugin surface | `tests/plugins/test_shinka_osint_plugin.py` |
| Desktop | 通过官方 Desktop IPC 与 pane contract 扩展 Git/review | `apps/desktop/electron/git-review-ops.test.ts` |
| Bot Mode | 通过 `(profile, "Bot Chat")` 解析 canonical forever-chat | `apps/desktop/src/plugins/hermes-bots/tests/canonical-chat-registry.test.mjs` |
| Security | security guidance 与强化的 approval/execution boundary | `tests/plugins/test_security_guidance_plugin.py` |
| Control MCP | auth/journal/coordinator contract；production write 保持 DISABLED | `docs/control-mcp/IMPLEMENTATION_LOG.md` |

每项功能的所有者、公开 surface、upstream 重叠范围、Windows 要求、测试和集成策略，
均记录在 `FEATURES.yaml` 中。原先由 watchdog 管理的 Desktop backend 在其中标记为
retired。这些是范围明确的检查，并非对每个可选集成的资格认定。

## 6. Windows Tier-1 支持契约

Tier-1 覆盖原生 drive path、MSYS `/c/...` 与受支持的 WSL `/mnt/c/...` alias、NTFS lock、
已锁定 executable 与 extension module 的 update、process tree、适用的 Job Object 行为、
PowerShell quoting、Git Bash boundary、CP932/UTF-8 boundary、CRLF、venv `Scripts\`，
以及 Electron stdio pipe。

运行时资格验证覆盖 sleep/resume、network 与 loopback provider 恢复、Desktop relaunch、
updater handoff、watchdog 恢复、llama restart 与 hot-swap、embedding restart，
以及 profile/session persistence。规范契约见
[.codex/WINDOWS_PLATFORM_CONTRACT.md](.codex/WINDOWS_PLATFORM_CONTRACT.md)。
原生 Python、Desktop、installer、portable、upgrade、watchdog 与 security 检查是彼此独立的
gate；仅靠 mock 的结果或被跳过的 P0 测试不能认定 Windows 支持。

## 7. 本地 AI 架构

官方 Hermes provider 与 model catalogue 契约仍是权威来源。下游本地运行时通过这些契约接入：
llama.cpp/GGUF 作为 local fallback runtime，Hypura 作为 provider plugin seam，local
embedding 作为 Semantic Graph backend 并配合 watchdog 管理的 loopback service。hot-swap
preset 选择单独安装的 GGUF 文件；推理就绪需要真实的模型响应，而不只是端口已打开。

运维脚本位于 `scripts/windows/` 下（例如 `start-llama-hotswap.ps1`、
`switch-llama-hotswap.ps1` 以及按 GPU 区分的 `start-hermes-llama-fallback-*.ps1`
launcher）。运行时 plugin entrypoint 保留在 `plugins/` 下，使官方 discovery 能够继续工作。
对本地服务的远程访问通过 `Manage-HermesTailscaleServe.ps1`（Tailscale Serve）配置，
并提供仅验证模式。

## 8. Watchdog 与恢复架构

在受支持的 Windows 拓扑中，Desktop Python backend 的 lifecycle 由 Electron main 独占。
health 观测、PID、端口、token 或 manifest 都不会授予其他组件破坏性的 lifecycle 权限。

外部 Go watchdog 是具有只读 status surface 的辅助 supervisor。其受支持的破坏性操作范围
仅限于它明确启动并拥有的 embedding `llama-server` 实例；它不是 Desktop backend 的第二个
所有者。旧的 watchdog backend 所有权与 Desktop 重新启动路径均已移除。参见
[watchdog 指南](scripts/windows/watchdog-go/README.md) 与
[Windows platform contract](.codex/WINDOWS_PLATFORM_CONTRACT.md)。

下游 Python service module 是无副作用的契约。实际的 operator startup 与 deployment
仍由 `scripts/windows/` 下的 PowerShell 和 Go surface 负责。

## 9. 记忆与 semantic retrieval

profile 隔离配置、凭据、session 与记忆。Semantic Graph plugin 通过官方 plugin 与 memory
interface 提供 graph storage、hybrid retrieval、embedding、fusion、abstention 和
cognitive helper。Ebbinghaus provider 增加 experience 与 retention policy，并可连接
Semantic Graph。两者均保留独立的 plugin entrypoint 与针对性的 test suite。

外部 memory provider（上表中的 Honcho、Mem0、Supermemory、Hindsight 等）通过
`hermes memory` 选择，`hermes journey` 可查看已学习的 skill 与记忆随时间的变化。
源码发行包不包含模型文件或个人记忆。

## 10. VRChat、Unity 与语音集成

VRChat autonomy tool、observation/relay helper、Unity bridge package、VOICEVOX、
Irodori 及其他 local TTS route 都是下游所有的功能。它们使用官方 plugin、tool 与
TTS contract，而不会把 core 改造成 VR 或语音专用 runtime。相关 SDK、应用与硬件需单独配置。

外部发布与写入 action 仍须明确 approval。本地生成不代表获得向外部 account 发布内容或
修改其状态的授权。

## 11. 安装

目标平台为 Windows 11 x64。请使用 PowerShell、Git、`uv` 与 Python 3.11–3.13。依赖安装
可能需要数分钟，可选 extra 可能需要原生构建工具。原生应用不需要 WSL。

```powershell
git clone https://github.com/zapabob/hermes-agent-windows.git
Set-Location hermes-agent-windows
uv sync --locked --all-extras
uv run hermes --version
uv run hermes setup
```

设置向导用于选择模型 provider。使用远程 provider 时 GPU 为可选。本地模型需要另行准备的
模型文件与兼容的推理运行时；本仓库不包含模型权重。

Windows release workflow 会生成用户级 NSIS installer 与 portable ZIP，并在 stable
tag 发布前执行 clean install、启动与 upgrade E2E。只从
[下游 Releases](https://github.com/zapabob/hermes-agent-windows/releases)
获取已发布产物，并核对 `SHA256SUMS.txt`。除非 `release-manifest.json` 另有记录，
当前 candidate 按 unsigned 处理。完整步骤以 [Windows 安装指南](docs/windows/INSTALL.md)
为准；其中的旧版本示例并不能证明 0.21.5 已发布。

官方 upstream installer 面向 upstream 产品；本发行版请使用本下游仓库或其已发布的
release asset。

### 构建 Desktop

请使用 [`apps/desktop/package.json`](apps/desktop/package.json) 接受的 Node.js 版本。
Desktop 是 npm workspace，因此请在仓库根目录安装 JavaScript 依赖。

```powershell
npm ci
npm run typecheck --workspace apps/desktop
npm run build --workspace apps/desktop
```

构建会生成应用文件。打包与安装新的 Desktop binary 是单独的操作。请勿在进程运行时替换
executable。

启用任何全天候 service 或 Scheduled Task 前，请先检查配置。API key 与 token 应存放在
profile-scoped Hermes secret store 中，或按照 Hermes 文档保存到 `.env`；非 secret 设置
应放入 `config.yaml`。

## 12. 更新与 upstream 集成策略

upstream 是集成输入，不把持续变化的 source tree 直接作为下游正本。semantic-refresh
campaign 以 exact SHA、inventory、source/caller mapping、focused regression、必要的 mutation、
CodeGraph 与独立 review 按 family 闭合。

| 输入 | SHA | 含义 |
| --- | --- | --- |
| R2 | `f97608f178d1ffeca59860195ab7da295f7c8e5f` | upstream 0.21.5 / `v2026.9.24` stable release |
| U1 | `678a4762b887f3eabe5cad11254b2ab1ae859485` | 当前 campaign 的固定 newer-upstream ceiling |
| historical snapshot | `b51c055a12220f8c7c18660e8599365012e19532` | 保留的 provenance anchor |

当前 `main` 已包含多个经过映射的 Windows/runtime 修复，包括 process identity、
relaunch/recovery 与 Desktop E2E isolation。但在所有 in-scope ledger row 都有证据映射或明确
disposition 之前，整个 campaign 仍不算完成。0.21.5 是 product version，不是 semantic parity
的捷径。

更新流程保持 `plan → snapshot → apply → restart-per-kind → verify → report`。Desktop、gateway、
generation llama、embedding 与 Go watchdog 各自具有独立 lifecycle，需要分别验证 owner 与
readiness。

## 13. 架构

fork 所有的 Python boundary 位于 `downstream/`：`compat/hermes` 委托给官方 contract，
`platform/windows` 负责 native policy，`services` 定义 long-lived service contract，
`features` 验证 product ledger。项目刻意不创建名为 `platform` 的 top-level Python package。

共享的 agent core 位于 CLI、消息 gateway、TUI 与 Electron Desktop 之后。围绕它的有集中式
slash command registry、cron 调度、多 profile kanban board、subagent 委派、skill curator、
Mixture of Agents（`hermes moa`）、MCP client 与 server（`hermes mcp`）、ACP 以及 profile。
core 继续保持为狭窄的公共边界：capability 由 plugin 与 skill 承载，state path 由
profile-aware 的官方 path helper 管理，prompt cache 与 message role invariant 始终是强制要求。

Bot Mode 同样遵循 session/profile 契约。一个 bot 的 canonical chat 由该 profile 下 exact title
`Bot Chat` 的 registry identity 每次重新解析，不持久化 canonical session-id pointer；side-chat
继续作为独立 session 存在。

## 14. 安全

请勿 commit secret、个人 runtime data、profile database、model file、local artifact 或
生成的 credential。write、publish、destructive 与 shell action 必须置于明确 approval
之后。child service environment 只应传递必要 variable，不应继承 ambient credential。

provider base URL 在写入日志前会被遮蔽。除非在 `config.yaml` 中设置
`telemetry.relay.propagate_trace_headers: true`，Relay 0.8 的 trace-context header
（`traceparent`、`tracestate`、`baggage`）会从 provider 调用中移除。`hermes security`
执行 supply-chain 审计与 Windows 工作站恶意软件防护，`hermes egress` 管理凭据注入式
egress 防火墙，`hermes secrets` 连接 Bitwarden、1Password 等外部 secret 来源。

security gate 会检查锁定的 Python graph、Python advisory、production npm advisory、
Go module integrity、OSV result、supply-chain policy，以及本仓库的 security regression
test。green 的 local unit test 不能代替 exact-head CI 或 live runtime evidence。请阅读
[SECURITY.md](SECURITY.md)；未解决的 private contract 仍未获资格认定。

Control MCP 已有 auth、strict claim、journal、coordinator 与 evidence contract，但
**production write 仍为 DISABLED**。当前 campaign 中 N07-A1、T06、T12 尚未闭合；real host
grant-revocation writer、grant/claim/effect linearization、trusted producer、独立 apply approval
与 actual writer fence 的证据仍不完整。test 或看似成功的 receipt 不能授权开启该 write path。

## 15. Upstream 项目

原版项目为 [NousResearch/hermes-agent](https://github.com/NousResearch/hermes-agent)。
官方 upstream installer、website、documentation、issue tracker 与 support channel 仅适用于
upstream distribution，它们不会安装或认可本下游仓库。upstream 贡献保留其作者身份与归属。

## 16. 许可证与归属

原版 Hermes Agent 由 Nous Research 开发，并采用 MIT License。本下游版本保留该归属声明、
原版 copyright 与 contributor history，以及 [MIT License](LICENSE)。下游工作独立维护；
upstream 与 downstream 的 issue、release 和产品声明必须清楚区分。
