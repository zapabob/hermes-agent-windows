# Hermes Agent Windows Workstation Edition

<p align="center">
  <a href="README.md" lang="en-GB">King's English</a> ·
  <a href="README.ja.md" lang="ja"><strong>日本語</strong></a> ·
  <a href="README.zh-CN.md" lang="zh-CN">简体中文</a>
</p>

> [!NOTE]
> 英語版の `README.md` が正本です。この日本語版は同じ製品境界と導入契約に追随します。

**[Hermes Agent](https://github.com/NousResearch/hermes-agent) の非公式 Windows ネイティブ派生**です。  
常時稼働のワークステーションとして Hermes を運用する人向けに、Electron Desktop・CLI・
メッセージング Gateway・profile・ローカル推論・semantic memory・自動化・任意の edge 連携を
**ひとつのソースツリー・ひとつの core** で扱います。

保守先は
[zapabob/hermes-agent-windows](https://github.com/zapabob/hermes-agent-windows)。  
Nous Research との提携・承認はありません。upstream の帰属と [MIT License](LICENSE) は保持します。

[![Windows Workstation Tier-1 CI](https://github.com/zapabob/hermes-agent-windows/actions/workflows/fork-cicd.yml/badge.svg)](https://github.com/zapabob/hermes-agent-windows/actions/workflows/fork-cicd.yml)

**ソース版: 0.23.0**（`2026.10.28`）· channel: `stable` / `preview`

---

## ひと目でわかる範囲

| 得られるもの | 崩さないもの |
| --- | --- |
| Windows 11 x64 を Tier-1 実行対象として扱う | 公式 Hermes の CLI / session / profile / tool / MCP 契約 |
| Electron Desktop（backend の破壊的 owner は単一） | upstream の MIT 履歴と貢献者クレジット |
| リモート provider と並ぶローカル llama.cpp/GGUF | 証拠ベースの upstream 採用（exact SHA。盲目 merge はしない） |
| Semantic Graph + Ebbinghaus の memory seam | config / secret / session / gateway の profile 隔離 |
| Gateway・cron・skills・MCP・delegation・kanban | prompt cache 安定性と role 交互の invariant |

`0.23.0` は **downstream の製品版番号** です。後続の upstream commit すべてとの意味論的
同等を一括宣言するものではありません。未完の semantic-refresh family は source・test・
mutation・CodeGraph・review が閉じるまで未完のままです。詳細は
[版と provenance](#版と-provenance)。

---

## すぐ始める（ソース経路）

**前提:** Windows 11 x64 · PowerShell · Git · [`uv`](https://docs.astral.sh/uv/) · Python 3.11–3.13  
Node.js は Desktop をソースからビルドするときだけ必要です。

```powershell
git clone https://github.com/zapabob/hermes-agent-windows.git
Set-Location hermes-agent-windows
uv sync --locked --all-extras
uv run hermes setup
uv run hermes chat
```

同じ checkout から Desktop:

```powershell
uv run hermes desktop
```

installer / portable ZIP は
[Releases](https://github.com/zapabob/hermes-agent-windows/releases)
で asset の有無を確認し、`SHA256SUMS.txt` を検証したうえで
[docs/windows/INSTALL.md](docs/windows/INSTALL.md) に従ってください。

> 初回の `uv sync` とネイティブビルドはコマンド一覧より時間がかかります。  
> `main` への push は **stable installer 公開の証拠ではありません**。

ワークステーション再起動は Documents 配下の checkout のみ — **`.worktrees/` からは起動しない**:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts\windows\Restart-HermesFullStack.ps1
```

---

## 表面（Surfaces）

ひとつの `AIAgent` core の上に四つの操作面があります。

| 表面 | 役割 |
| --- | --- |
| **CLI** | 対話チャット、setup、tools、skills、update、doctor |
| **Electron Desktop** | ネイティブ UI、profile、Security Center、Bot Mode、Git/review |
| **Gateway** | Telegram / Discord / Slack / LINE / Signal など長時間メッセージング |
| **TUI** | stdio JSON-RPC 上の Ink 端末 UI |

能力は **edge**（plug-in / skill / MCP / service-gated tool）で増やします。  
core のツールを毎 API 呼び出しに載せ続ける成長は避けます。

---

## 0.23.0 の新機能

Windows-native feature intake —
[`docs/windows/feature-intake-20261028/`](docs/windows/feature-intake-20261028/):

| 領域 | 振る舞い |
| --- | --- |
| 子 agent 設定 | Desktop Settings 専用ページ。Apply 一回で `delegation` 草案を validate→merge 後に保存 |
| Plugin OAuth | マニフェスト `oauth:` + `hermes auth …`。Bearer は host が付与 — plugin は token を受け取らない |
| `ask_choice` | `PluginContext.ask_choice` が各表面の clarify に結線。未結線/headless は `None` |
| Vault keychain | 任意の `vault.key_storage: keychain`。既定は `file` |
| `ctx.files` | Desktop grant API（picker 限定 root、opaque handle、Windows path 硬化） |
| MCP / 更新 / 圧縮 | 呼び出し単位の progress、plugin 更新共通化、耐久 `post_compaction` |

### ローカルモデル安定化（128K llama-server）

大きなローカル context で KV が VRAM を溢れ、オートコンパクションが
`context_compression_timeout` になる問題に対し、本ツリーは次を入れています。

- `scripts/windows/Get-LlamaContextBudget.ps1` で VRAM resident 予算にクランプ
- 要約入力を **token** 上限に（文字数制限ではない。CJK 安全）
- ローカル向け no-progress / total ceiling の拡大
- deferred tool schema によるリクエスト縮小
- 圧縮 timeout でもユーザー turn を落とさず再試行可能

参照 27B 経路での実測: prefill が約 11 tok/s から約 550–1,000 tok/s に戻り、
オートコンパクションが再び完了します。

---

## この fork が存在する理由

- **Windows を第一級ランタイムに** — path、process identity、PowerShell、NTFS、Electron
  IPC、update、installer/portable、Go watchdog をネイティブ試験。Linux 交差コンパイルは
  Windows 証拠にしない。
- **Desktop backend の破壊的 owner は Electron main のみ** — PID / port / token の観測は
  第二所有者の権限にならない。
- **provider モデルを分岐させないローカル推論** — 同じ picker でリモート / OAuth /
  llama.cpp/GGUF。生成と embedding は別 lifecycle・別 readiness。
- **公式 seam 上の memory** — Semantic Graph と Ebbinghaus を Hermes memory-provider
  契約で合成。
- **Bot Mode は名前で解決** — 1 bot = `(profile, タイトルが正確に "Bot Chat")`。
  canonical session-id pin は持たない。
- **長時間自動化** — Gateway / cron / skills / MCP / delegation / kanban が同じ
  session/profile モデルを共有。
- **edge 連携** — VRChat/Unity、音声、AITuber、OSINT などは plug-in / optional。
- **Security Center** — 決定論的 scan・evidence・quarantine。mutation は明示確認。
- **証拠駆動の upstream 取り込み** — exact SHA と観測可能契約。版番号だけでは互換証明にしない。

台帳: [`FEATURES.yaml`](FEATURES.yaml) · 持ち越し: [`CARRY.yaml`](CARRY.yaml) ·
採用: `UPSTREAM_ADOPTION.yaml` · 方針: [`DOWNSTREAM_POLICY.md`](DOWNSTREAM_POLICY.md)

---

## アーキテクチャ要約

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

崩してはいけない invariant:

1. **会話単位の prompt cache** — 途中で過去文脈や toolset を入れ替えると KV cache が壊れ、
   API コストが跳ねる。
2. **細い腰・能力は edge** — 新機能は CLI/skill → service-gated tool → plug-in → MCP を優先。
3. **表面能力は session スコープ** — Desktop 機能は `session.platform` から解決する。
4. **決定論的・可逆な実行** — 破壊操作には復旧・監査・承認が要る。

規範契約:
[`.codex/WINDOWS_PLATFORM_CONTRACT.md`](.codex/WINDOWS_PLATFORM_CONTRACT.md)

---

## 所有権と復旧

| コンポーネント | lifecycle owner |
| --- | --- |
| Desktop `serve` backend | Electron main のみ |
| 生成用 llama-server | オペレーター / launcher |
| embedding llama-server（watchdog 起動時） | Go watchdog |
| メッセージング Gateway | Gateway 自身（Desktop 終了後も生存する設計） |
| WebUI / 固定 port dashboard | Desktop の `serve --port 0` とは別 |

Go watchdog は観測と、**自ら起動した** embedding の管理まで。Desktop backend の第二
所有者になってはいけない。argv 部分一致より exact process identity を優先する。

ガイド: [`scripts/windows/watchdog-go/README.md`](scripts/windows/watchdog-go/README.md)

---

## プラグインとサブモジュール

```powershell
uv run hermes plugins
```

代表例（件数は変動。有効化は profile と credential 次第）:

| 領域 | 例 |
| --- | --- |
| Desktop / ops | `hermes-bot-mode`, `desktop-dashboard`, `implementation_router` |
| Memory | `semantic_graph`, `memory/ebbinghaus`, `surfsense` |
| Media / XR | `voicevox_tts`, `vrchat-autonomy`, `unity_vrchat_bridge`, `aituber_onair` |
| Research | `shinka-osint`, `world-intel-osint` |
| Providers | `openai-codex`, `qwen-oauth`, `xai`, `hypura` |

`implementation_router` は **opt-in**。通常の picker / delegation / MoA / fallback を
置き換えず、自動 apply / publish もしません。

必要な外部 runtime があるときだけ:

```powershell
git submodule update --init --recursive
```

一覧スナップショット: [`docs/windows/INTEGRATIONS.md`](docs/windows/INTEGRATIONS.md)

---

## インストールと Desktop ビルド

```powershell
git clone https://github.com/zapabob/hermes-agent-windows.git
Set-Location hermes-agent-windows
uv sync --locked --all-extras
uv run hermes --version
uv run hermes setup
```

Desktop（Node 版は [`apps/desktop/package.json`](apps/desktop/package.json) に従う）:

```powershell
npm ci
npm run typecheck --workspace apps/desktop
npm run build --workspace apps/desktop
```

実行中の `Hermes.exe` の差し替えは所有権を意識した別操作です。バイナリ交換の前に
所有プロセスを止めてください。

秘密は profile の `.env`（または外部 vault）。非秘密設定は `config.yaml`。  
モデル重み・profile DB・token を commit しないでください。

---

## 版と provenance

| 事実 | 値 |
| --- | --- |
| Downstream 製品版 | `0.23.0`（`version_source: downstream`） |
| Upstream stable 参照 (R2) | `f97608f178d1ffeca59860195ab7da295f7c8e5f`（`0.21.5` / `v2026.9.24`） |
| 現行 semantic-refresh ceiling (U1) | `678a4762b887f3eabe5cad11254b2ab1ae859485` |
| 歴史的 provenance snapshot | `b51c055a12220f8c7c18660e8599365012e19532` |

引き継ぎ計画:
[`docs/windows/semantic-refresh-20260926/CURSOR_IMPLEMENTATION_PLAN_20260929.md`](docs/windows/semantic-refresh-20260926/CURSOR_IMPLEMENTATION_PLAN_20260929.md)

更新パイプライン:
`plan → snapshot → apply → restart-per-kind → verify → report`

---

## セキュリティ

- 秘密・個人 runtime・モデルファイル・調査成果物を commit しない。
- Security Center の mutation API は明示確認が必要。
- `hermes security` / `hermes egress` / `hermes secrets` で scan・egress・外部 vault。
- provider base URL はログ前にマスク。子プロセスは制限された環境変数のみ受け取る。

**Control MCP:** auth / journal / coordinator 契約はあるが、**production write は
DISABLED**。host grant-revocation・線形化・trusted producer・writer fence がすべて
閉じるまで有効化しない。テスト合格だけでは許可にならない。  
[`docs/control-mcp/IMPLEMENTATION_LOG.md`](docs/control-mcp/IMPLEMENTATION_LOG.md)

---

## ドキュメント案内

| 文書 | 内容 |
| --- | --- |
| [`docs/windows/INSTALL.md`](docs/windows/INSTALL.md) | Windows 導入の正本 |
| [`docs/windows/INTEGRATIONS.md`](docs/windows/INTEGRATIONS.md) | 任意連携のスナップショット |
| [`docs/windows/SECURITY_CENTER.md`](docs/windows/SECURITY_CENTER.md) | Security Center |
| [`docs/windows/feature-intake-20261028/`](docs/windows/feature-intake-20261028/) | 0.23.0 intake |
| [`AGENTS.md`](AGENTS.md) | 開発者・アシスタント向け契約 |
| [`SECURITY.md`](SECURITY.md) | セキュリティ方針 |

---

## Upstream プロジェクト

原作: [NousResearch/hermes-agent](https://github.com/NousResearch/hermes-agent)。  
upstream のドキュメント・installer・release・サポートは **upstream 配布物** 向けであり、
この派生を導入・承認するものではありません。

---

## ライセンスと帰属

Hermes Agent は Nous Research が MIT License の下で開発しています。本派生はその帰属・
copyright・貢献履歴を保持し、同じく [MIT License](LICENSE) で提供します。

Windows / ワークステーション向け変更は本リポジトリで独立に保守します。upstream と
downstream の issue・release・サポート主張・認定証拠は分離したままです。
