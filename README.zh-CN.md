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

**当前源码版本：0.21.3。** 记录的 upstream release 同为 0.21.3（`v2026.9.14`）。
本 fork 保持 `version_source: downstream` 与固定的 upstream snapshot
`b51c055a12220f8c7c18660e8599365012e19532`。源码版本或 main 分支的 push 并不代表已经
发布 stable installer。支持的 channel 为 `stable` 与 `preview`。

如果这个 Windows 原生版本对你有帮助，欢迎为仓库点 Star，让更多 Windows 用户发现它。

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

- **自带密钥（BYOK），OAuth 优先。** 运行时不依赖任何必需的托管服务。可通过 OAuth
  登录订阅（OpenAI Codex/ChatGPT、xAI Grok、Qwen、MiniMax、Nous Portal 等），为随附的
  42 个模型 provider 使用自己的 API key，或连接本地 llama.cpp server。Nous Portal 只是
  可选 provider 之一，并非必需。
- Python、Electron、Go、upstream API 兼容、regression 与 security lock 的 Windows Tier-1 CI
- 覆盖非管理员账户与含空格 path 的 installer、portable 与 upgrade E2E
- 固定 upstream snapshot `b51c055a12220f8c7c18660e8599365012e19532`，不使用移动基线
- 通过官方 provider/memory seam 接入的本地 llama.cpp/GGUF 推理与 embedding lifecycle
- 由 Electron main 独占的 Desktop Python backend，以及权限仅限于其自行启动的
  embedding server 的外部 Go watchdog
- 复用现有 model picker、父级推理与无凭据 Docker 执行的顺序式工程 workflow
  （`implementation_router`）
- consumer NVIDIA workstation 实机证据与无 GPU 的 hosted CI 分开记录

## 插件与Git子模块

Hermes通过 `plugin.yaml`、`__init__.py` 和 `register(ctx)` 发现标准目录插件。
下面按用途列出53个随附的标准根插件；`lmcache` 以具有独立注册路径的旧式manifest
提供。运行 `uv run hermes plugins` 可查看当前profile实际启用的插件。

| 领域 | 随附根插件 |
| --- | --- |
| Agent与运维 | `ai-employee-org`, `ai-partner-os`, `airi`, `aituber-onair`, `aituber-kit`, `book-to-skill`, `desktop-dashboard`, `disk-cleanup`, `freebuff`, `freellmapi`, `google-colab`, `google_meet`, `hermes-antigravity`, `hermes-gpt`, `hermes-bot-mode`, `implementation_router`, `line-ai-bot`, `lm-twitterer`, `memory-llm-wiki`, `notebooklm`, `oh-my-hermes`, `openclaw-vendor`, `openmanus`, `plugin-doctor`, `research-desk`, `scrapling-feeds`, `teams_pipeline`, `warashibe-reselling` |
| 媒体、语音与XR | `akari-video`, `buzz`, `fish-audio-tts`, `hakua-tts-bridge`, `heygen`, `hyperframes`, `irodori-tts`, `questframe-fh6vr`, `sillytavern`, `spotify`, `unity-cli`, `unity-vrchat-bridge`, `unsloth-studio`, `voicebox`, `voicevox-tts`, `vrchat-autonomy` |
| 知识、安全与OSINT | `osint-agent`, `security-guidance`, `semantic-graph`, `shinka-osint`, `sitdeck-osint`, `surfsense`, `tookie-osint`, `world-intel-osint`, `worldmonitor-osint` |
| 旧式manifest | `lmcache` |

保留的[集成清单](docs/windows/INTEGRATIONS.md)在其记录时点列出了154个插件manifest；
此后新增了 `hermes-antigravity` 与 `implementation_router`，因此当前代码树共有156个。
专用provider系列由各自的发现器处理，因此只有已配置的能力会进入session。数量描述的是
代码树内容，而非运行时启用状态或资格认定。

