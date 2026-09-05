# Hermes Agent Windows Workstation Edition

<p align="center">
  <a href="README.md" lang="en-GB">King's English</a> ·
  <a href="README.ja.md" lang="ja">日本語</a> ·
  <a href="README.zh-CN.md" lang="zh-CN"><strong>简体中文</strong></a>
</p>

> [!NOTE]
> 英文版 `README.md` 是规范正本。本简体中文版以英文版为准并随其更新。

面向 Windows 11 AI 工作站的 Hermes Agent 非官方 Windows 原生版。

这个 fork 由一名维护者独立维护，不隶属于 Nous Research，也未获得其认可。
原版 Hermes Agent 由 Nous Research 开发，并采用 MIT License。

[![Windows Workstation Tier-1 CI](https://github.com/zapabob/hermes-agent-windows/actions/workflows/fork-cicd.yml/badge.svg)](https://github.com/zapabob/hermes-agent-windows/actions/workflows/fork-cicd.yml)

## 30 秒看懂安装

> **TL;DR：**依次运行下面五条命令。模型提供商可在向导中设置；核心CLI无需安装
> 可选插件或初始化Git子模块。

当前可立即使用的是源码安装。请准备 Windows 11 x64、PowerShell、Git、`uv` 和
Python 3.11-3.13。只有构建 Desktop 时才需要 Node.js。

```powershell
git clone https://github.com/zapabob/hermes-agent-windows.git
Set-Location hermes-agent-windows
uv sync --locked --all-extras
uv run hermes setup
uv run hermes chat
```

这是可在30秒内看完的命令路径；首次下载依赖和编译可能需要更长时间。

设置向导会配置模型提供商，最后一条命令会打开 CLI chat。要从同一 checkout 启动
Desktop，请运行：

```powershell
uv run hermes desktop
```

如果需要 installer 或 portable ZIP，请先确认
[下游 Releases](https://github.com/zapabob/hermes-agent-windows/releases)
已经发布对应 asset，并用 `SHA256SUMS.txt` 校验。完整步骤见
[Windows 安装指南](docs/windows/INSTALL.md)。

## 这个 fork 增加了什么

- Python、Electron、Go、upstream API 兼容、regression 与 security lock 的 Windows Tier-1 CI
- 覆盖非管理员与含空格 path 的 installer、portable、旧版 upgrade E2E
- 固定 upstream snapshot `b51c055a12220f8c7c18660e8599365012e19532`，不使用移动基线
- 通过官方 provider/memory seam 连接 local llama.cpp/GGUF 与 embedding lifecycle
- 由外部 Go watchdog 对 Desktop/backend 及可选 embedding 执行有限恢复
- consumer NVIDIA workstation 实机证据与无 GPU 的 hosted CI 分开记录

release candidate 为 `0.21.0`。版本号跟随 Hermes 上游，下游修订使用 commit SHA
而不是独立 suffix 识别。支持 `stable` 与 `preview` channel。通过验证的产物只从
与上游同格式的对应 tag 发布到
[下游 Releases](https://github.com/zapabob/hermes-agent-windows/releases)。
在首个 stable asset 实际存在前，请使用上面的 source route。
另见 [release policy](docs/windows/RELEASE_POLICY.md) 与
[官方 upstream](https://github.com/NousResearch/hermes-agent)。

## 插件与Git子模块

Hermes通过 `plugin.yaml`、`__init__.py` 和 `register(ctx)` 发现标准目录插件。
下面按用途列出51个随附的标准根插件；`lmcache` 以具有独立注册路径的旧式manifest
提供。运行 `uv run hermes plugins` 可查看当前profile实际启用的插件。

| 领域 | 随附根插件 |
| --- | --- |
| Agent与运维 | `ai-employee-org`, `ai-partner-os`, `airi`, `aituber-onair`, `aituber-kit`, `book-to-skill`, `desktop-dashboard`, `disk-cleanup`, `freebuff`, `freellmapi`, `google-colab`, `google_meet`, `hermes-gpt`, `hermes-bot-mode`, `line-ai-bot`, `lm-twitterer`, `memory-llm-wiki`, `notebooklm`, `oh-my-hermes`, `openclaw-vendor`, `openmanus`, `plugin-doctor`, `research-desk`, `scrapling-feeds`, `teams_pipeline`, `warashibe-reselling` |
| 媒体、语音与XR | `akari-video`, `buzz`, `fish-audio-tts`, `hakua-tts-bridge`, `heygen`, `hyperframes`, `irodori-tts`, `questframe-fh6vr`, `sillytavern`, `spotify`, `unity-cli`, `unity-vrchat-bridge`, `unsloth-studio`, `voicebox`, `voicevox-tts`, `vrchat-autonomy` |
| 知识、安全与OSINT | `osint-agent`, `security-guidance`, `semantic-graph`, `shinka-osint`, `sitdeck-osint`, `surfsense`, `tookie-osint`, `world-intel-osint`, `worldmonitor-osint` |
| 旧式manifest | `lmcache` |

仓库中共有154个插件manifest。专用provider系列由各自的发现器处理，因此只有已配置的
能力会进入session。

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

Git子模块用于可选集成。仅在需要全部功能时运行
`git submodule update --init --recursive`。

| 路径 | 仓库 | 用途 |
| --- | --- | --- |
| `plugins/hermes-bot-mode/desktop` | [Hermes-Bot-Mode](https://github.com/zapabob/Hermes-Bot-Mode.git) | Desktop bot roster UI |
| `vendor/openclaw-mirror/AI-Scientist` | [AI-Scientist](https://github.com/zapabob/AI-Scientist.git) | 科研agent集成 |
| `vendor/openclaw-mirror/ATLAS` | [ATLAS](https://github.com/zapabob/ATLAS.git) | Research agent集成 |
| `vendor/openclaw-mirror/ShinkaEvolve` | [ShinkaEvolve](https://github.com/zapabob/ShinkaEvolve.git) | 进化workflow集成 |
| `vendor/neuro-sdk` | [neuro-sdk](https://github.com/zapabob/neuro-sdk.git) | Neuro集成SDK |
| `vendor/openmanus` | [OpenManus](https://github.com/zapabob/OpenManus.git) | OpenManus runtime |
| `vendor/SillyTavern` | [SillyTavern](https://github.com/zapabob/SillyTavern.git) | 本地角色聊天前端 |
| `vendor/shinka-osint` | [ShinkaEvolve-OSINT](https://github.com/zapabob/ShinkaEvolve-OSINT.git) | OSINT分析runtime |
| `vendor/buzz` | [buzz](https://github.com/zapabob/buzz.git) | 语音转写runtime |
| `vendor/officecli` | [OfficeCLI](https://github.com/zapabob/OfficeCLI.git) | Office文档CLI |
| `vendor/akari-video` | [akari-video](https://github.com/zapabob/akari-video.git) | AI视频编辑器 |
| `vendor/cloakbrowser` | [cloakbrowser](https://github.com/zapabob/cloakbrowser.git) | Browser automation runtime |
| `vendor/airi` | [airi](https://github.com/zapabob/airi.git) | Avatar与companion runtime |
| `vendor/oh-my-hermes` | [oh-my-hermes](https://github.com/zapabob/oh-my-hermes.git) | Hermes workflow扩展 |
| `vendor/OpenMausBot` | [OpenMausBot](https://github.com/zapabob/OpenMausBot.git) | Desktop automation bot |
| `vendor/heygen-cli` | [heygen-cli](https://github.com/heygen-com/heygen-cli.git) | HeyGen CLI client |

## 1. 产品定位

Hermes Agent Windows Workstation Edition 是面向持久运行的本地 AI 工作站、功能完整的
Windows 优先下游发行版。它保留 Hermes CLI 命令、公开契约、插件模型和 upstream 历史，
同时为 Windows 原生运行、本地模型、记忆、语音、VR/Unity 与恢复机制维护明确的下游策略。

产品功能台账位于 [FEATURES.yaml](FEATURES.yaml)。保留在 upstream 所有文件中的直接补丁，
由 [CARRY.yaml](CARRY.yaml) 单独追踪。

## 2. Windows 优先目标

主要目标平台是配备原生 Python、原生 Node/Electron、交互式桌面和消费级 NVIDIA GPU 的
Windows 11 x64。设计支持本地 LLM 与 embedding 服务、语音服务、VRChat/Unity 集成及
远程管理的持续运行。

无论 upstream 如何安排平台优先级，Windows 都是独立的 Tier-1 目标。原生行为在
`windows-latest` 上测试；Linux 交叉编译不能作为 Windows 运行时证据。

## 3. 适用人群

本发行版面向维护 Windows AI 工作站，并需要从源码层面控制本地推理、长期运行服务、记忆、
桌面行为与恢复机制的运维人员和开发者。使用者应熟悉 PowerShell、Git、Python 环境、
Node 工具以及 CI 结果的阅读。

如果需要最简洁的 Hermes 官方安装方式和 upstream 支持模式，请使用第 15 节链接的原版项目。

## 4. 下游优势

本下游版增加了 Windows 原生运行与恢复契约、外部 Go watchdog、本地 llama.cpp/GGUF 与
embedding 生命周期、本地秘书及 provider 集成、semantic memory 与 cognitive memory
扩展、VRChat/Unity 和本地语音路由、OSINT/Shinka 扩展、Desktop Git/review 界面，
以及额外的 security 与 provider fallback 覆盖。

这些能力通过官方 Hermes API 组合运行。本 fork 不会为 session、approval、profile、
gateway、model catalogue 或 tool registry 建立并行的权威来源。

## 5. 已验证功能矩阵

| 领域 | 已验证实现 | 契约证据 |
| --- | --- | --- |
| Windows runtime | 原生 path、process、IPC、NTFS handoff、terminal、credential、power 与 GPU helper | `tests/downstream/test_windows_contracts.py` |
| Recovery | 外部 Go watchdog 与由 watchdog 管理的 Desktop backend | `scripts/windows/watchdog-go/*_test.go` |
| Local inference | llama.cpp/GGUF fallback 与 hot-swap script | `tests/hermes_cli/test_llama_fallback_runtime.py` |
| Local embeddings | watchdog embedding lifecycle 与 semantic graph backend | `scripts/windows/watchdog-go/embedding_test.go` |
| Local secretary | 基于官方 agent boundary 的 read/write action 分离 | `tests/downstream/test_upstream_api_contracts.py` |
| Providers | Hypura/local provider 集成与 provider rotation/fallback | `tests/fork/test_hypura_oai_proxy.py` |
| Memory | Semantic Graph hybrid retrieval 与 Ebbinghaus cognitive extension | `tests/plugins/test_semantic_graph_registration.py` |
| VR and Unity | VRChat autonomy tooling 与 Unity bridge | `tests/plugins/test_vrchat_autonomy_plugin.py` |
| Voice | Irodori、VOICEVOX 与 local TTS route | `tests/plugins/test_irodori_tts_plugin.py` |
| AITuber | AITuber OnAir 与 AITuber Kit plugin | `tests/plugins/test_aituber_onair_plugin.py` |
| OSINT/Shinka | Shinka、SitDeck、WorldMonitor 与 OSINT plugin surface | `tests/plugins/test_shinka_osint_plugin.py` |
| Desktop | 通过官方 Desktop IPC 与 pane contract 扩展 Git/review | `apps/desktop/electron/git-review-ops.test.ts` |
| Security | security guidance 与强化的 approval/execution boundary | `tests/plugins/test_security_guidance_plugin.py` |

每项功能的所有者、公开 surface、upstream 重叠范围、Windows 要求、测试和集成策略，
均记录在 `FEATURES.yaml` 中。

## 6. Windows Tier-1 支持契约

Tier-1 覆盖原生 drive path、MSYS `/c/...` 与受支持的 WSL `/mnt/c/...` alias、NTFS lock、
已锁定 executable 与 extension module 的 update、process tree、适用的 Job Object 行为、
PowerShell quoting、Git Bash boundary、CP932/UTF-8 boundary、CRLF、venv `Scripts\\`，
以及 Electron stdio pipe。

运行时资格验证覆盖 sleep/resume、network 与 loopback provider 恢复、Desktop relaunch、
updater handoff、watchdog 恢复、llama restart 与 hot-swap、embedding restart，
以及 profile/session persistence。规范契约见
[.codex/WINDOWS_PLATFORM_CONTRACT.md](.codex/WINDOWS_PLATFORM_CONTRACT.md)。

## 7. 本地 AI 架构

官方 Hermes provider 与 model catalogue 契约仍是权威来源。下游本地运行时通过这些契约接入：
llama.cpp/GGUF 使用 local fallback runtime，Hypura 使用 provider plugin seam，
local embedding 使用 Semantic Graph backend 与 watchdog 管理的 loopback service。

运维脚本保留在 `scripts/windows/` 下。运行时 plugin entrypoint 保留在 `plugins/` 下，
使官方 discovery 能够继续工作。

## 8. Watchdog 与恢复架构

`scripts/windows/watchdog-go` 是唯一的外层自动重启权威。它可以监控 packaged Desktop、
发布 prewarmed backend manifest，并协调已配置的 local embedding process。Desktop、
backend、llama 与 embedding component 可以公开 health 或请求恢复，但不会形成各自独立的
自动重启 loop。

下游 Python service module 是无副作用的契约。实际的 operator startup 与 deployment
仍由 `scripts/windows/` 下的 PowerShell 和 Go surface 负责。
## 9. 记忆与 semantic retrieval

Semantic Graph plugin 通过官方 plugin 与 memory interface 提供 graph storage、
hybrid retrieval、embedding、fusion、abstention 和 cognitive helper。Ebbinghaus provider
增加 experience 与 retention policy，并可连接 Semantic Graph。两者均保留独立的
plugin entrypoint 与针对性的 test suite。

## 10. VRChat、Unity 与语音集成

VRChat autonomy tool、observation/relay helper、Unity bridge package、VOICEVOX、
Irodori 及其他 local TTS route 都是下游所有的功能。它们使用官方 plugin、tool 与
TTS contract，而不会把 core 改造成 VR 或 voice 专用 runtime。

外部发布与写入 action 仍须明确 approval。本地生成不代表获得向外部 account 发布内容或
修改其状态的授权。

## 11. 安装

Windows release workflow 会生成用户级 NSIS installer 与 portable ZIP，并在 stable
tag 发布前执行 clean install、启动与 upgrade E2E。只从
[下游 Releases](https://github.com/zapabob/hermes-agent-windows/releases)
获取已发布产物，并核对 `SHA256SUMS.txt`。除非 `release-manifest.json` 另有记录，
当前 candidate 按 unsigned 处理。完整步骤见
[docs/windows/INSTALL.md](docs/windows/INSTALL.md)。

source/development route 仍可在 PowerShell 中使用：

```powershell
git clone https://github.com/zapabob/hermes-agent-windows.git
Set-Location hermes-agent-windows
uv sync --locked --all-extras
uv run hermes --version
uv run hermes setup
```

Desktop 开发与 source build：

```powershell
npm ci
npm --workspace apps/desktop run typecheck
npm --workspace apps/desktop run build
```

启用任何全天候 service 或 Scheduled Task 前，请先检查配置。API key 与 token 应存放在
profile-scoped Hermes secret store 中，或按照 Hermes 文档保存到 `.env`；非 secret 设置
应放入 `config.yaml`。

## 12. 更新与 upstream 集成策略

upstream 是集成输入，而不是下游产品的权威来源。每次 campaign 都会在
`.codex/UPSTREAM_SNAPSHOT.json` 中固定准确 SHA，在 `UPSTREAM_ADOPTION.yaml` 中分类
commit，并在 `CARRY.yaml` 中记录直接保留的修改。`scripts/upstream/snapshot_sync.py`
只接受显式 SHA，绝不会解析持续变化的 latest branch。

优先采用官方 public API。security 与 data integrity 修复会和更强、且经过验证的下游特性
组合。不能仅因 upstream 增加了名称相似的功能就移除下游功能；替换必须提供 parity 证据。

## 13. 架构

fork 所有的 Python boundary 位于 `downstream/`：`compat/hermes` 委托给官方 contract，
`platform/windows` 负责 native policy，`services` 定义 long-lived service contract，
`features` 验证 product ledger。项目刻意不创建名为 `platform` 的 top-level Python package。

Hermes core 继续保持为狭窄的公共边界。capability 由 plugin 与 skill 承载，state path 由
profile-aware 的官方 path helper 管理，prompt cache 与 message role invariant 始终是
强制要求。

## 14. 安全

请勿 commit secret、个人 runtime data、profile database、model file、local artifact 或
生成的 credential。write、publish、destructive 与 shell action 必须置于明确 approval
之后。child service environment 只应传递必要 variable，不应继承 ambient credential。

security gate 会检查锁定的 Python graph、Python advisory、production npm advisory、
Go module integrity、OSV result、supply-chain policy，以及本仓库的 security regression
test。green 的 local unit test 不能代替 exact-head CI 或 live runtime evidence。

## 15. Upstream 项目

原版 Hermes Agent 由 Nous Research 维护：
[NousResearch/hermes-agent](https://github.com/NousResearch/hermes-agent)。

官方 upstream installer、website、documentation、issue tracker 与 support channel 仅适用于
upstream distribution。它们不会安装或认可本下游仓库。

## 16. 许可证与归属

本下游版本继续采用仓库中的 MIT License。原版 Hermes Agent 的 copyright 与 contributor
history 均予保留。下游工作由 fork contributor 独立维护；upstream 与 downstream 的
issue、release 和产品声明必须清楚区分。
