# Hermes Agent Windows Workstation Edition

<p align="center">
  <a href="README.md" lang="en-GB">King's English</a> ·
  <a href="README.ja.md" lang="ja">日本語</a> ·
  <a href="README.zh-CN.md" lang="zh-CN"><strong>简体中文</strong></a>
</p>

> [!NOTE]
> 英文版 `README.md` 是规范正本。本简体中文版遵循相同的产品边界与安装契约。

**[Hermes Agent](https://github.com/NousResearch/hermes-agent) 的非官方 Windows 原生下游**，
面向把 Hermes 当作常驻工作站来运行的人：Electron Desktop、CLI、消息 Gateway、profile、
本地推理、语义记忆、自动化与可选的边缘集成——**同一源码树、同一 core**。

维护仓库：
[zapabob/hermes-agent-windows](https://github.com/zapabob/hermes-agent-windows)。  
与 Nous Research 无隶属或背书关系。保留 upstream 归属与 [MIT License](LICENSE)。

[![Windows Workstation Tier-1 CI](https://github.com/zapabob/hermes-agent-windows/actions/workflows/fork-cicd.yml/badge.svg)](https://github.com/zapabob/hermes-agent-windows/actions/workflows/fork-cicd.yml)

**源码版本：0.23.0**（`2026.10.28`）· channel：`stable` / `preview`

---

## 一眼看懂范围

| 你得到 | 你不破坏 |
| --- | --- |
| 将 Windows 11 x64 作为 Tier-1 运行目标 | 官方 Hermes CLI / session / profile / tool / MCP 契约 |
| Electron Desktop（破坏性 backend owner 唯一） | upstream 的 MIT 历史与贡献者署名 |
| 与远程 provider 并列的本地 llama.cpp/GGUF | 基于证据的 upstream 采纳（精确 SHA，禁止盲目 merge） |
| Semantic Graph + Ebbinghaus 记忆接缝 | config / secret / session / gateway 的 profile 隔离 |
| Gateway、cron、skills、MCP、delegation、kanban | prompt cache 稳定与角色交替不变量 |

`0.23.0` 是 **下游产品版本号**，并不表示已对之后所有 upstream commit 完成语义等价审查。
未完成的 semantic-refresh family 在 source、测试、mutation、CodeGraph、review 证据齐备前
保持开放。详见 [版本与 provenance](#版本与-provenance)。

---

## 快速开始（源码路径）

**要求：** Windows 11 x64 · PowerShell · Git · [`uv`](https://docs.astral.sh/uv/) · Python 3.11–3.13  
仅在从源码构建 Desktop 时需要 Node.js。

```powershell
git clone https://github.com/zapabob/hermes-agent-windows.git
Set-Location hermes-agent-windows
uv sync --locked --all-extras
uv run hermes setup
uv run hermes chat
```

同一 checkout 启动 Desktop：

```powershell
uv run hermes desktop
```

installer / portable ZIP：先在
[Releases](https://github.com/zapabob/hermes-agent-windows/releases)
确认资产存在，校验 `SHA256SUMS.txt`，再按
[docs/windows/INSTALL.md](docs/windows/INSTALL.md) 操作。

> 首次 `uv sync` 与原生构建耗时会超过命令列表的阅读时间。  
> 向 `main` 的 push **不是** stable installer 已发布的证据。

工作站重启仅限 Documents 下的 checkout——**切勿从 `.worktrees/` 启动**：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts\windows\Restart-HermesFullStack.ps1
```

---

## 表面（Surfaces）

同一 `AIAgent` core 之上有四类操作面：

| 表面 | 作用 |
| --- | --- |
| **CLI** | 交互聊天、setup、tools、skills、update、doctor |
| **Electron Desktop** | 原生 UI、profile、Security Center、Bot Mode、Git/review |
| **Gateway** | Telegram / Discord / Slack / LINE / Signal 等长驻消息 |
| **TUI** | 基于 stdio JSON-RPC 的 Ink 终端 UI |

能力在 **边缘**（plug-in / skill / MCP / 服务门控工具）扩展，  
避免把 core 工具集无限制地塞进每一次 API 调用。

---

## 0.23.0 新内容

Windows-native feature intake —
[`docs/windows/feature-intake-20261028/`](docs/windows/feature-intake-20261028/)：

| 领域 | 行为 |
| --- | --- |
| 子 agent 设置 | Desktop Settings 专页；一次 Apply 在服务端 validate→merge 后保存完整 `delegation` 草案 |
| Plugin OAuth | 清单 `oauth:` + `hermes auth …`；由 host 附加 Bearer——插件永不直接拿到 token |
| `ask_choice` | `PluginContext.ask_choice` 绑定各表面的 clarify；未绑定/headless 返回 `None` |
| Vault keychain | 可选 `vault.key_storage: keychain`；默认仍为 `file` |
| `ctx.files` | Desktop grant API（仅选择器根目录、不透明句柄、Windows 路径加固） |
| MCP / 更新 / 压缩 | 调用级 progress、共用插件更新核心、耐久 `post_compaction` |

### 本地模型稳定性（128K llama-server）

大本地上下文曾因 KV 溢出显存导致自动压缩以 `context_compression_timeout` 失败。本树：

- 用 `scripts/windows/Get-LlamaContextBudget.ps1` 将上下文钳制在可常驻显存的预算内；
- 以 **token**（而非字符）限制摘要输入，对 CJK 安全；
- 放宽本地 no-progress / total ceiling；
- 支持延迟工具 schema 以缩小请求基线；
- 压缩超时可重试，不丢弃用户回合。

参考 27B 路径实测：prefill 从约 11 tok/s 回到约 550–1,000 tok/s，自动压缩再次完成。

---

## 为何存在这个 fork

- **把 Windows 当作一级运行时** — path、进程身份、PowerShell、NTFS、Electron IPC、
  更新交接、installer/portable、Go watchdog 具备原生 Windows 测试。Linux 交叉编译
  不能当作 Windows 证据。
- **Desktop backend 的破坏性 owner 只有 Electron main** — 观察到 PID / 端口 / token
  并不授予第二所有者权限。
- **本地推理不分裂 provider 模型** — 同一选择器覆盖远程、OAuth 与 llama.cpp/GGUF。
  生成与 embedding 是分离的服务与就绪证据。
- **官方接缝上的记忆** — Semantic Graph 与 Ebbinghaus 通过 Hermes memory-provider
  契约组合。
- **Bot Mode 按名称解析** — 一个 bot = `(profile, 标题恰好为 "Bot Chat")`。
  不持久化 canonical session-id 指针。
- **长驻自动化** — Gateway / cron / skills / MCP / delegation / kanban 共享同一
  session/profile 模型。
- **边缘集成** — VRChat/Unity、语音、AITuber、OSINT 等作为 plug-in / 可选组件。
- **Security Center** — 确定性扫描、证据、隔离区；变更需明确确认。
- **证据驱动的 upstream 吸收** — 精确冻结 SHA 与可观测契约。版本号本身不是兼容性证明。

产品台账：[`FEATURES.yaml`](FEATURES.yaml) · 携带补丁：[`CARRY.yaml`](CARRY.yaml) ·
采纳：`UPSTREAM_ADOPTION.yaml` · 策略：[`DOWNSTREAM_POLICY.md`](DOWNSTREAM_POLICY.md)

---

## 架构速览

```text
┌─────────────┐  ┌──────────────┐  ┌──────────┐  ┌─────────┐
│ CLI / setup │  │ Electron UI  │  │ Gateway  │  │   TUI   │
└──────┬──────┘  └──────┬───────┘  └────┬─────┘  └────┬────┘
       └────────────────┴───────────────┴─────────────┘
                              ▼
                        AIAgent core
           (prompt cache · tools · memory · providers)
                              │
            ┌─────────────────┼──────────────────┐
            ▼                 ▼                  ▼
      plugins/skills   MCP / cron / kanban   local llama / embeddings
```

不可轻易破坏的不变量：

1. **按会话的 prompt cache** — 中途改写历史或切换 toolset 会摧毁 KV cache、拉高 API 成本。
2. **细腰、能力在边缘** — 新能力优先 CLI/skill → 服务门控工具 → plug-in → MCP。
3. **表面能力按会话作用域解析** — Desktop 功能来自 `session.platform`，而非静态环境变量。
4. **确定且可逆的执行** — 破坏性操作需要恢复路径、可审计性与批准。

规范契约：
[`.codex/WINDOWS_PLATFORM_CONTRACT.md`](.codex/WINDOWS_PLATFORM_CONTRACT.md)

---

## 所有权与恢复

| 组件 | lifecycle owner |
| --- | --- |
| Desktop `serve` backend | 仅 Electron main |
| 生成用 llama-server | 运维 / launcher |
| embedding llama-server（由 watchdog 拉起时） | Go watchdog |
| 消息 Gateway | Gateway 自身（设计上在 Desktop 退出后仍存活） |
| WebUI / 固定端口 dashboard | 与 Desktop 的 `serve --port 0` 分离 |

Go watchdog 负责观测，以及管理**它自己启动**的 embedding。不得成为 Desktop backend
的并行所有者。精确进程身份优先于 argv 子串猜测。

指南：[`scripts/windows/watchdog-go/README.md`](scripts/windows/watchdog-go/README.md)

---

## 插件与子模块

```powershell
uv run hermes plugins
```

代表性家族（数量会变；是否启用取决于 profile 与凭据）：

| 领域 | 示例 |
| --- | --- |
| Desktop / ops | `hermes-bot-mode`, `desktop-dashboard`, `implementation_router` |
| Memory | `semantic_graph`, `memory/ebbinghaus`, `surfsense` |
| Media / XR | `voicevox_tts`, `vrchat-autonomy`, `unity_vrchat_bridge`, `aituber_onair` |
| Research | `shinka-osint`, `world-intel-osint` |
| Providers | `openai-codex`, `qwen-oauth`, `xai`, `hypura` |

`implementation_router` 为 **opt-in**：隔离的 planner→worker→verify→reviewer 流程。
不替代普通选择器、delegation、MoA 或 fallback，也不会自动 apply / 发布。

仅在需要对应外部 runtime 时初始化子模块：

```powershell
git submodule update --init --recursive
```

清单快照：[`docs/windows/INTEGRATIONS.md`](docs/windows/INTEGRATIONS.md)

---

## 安装与 Desktop 构建

```powershell
git clone https://github.com/zapabob/hermes-agent-windows.git
Set-Location hermes-agent-windows
uv sync --locked --all-extras
uv run hermes --version
uv run hermes setup
```

从源码构建 Desktop（Node 版本见
[`apps/desktop/package.json`](apps/desktop/package.json)）：

```powershell
npm ci
npm run typecheck --workspace apps/desktop
npm run build --workspace apps/desktop
```

打包 / 替换正在运行的 `Hermes.exe` 是另一项、需感知所有权的操作。交换二进制前先停止
被拥有的进程。

密钥写入 profile 的 `.env`（或外部 vault）；非密钥设置写入 `config.yaml`。  
切勿提交模型权重、profile 数据库或 token。

---

## 版本与 provenance

| 事实 | 值 |
| --- | --- |
| 下游产品版本 | `0.23.0`（`version_source: downstream`） |
| Upstream stable 参照 (R2) | `f97608f178d1ffeca59860195ab7da295f7c8e5f`（`0.21.5` / `v2026.9.24`） |
| 当前 semantic-refresh ceiling (U1) | `678a4762b887f3eabe5cad11254b2ab1ae859485` |
| 历史 provenance snapshot | `b51c055a12220f8c7c18660e8599365012e19532` |

交接计划：
[`docs/windows/semantic-refresh-20260926/CURSOR_IMPLEMENTATION_PLAN_20260929.md`](docs/windows/semantic-refresh-20260926/CURSOR_IMPLEMENTATION_PLAN_20260929.md)

更新流水线：
`plan → snapshot → apply → restart-per-kind → verify → report`

---

## 安全

- 勿提交密钥、个人 runtime 数据、模型文件或调查产物。
- Security Center 的变更 API 需要明确确认。
- `hermes security` / `hermes egress` / `hermes secrets` 覆盖扫描、出口策略与外部保险库。
- provider base URL 在写入日志前会掩码；子进程只接收有界环境变量。

**Control MCP：** 已有 auth / journal / coordinator 契约，但 **生产写入仍为 DISABLED**。
在 host grant-revocation、线性化、可信生产者绑定与 writer fence 全部关闭前不得启用。
仅凭测试通过不能授权该写入路径。见
[`docs/control-mcp/IMPLEMENTATION_LOG.md`](docs/control-mcp/IMPLEMENTATION_LOG.md)。

---

## 文档导航

| 文档 | 用途 |
| --- | --- |
| [`docs/windows/INSTALL.md`](docs/windows/INSTALL.md) | Windows 安装正本 |
| [`docs/windows/INTEGRATIONS.md`](docs/windows/INTEGRATIONS.md) | 可选集成快照 |
| [`docs/windows/SECURITY_CENTER.md`](docs/windows/SECURITY_CENTER.md) | Security Center |
| [`docs/windows/feature-intake-20261028/`](docs/windows/feature-intake-20261028/) | 0.23.0 intake |
| [`AGENTS.md`](AGENTS.md) | 面向开发者与助手的工程契约 |
| [`SECURITY.md`](SECURITY.md) | 安全策略 |

---

## Upstream 项目

原项目：[NousResearch/hermes-agent](https://github.com/NousResearch/hermes-agent)。  
upstream 文档、安装程序、发行与支持仅适用于 **upstream 发行版**，并不安装或背书本下游。

---

## 许可与归属

Hermes Agent 由 Nous Research 在 MIT License 下开发。本下游保留其归属、版权与贡献者
历史，并以相同的 [MIT License](LICENSE) 提供。

Windows / 工作站相关变更由本仓库独立维护。upstream 与 downstream 的 issue、发行、
支持声明与资格证据保持分离。