| 发现系列 | 随附provider与adapter |
| --- | --- |
| Browser (3) | `browser_use`, `browserbase`, `firecrawl` |
| Cron (1) | `chronos` |
| Dashboard认证 (4) | `basic`, `drain`, `nous`, `self_hosted` |
| 图像生成 (7) | `deepinfra`, `fal`, `krea`, `openai`, `openai-codex`, `openrouter`, `xai` |
| Memory (9) | `byterover`, `ebbinghaus`, `hindsight`, `holographic`, `honcho`, `mem0`, `openviking`, `retaindb`, `supermemory` |
| 模型provider (42) | `actual`, `ai-gateway`, `alibaba`, `alibaba-coding-plan`, `anthropic`, `arcee`, `azure-foundry`, `bedrock`, `commandcode`, `copilot`, `copilot-acp`, `custom`, `deepinfra`, `deepseek`, `fireworks`, `freebuff`, `freellmapi`, `gemini`, `gmi`, `huggingface`, `hypura`, `kilocode`, `kimi-coding`, `meta-ai`, `minimax`, `nebius-token-factory`, `nous`, `novita`, `nvidia`, `ollama-cloud`, `openai-codex`, `opencode-free`, `opencode-zen`, `openrouter`, `qwen-oauth`, `router`, `stepfun`, `upstage`, `vertex`, `xai`, `xiaomi`, `zai` |
| Observability (1) | `langfuse` |
| 消息平台 (22) | `a2a`, `buzz`, `dingtalk`, `discord`, `email`, `feishu`, `google_chat`, `homeassistant`, `irc`, `line`, `matrix`, `mattermost`, `ntfy`, `photon`, `raft`, `simplex`, `slack`, `sms`, `teams`, `telegram`, `wecom`, `whatsapp` |
| 视频生成 (3) | `deepinfra`, `fal`, `xai` |
| Web搜索与提取 (11) | `brave_free`, `cloakbrowser`, `ddgs`, `exa`, `firecrawl`, `keenable`, `parallel`, `scrapling`, `searxng`, `tavily`, `xai` |

`gateway/platforms/` 下的内置 adapter 另外提供 Signal、BlueBubbles（iMessage）、
Weixin、Yuanbao、WhatsApp Business Cloud API、通用 webhook 以及 OpenAI 兼容 API server。

Git子模块用于可选集成。仅在需要全部功能时运行
`git submodule update --init --recursive`。

| 路径 | 仓库 | 用途 |
| --- | --- | --- |
| `plugins/hermes-bot-mode/desktop` | [Hermes-Bot-Mode](https://github.com/zapabob/Hermes-Bot-Mode.git) | Desktop bot roster UI |
| `plugins/artemis` | [artemis](https://github.com/zapabob/artemis.git) | 基于自然语言指令的 Android 自动化 |
| `vendor/openclaw-mirror/AI-Scientist` | [AI-Scientist](https://github.com/zapabob/AI-Scientist.git) | 科研agent集成 |
| `vendor/openclaw-mirror/ATLAS` | [ATLAS](https://github.com/zapabob/ATLAS.git) | Research agent集成 |
| `vendor/openclaw-mirror/ShinkaEvolve` | [ShinkaEvolve](https://github.com/zapabob/ShinkaEvolve.git) | 进化workflow集成 |
| `vendor/neuro-sdk` | [neuro-sdk](https://github.com/zapabob/neuro-sdk.git) | Neuro集成SDK |
| `vendor/openmanus` | [OpenManus](https://github.com/zapabob/OpenManus.git) | OpenManus runtime |
| `vendor/SillyTavern` | [SillyTavern](https://github.com/zapabob/SillyTavern.git) | 本地角色聊天前端 |
| `vendor/shinka-osint` | [ShinkaEvolve-OSINT](https://github.com/zapabob/ShinkaEvolve-OSINT.git) | OSINT分析runtime（私有仓库，初始化需要访问权限） |
| `vendor/buzz` | [buzz](https://github.com/zapabob/buzz.git) | 语音转写runtime |
| `vendor/officecli` | [OfficeCLI](https://github.com/zapabob/OfficeCLI.git) | Office文档CLI |
| `vendor/akari-video` | [akari-video](https://github.com/zapabob/akari-video.git) | AI视频编辑器 |
| `vendor/cloakbrowser` | [cloakbrowser](https://github.com/zapabob/cloakbrowser.git) | Browser automation runtime |
| `vendor/airi` | [airi](https://github.com/zapabob/airi.git) | Avatar与companion runtime |
| `vendor/oh-my-hermes` | [oh-my-hermes](https://github.com/zapabob/oh-my-hermes.git) | Hermes workflow扩展 |
| `vendor/OpenMausBot` | [OpenMausBot](https://github.com/zapabob/OpenMausBot.git) | Desktop automation bot |
| `vendor/heygen-cli` | [heygen-cli](https://github.com/heygen-com/heygen-cli.git) | HeyGen CLI client |

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
  `/engineer`。
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
| Security | security guidance 与强化的 approval/execution boundary | `tests/plugins/test_security_guidance_plugin.py` |

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
为准；其中的旧版本示例并不能证明 0.21.3 已发布。

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

upstream 是集成输入，而不是下游产品的权威来源。每次 campaign 都会在
`.codex/UPSTREAM_SNAPSHOT.json` 中固定准确 SHA，在 `UPSTREAM_ADOPTION.yaml` 中分类
commit，并在 `CARRY.yaml` 中记录直接保留的修改。`scripts/upstream/snapshot_sync.py`
只接受显式 SHA，绝不会解析持续变化的 latest branch。保留的 release-provenance snapshot 为
`b51c055a12220f8c7c18660e8599365012e19532`。

优先采用官方 public API。security 与 data integrity 修复会和更强、且经过验证的下游特性
组合。不能仅因 upstream 增加了名称相似的功能就移除下游功能；替换必须提供 parity 证据。
请勿用整体的 upstream merge、rebase 或 cherry-pick 代替契约审查。

更新正在运行的工作站前，请保存未 commit 的工作与各个 profile，记录当前 commit，并保留
已部署 Desktop 的回滚副本。Desktop control backend、消息 gateway、llama server、
embedding server 与 Go watchdog 各有独立的 lifecycle；关闭一个窗口并不代表它们全部已
重启。重启后请检查应用窗口、backend 响应与实际模型就绪状态。参见
[本地运行时配置](docs/local-secretary-runtime.md)、
[release policy](docs/windows/RELEASE_POLICY.md) 与 [AGENTS.md](AGENTS.md)。

## 13. 架构

fork 所有的 Python boundary 位于 `downstream/`：`compat/hermes` 委托给官方 contract，
`platform/windows` 负责 native policy，`services` 定义 long-lived service contract，
`features` 验证 product ledger。项目刻意不创建名为 `platform` 的 top-level Python package。

共享的 agent core 位于 CLI、消息 gateway、TUI 与 Electron Desktop 之后。围绕它的有集中式
slash command registry、cron 调度、多 profile kanban board、subagent 委派、skill curator、
Mixture of Agents（`hermes moa`）、MCP client 与 server（`hermes mcp`）、ACP 以及 profile。
core 继续保持为狭窄的公共边界：capability 由 plugin 与 skill 承载，state path 由
profile-aware 的官方 path helper 管理，prompt cache 与 message role invariant 始终是强制要求。

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

## 15. Upstream 项目

原版项目为 [NousResearch/hermes-agent](https://github.com/NousResearch/hermes-agent)。
官方 upstream installer、website、documentation、issue tracker 与 support channel 仅适用于
upstream distribution，它们不会安装或认可本下游仓库。upstream 贡献保留其作者身份与归属。

## 16. 许可证与归属

原版 Hermes Agent 由 Nous Research 开发，并采用 MIT License。本下游版本保留该归属声明、
原版 copyright 与 contributor history，以及 [MIT License](LICENSE)。下游工作独立维护；
upstream 与 downstream 的 issue、release 和产品声明必须清楚区分。
