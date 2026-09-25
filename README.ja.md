# Hermes Agent Windows Workstation Edition

<p align="center">
  <a href="README.md" lang="en-GB">King's English</a> ·
  <a href="README.ja.md" lang="ja"><strong>日本語</strong></a> ·
  <a href="README.zh-CN.md" lang="zh-CN">简体中文</a>
</p>

> [!NOTE]
> 英語版の `README.md` が正本です。この日本語版は英語版の各節に追随します。

Electron デスクトップ、CLI、メッセージング gateway と、任意のローカル推論・メモリ・
音声連携を備えた、Hermes Agent の非公式 Windows ネイティブ版です。

この fork は1名のメンテナーが独立して保守しており、Nous Research との提携関係や
同社による承認はありません。ダウンストリームは
[zapabob/hermes-agent-windows](https://github.com/zapabob/hermes-agent-windows)
で保守しています。オリジナルの [Hermes Agent](https://github.com/NousResearch/hermes-agent)
は Nous Research が開発しており、upstream の帰属表示と [MIT License](LICENSE) を保持しています。

[![Windows Workstation Tier-1 CI](https://github.com/zapabob/hermes-agent-windows/actions/workflows/fork-cicd.yml/badge.svg)](https://github.com/zapabob/hermes-agent-windows/actions/workflows/fork-cicd.yml)

**現在のソース版: 0.21.3。** 記録済みの upstream release も 0.21.3（`v2026.9.14`）です。
この fork は `version_source: downstream` と固定 upstream snapshot
`b51c055a12220f8c7c18660e8599365012e19532` を維持します。ソース版の更新や main への
push は、stable installer の公開を意味しません。対応 channel は `stable` と `preview` です。

この Windows ネイティブ版が役に立ったら、リポジトリに Star をいただけると、
他の Windows ユーザーにも見つけてもらいやすくなります。

## 30秒でわかる導入

> **TL;DR:** 下の5コマンドを順に実行します。モデルプロバイダーはセットアップ
> ウィザードで設定でき、基本CLIの起動に任意プラグインやGitサブモジュールは不要です。

現在すぐに使えるのは source route です。Windows 11 x64、PowerShell、Git、`uv`、
Python 3.11–3.13 を用意してください。Node.js は Desktop をビルドする場合だけ必要です。

```powershell
git clone https://github.com/zapabob/hermes-agent-windows.git
Set-Location hermes-agent-windows
uv sync --locked --all-extras
uv run hermes setup
uv run hermes chat
```

これは30秒で読めるコマンド経路です。初回の依存関係ダウンロードやネイティブビルドには
さらに時間がかかります。同じ checkout から Desktop を開く場合は、次を実行します。

```powershell
uv run hermes desktop
```

installer または portable ZIP を使う場合は、
[ダウンストリーム Releases](https://github.com/zapabob/hermes-agent-windows/releases)
に対応 asset が公開されていることを確認し、`SHA256SUMS.txt` と照合してください。
詳しい手順は [Windows 導入ガイド](docs/windows/INSTALL.md) にあります。

## この fork が追加するもの

- **BYOK（自分のキー持ち込み）と OAuth 優先。** 実行時に必須のホスト型サービスは
  ありません。OAuth によるサブスクリプションのサインイン（OpenAI Codex/ChatGPT、
  xAI Grok、Qwen、MiniMax、Nous Portal など）、同梱42 model provider への自前 API key、
  またはローカル llama.cpp server のいずれでも動作します。Nous Portal は任意の
  provider の1つであり、必須ではありません。
- Python、Electron、Go、upstream API 互換、regression、security lock の Windows Tier-1 CI
- 非管理者アカウントや空白入り path を含む installer、portable、upgrade E2E
- 移動しない固定 upstream snapshot `b51c055a12220f8c7c18660e8599365012e19532`
- 公式 provider/memory seam 上のローカル llama.cpp/GGUF 推論と embedding lifecycle
- Electron main が単独で所有する Desktop Python backend と、自ら起動した embedding
  server だけに権限を限定した外部 Go watchdog
- 既存の model picker、親所有の推論、credential を持たない Docker 実行を再利用する
  逐次型エンジニアリング workflow（`implementation_router`）
- GPU のない hosted CI と分離した consumer NVIDIA workstation の実機証拠

## プラグインとGitサブモジュール

Hermesの標準ディレクトリプラグインは、`plugin.yaml`、`__init__.py`、
`register(ctx)` から検出されます。バンドル済みの標準ルートプラグイン53件を下に
分類しました。`lmcache` は独自の登録経路を持つ旧形式manifestとして同梱されています。
有効状態は `uv run hermes plugins` でprofileごとに確認できます。

| 分野 | バンドル済みルートプラグイン |
| --- | --- |
| Agent・運用 | `ai-employee-org`, `ai-partner-os`, `airi`, `aituber-onair`, `aituber-kit`, `book-to-skill`, `desktop-dashboard`, `disk-cleanup`, `freebuff`, `freellmapi`, `google-colab`, `google_meet`, `hermes-antigravity`, `hermes-gpt`, `hermes-bot-mode`, `implementation_router`, `line-ai-bot`, `lm-twitterer`, `memory-llm-wiki`, `notebooklm`, `oh-my-hermes`, `openclaw-vendor`, `openmanus`, `plugin-doctor`, `research-desk`, `scrapling-feeds`, `teams_pipeline`, `warashibe-reselling` |
| Media・音声・XR | `akari-video`, `buzz`, `fish-audio-tts`, `hakua-tts-bridge`, `heygen`, `hyperframes`, `irodori-tts`, `questframe-fh6vr`, `sillytavern`, `spotify`, `unity-cli`, `unity-vrchat-bridge`, `unsloth-studio`, `voicebox`, `voicevox-tts`, `vrchat-autonomy` |
| Knowledge・security・OSINT | `osint-agent`, `security-guidance`, `semantic-graph`, `shinka-osint`, `sitdeck-osint`, `surfsense`, `tookie-osint`, `world-intel-osint`, `worldmonitor-osint` |
| 旧形式manifest | `lmcache` |

保持している [統合インベントリ](docs/windows/INTEGRATIONS.md) は、記録時点の
154件のプラグインmanifestを記載しています。その後 `hermes-antigravity` と
`implementation_router` が追加されたため、現在のツリーには156件あります。専門的な
provider群は個別に検出され、設定した機能だけがsessionへ入る構造です。件数はツリーの
内容を示すもので、実行時の有効化や認定を示すものではありません。

| 検出ファミリー | 同梱provider・adapter |
| --- | --- |
| Browser (3) | `browser_use`, `browserbase`, `firecrawl` |
| Cron (1) | `chronos` |
| Dashboard認証 (4) | `basic`, `drain`, `nous`, `self_hosted` |
| Image生成 (7) | `deepinfra`, `fal`, `krea`, `openai`, `openai-codex`, `openrouter`, `xai` |
| Memory (9) | `byterover`, `ebbinghaus`, `hindsight`, `holographic`, `honcho`, `mem0`, `openviking`, `retaindb`, `supermemory` |
| Model provider (42) | `actual`, `ai-gateway`, `alibaba`, `alibaba-coding-plan`, `anthropic`, `arcee`, `azure-foundry`, `bedrock`, `commandcode`, `copilot`, `copilot-acp`, `custom`, `deepinfra`, `deepseek`, `fireworks`, `freebuff`, `freellmapi`, `gemini`, `gmi`, `huggingface`, `hypura`, `kilocode`, `kimi-coding`, `meta-ai`, `minimax`, `nebius-token-factory`, `nous`, `novita`, `nvidia`, `ollama-cloud`, `openai-codex`, `opencode-free`, `opencode-zen`, `openrouter`, `qwen-oauth`, `router`, `stepfun`, `upstage`, `vertex`, `xai`, `xiaomi`, `zai` |
| Observability (1) | `langfuse` |
| Messaging platform (22) | `a2a`, `buzz`, `dingtalk`, `discord`, `email`, `feishu`, `google_chat`, `homeassistant`, `irc`, `line`, `matrix`, `mattermost`, `ntfy`, `photon`, `raft`, `simplex`, `slack`, `sms`, `teams`, `telegram`, `wecom`, `whatsapp` |
| Video生成 (3) | `deepinfra`, `fal`, `xai` |
| Web検索・抽出 (11) | `brave_free`, `cloakbrowser`, `ddgs`, `exa`, `firecrawl`, `keenable`, `parallel`, `scrapling`, `searxng`, `tavily`, `xai` |

`gateway/platforms/` 配下の組み込み adapter は、Signal、BlueBubbles（iMessage）、
Weixin、Yuanbao、WhatsApp Business Cloud API、汎用 webhook、OpenAI 互換 API server
を追加します。

Gitサブモジュールは任意の連携機能です。すべて必要な場合だけ、
`git submodule update --init --recursive` を実行してください。

| Path | Repository | 用途 |
| --- | --- | --- |
| `plugins/hermes-bot-mode/desktop` | [Hermes-Bot-Mode](https://github.com/zapabob/Hermes-Bot-Mode.git) | Desktop bot roster UI |
| `plugins/artemis` | [artemis](https://github.com/zapabob/artemis.git) | 自然言語指示による Android 自動化 |
| `vendor/openclaw-mirror/AI-Scientist` | [AI-Scientist](https://github.com/zapabob/AI-Scientist.git) | 科学agent連携 |
| `vendor/openclaw-mirror/ATLAS` | [ATLAS](https://github.com/zapabob/ATLAS.git) | Research agent連携 |
| `vendor/openclaw-mirror/ShinkaEvolve` | [ShinkaEvolve](https://github.com/zapabob/ShinkaEvolve.git) | 進化workflow連携 |
| `vendor/neuro-sdk` | [neuro-sdk](https://github.com/zapabob/neuro-sdk.git) | Neuro連携SDK |
| `vendor/openmanus` | [OpenManus](https://github.com/zapabob/OpenManus.git) | OpenManus runtime |
| `vendor/SillyTavern` | [SillyTavern](https://github.com/zapabob/SillyTavern.git) | Local character chat frontend |
| `vendor/shinka-osint` | [ShinkaEvolve-OSINT](https://github.com/zapabob/ShinkaEvolve-OSINT.git) | OSINT分析runtime（private repository。初期化にはアクセス権が必要） |
| `vendor/buzz` | [buzz](https://github.com/zapabob/buzz.git) | 音声文字起こしruntime |
| `vendor/officecli` | [OfficeCLI](https://github.com/zapabob/OfficeCLI.git) | Office文書CLI |
| `vendor/akari-video` | [akari-video](https://github.com/zapabob/akari-video.git) | AI video editor |
| `vendor/cloakbrowser` | [cloakbrowser](https://github.com/zapabob/cloakbrowser.git) | Browser automation runtime |
| `vendor/airi` | [airi](https://github.com/zapabob/airi.git) | Avatar・companion runtime |
| `vendor/oh-my-hermes` | [oh-my-hermes](https://github.com/zapabob/oh-my-hermes.git) | Hermes workflow拡張 |
| `vendor/OpenMausBot` | [OpenMausBot](https://github.com/zapabob/OpenMausBot.git) | Desktop automation bot |
| `vendor/heygen-cli` | [heygen-cli](https://github.com/heygen-com/heygen-cli.git) | HeyGen CLI client |

## 1. 製品の位置づけ

Hermes Agent Windows Workstation Edition は、常時稼働するローカル AI ワークステーション
向けの Windows ファーストなダウンストリーム・ディストリビューションです。Hermes CLI
コマンド、公開契約、プラグインモデル、upstream の履歴を維持しながら、Windows ネイティブ
動作、ローカルモデル、メモリ、音声、VR/Unity、復旧について明確なダウンストリーム方針を
定めています。

製品台帳は [FEATURES.yaml](FEATURES.yaml) です。upstream 所有ファイルに保持する直接
パッチは [CARRY.yaml](CARRY.yaml) で別途追跡し、upstream の commit は
`UPSTREAM_ADOPTION.yaml` で分類します。方針の要約は
[DOWNSTREAM_POLICY.md](DOWNSTREAM_POLICY.md) です。

## 2. Windows ファーストの目標

主対象は、ネイティブ Python、ネイティブ Node/Electron、対話型デスクトップ、コンシューマー
向け NVIDIA GPU を備えた Windows 11 x64 です。ローカル LLM と embedding サービス、
音声サービス、VRChat/Unity 連携、リモート管理を含む継続運用を想定しています。

Windows は upstream のプラットフォーム優先順位とは独立した Tier-1 対象です。ネイティブ
動作は `windows-latest` でテストし、Linux 上のクロスコンパイルは Windows ランタイムの
証拠として認めません。バックグラウンドの Git・web helper 呼び出しは非表示プロセス作成
フラグを使い、Git wrapper は非対話 probe をユーザー向け terminal から分離します。これは
既知の helper 起動経路への対処であり、あらゆるコンソール発生源を排除したという主張では
ありません。

## 3. 対象ユーザー

Windows AI ワークステーションを運用し、ローカル推論、長時間稼働サービス、メモリ、
デスクトップ動作、復旧をソースレベルで管理する必要があるオペレーターと開発者を対象と
します。PowerShell、Git、Python 環境、Node ツール、CI 結果の確認に慣れていることを
前提とします。

最も簡潔な公式 Hermes の導入方法と upstream のサポートモデルを利用する場合は、
第 15 節のオリジナルプロジェクトを使用してください。

## 4. ダウンストリームの利点

- **ベンダーロックインなし。** どの provider も任意です。OAuth サインイン（OpenAI
  Codex/ChatGPT、xAI Grok、Qwen、MiniMax、Nous Portal）、既存の Claude Code OAuth
  credential、自前の API key、ローカル llama.cpp server のいずれも同じ provider registry
  で動作します。`hermes proxy` は OAuth provider をローカルの OpenAI 互換 endpoint として
  公開し、`hermes fallback` は primary が失敗したときに provider を連鎖させます。
- **Windows ランタイムと復旧の契約。** Desktop backend の所有者は1つで、Go watchdog は
  補助に徹します（第8節）。
- **ローカル推論。** `scripts/windows/` 配下の llama.cpp/GGUF fallback、hot-swap preset、
  GPU 別 launcher に加え、Hypura provider と harness（`hermes harness`）を提供します。
- **メモリ。** Semantic Graph の hybrid retrieval と Ebbinghaus cognitive memory
  provider（第9節）。
- **エンジニアリング workflow。** `implementation_router` plugin は、既存の auxiliary
  model picker を通じて planner、worker、決定論的検証、reviewer の各段階を実行します。
  入口は `engineering_run` または `/engineer` です。
- **連携機能。** ローカル秘書、VRChat/Unity、ローカル音声、AITuber、OSINT/Shinka、
  Desktop の Git/review pane、分離された Antigravity CLI bridge（`hermes-antigravity`）。
- **Credential の衛生管理。** credential lease は選択した entry に束縛され、空の
  credential pool から継承 client で委譲 child を起動することはできません。provider の
  base URL は log に出る前にマスクされます。

これらの機能は公式 Hermes API と組み合わせて動作します。この fork は session、approval、
profile、gateway、model catalogue、tool registry について、並行する別の正本を作りません。

## 5. 検証済み機能マトリクス

| 分野 | 検証済み実装 | 契約の証拠 |
| --- | --- | --- |
| Windows runtime | ネイティブ path、process、IPC、NTFS handoff、terminal、credential、power、GPU helper | `tests/downstream/test_windows_contracts.py` |
| Desktop backend | Electron main による単一所有者の backend lifecycle | `apps/desktop/electron/single-owner-backend-lifecycle.test.ts` |
| Recovery | read-only status と厳密な identity 権限を持つ外部 Go watchdog | `scripts/windows/watchdog-go/authority_test.go` |
| Local inference | llama.cpp/GGUF fallback と hot-swap script | `tests/hermes_cli/test_llama_fallback_runtime.py` |
| Local embeddings | watchdog embedding lifecycle と Semantic Graph backend | `scripts/windows/watchdog-go/embedding_test.go` |
| Local secretary | 公式 agent boundary 上の read/write action 分離 | `tests/downstream/test_upstream_api_contracts.py` |
| Providers | Hypura/local provider 連携 | `tests/fork/test_hypura_oai_proxy.py` |
| Provider fallback | fallback chain と provider rotation | `tests/hermes_cli/test_fallback_chain.py` |
| Memory | Semantic Graph hybrid retrieval と Ebbinghaus cognitive extension | `tests/plugins/test_semantic_graph_registration.py`, `tests/plugins/test_ebbinghaus_plugin.py` |
| Engineering workflow | route admission を備えた逐次 planner/worker/reviewer router | `tests/implementation_router/test_route_admission.py` |
| VR and Unity | VRChat autonomy tooling と Unity bridge | `tests/plugins/test_vrchat_autonomy_plugin.py` |
| Voice | Irodori、VOICEVOX、local TTS route | `tests/plugins/test_irodori_tts_plugin.py` |
| AITuber | AITuber OnAir と AITuber Kit plugin | `tests/plugins/test_aituber_onair_plugin.py` |
| OSINT/Shinka | Shinka、SitDeck、WorldMonitor、OSINT plugin surface | `tests/plugins/test_shinka_osint_plugin.py` |
| Desktop | 公式 Desktop IPC と pane contract を用いた Git/review extension | `apps/desktop/electron/git-review-ops.test.ts` |
| Security | security guidance と強化された approval/execution boundary | `tests/plugins/test_security_guidance_plugin.py` |

機能ごとの所有者、公開 surface、upstream との重複、Windows 要件、テスト、統合方針は
すべて `FEATURES.yaml` に記録しています。旧来の watchdog 管理 Desktop backend は
そこで retired と記録されています。これらは範囲を絞った検証であり、すべての任意連携の
認定ではありません。

## 6. Windows Tier-1 サポート契約

Tier-1 の対象には、ネイティブ drive path、MSYS `/c/...` とサポート対象の WSL
`/mnt/c/...` alias、NTFS lock、ロック中の executable と extension module の update、
process tree、適用可能な Job Object 動作、PowerShell quoting、Git Bash boundary、
CP932/UTF-8 boundary、CRLF、venv `Scripts\`、Electron stdio pipe が含まれます。

ランタイム認定では、sleep/resume、network と loopback provider の復旧、Desktop 再起動、
updater handoff、watchdog 復旧、llama restart と hot-swap、embedding restart、
profile/session persistence を検証します。規範となる契約は
[.codex/WINDOWS_PLATFORM_CONTRACT.md](.codex/WINDOWS_PLATFORM_CONTRACT.md) です。
ネイティブ Python、Desktop、installer、portable、upgrade、watchdog、security の各検証は
別々の gate であり、mock のみの結果や skip された P0 テストでは Windows 対応を認定できません。

## 7. ローカル AI アーキテクチャ

公式 Hermes の provider と model catalogue の契約を正本とします。ダウンストリームの
ローカルランタイムは、llama.cpp/GGUF を local fallback runtime、Hypura を provider
plugin seam、local embedding を Semantic Graph backend と watchdog 管理の loopback
service として、これらの契約へ接続します。hot-swap preset は個別に導入した GGUF
ファイルを選択します。推論の準備完了には、port が開いていることではなく実際のモデル応答が
必要です。

オペレーター用 script は `scripts/windows/` 配下にあります（例: `start-llama-hotswap.ps1`、
`switch-llama-hotswap.ps1`、GPU 別の `start-hermes-llama-fallback-*.ps1` launcher）。
ランタイム plugin の entrypoint は `plugins/` 配下に保ち、公式 discovery が引き続き
機能するようにします。ローカルサービスへのリモートアクセスは
`Manage-HermesTailscaleServe.ps1`（Tailscale Serve）で設定し、検証専用モードも使えます。

## 8. Watchdog と復旧のアーキテクチャ

サポート対象の Windows 構成では、Desktop Python backend の lifecycle は Electron main
だけが所有します。health の観測、PID、port、token、manifest は、他の component に
破壊的な lifecycle 権限を与えるものではありません。

外部 Go watchdog は read-only の status surface を持つ補助 supervisor です。サポート
対象の破壊的操作の範囲は、自ら明示的に起動して所有する embedding 用 `llama-server`
instance に限られ、Desktop backend の第2の所有者ではありません。旧来の watchdog による
backend 所有と Desktop 再起動の経路は削除済みです。
[watchdog ガイド](scripts/windows/watchdog-go/README.md) と
[Windows platform contract](.codex/WINDOWS_PLATFORM_CONTRACT.md) を参照してください。

ダウンストリームの Python service module は副作用のない契約です。実際の operator
startup と deployment は `scripts/windows/` 配下の PowerShell と Go surface に残します。

## 9. メモリと semantic retrieval

profile は設定、credential、session、メモリを分離します。Semantic Graph plugin は、
公式 plugin interface と memory interface を通して、graph storage、hybrid retrieval、
embedding、fusion、abstention、cognitive helper を提供します。Ebbinghaus provider は
experience と retention policy を追加し、Semantic Graph に bridge できます。両者とも
独立した plugin entrypoint と対象を絞った test suite を維持します。

外部 memory provider（上表の Honcho、Mem0、Supermemory、Hindsight など）は
`hermes memory` で選択し、`hermes journey` で学習した skill と memory の推移を確認できます。
ソース配布物にモデルファイルや個人のメモリは含まれません。

## 10. VRChat、Unity、音声の統合

VRChat autonomy tool、observation/relay helper、Unity bridge package、VOICEVOX、
Irodori、その他の local TTS route は、ダウンストリーム所有の機能です。core を VR や
音声専用 runtime に変えず、公式の plugin、tool、TTS contract を使用します。各 SDK、
アプリケーション、ハードウェアは別途設定が必要です。

外部への公開と書き込み action は、引き続き明示的な approval を必要とします。ローカルでの
生成は、外部 account への公開や変更を許可するものではありません。

## 11. インストール

対象は Windows 11 x64 です。PowerShell、Git、`uv`、Python 3.11–3.13 を使用します。
依存関係のインストールには数分かかることがあり、任意の extra にはネイティブビルドツールが
必要な場合があります。ネイティブアプリケーションに WSL は不要です。

```powershell
git clone https://github.com/zapabob/hermes-agent-windows.git
Set-Location hermes-agent-windows
uv sync --locked --all-extras
uv run hermes --version
uv run hermes setup
```

セットアップウィザードでモデルプロバイダーを選択します。リモート provider を使う場合、
GPU は任意です。ローカルモデルには別途用意したモデルファイルと互換推論ランタイムが必要で、
このリポジトリにモデルの重みは含まれません。

Windows release workflow は、ユーザー単位の NSIS installer と portable ZIP を作成し、
stable tag で公開する前に clean install、起動、upgrade E2E を実行します。公開済みの
成果物は
[ダウンストリーム Releases](https://github.com/zapabob/hermes-agent-windows/releases)
からのみ取得し、`SHA256SUMS.txt` を確認してください。現在の candidate は
`release-manifest.json` に別の記録がない限り unsigned です。手順の正本は
[Windows 導入ガイド](docs/windows/INSTALL.md) です。そこにある旧版の例は 0.21.3 の
release の証拠ではありません。

公式 upstream の installer は upstream 製品を対象とします。この配布物には、この
ダウンストリームのリポジトリか、その公開済み release asset を使用してください。

### Desktop のビルド

[`apps/desktop/package.json`](apps/desktop/package.json) が受け入れる Node.js の
バージョンを使用します。Desktop は npm workspace なので、JavaScript の依存関係は
リポジトリのルートでインストールします。

```powershell
npm ci
npm run typecheck --workspace apps/desktop
npm run build --workspace apps/desktop
```

ビルドはアプリケーションファイルを生成します。新しい Desktop binary のパッケージ化と
インストールは別の操作です。プロセスの実行中に executable を置き換えないでください。

24 時間稼働の service や Scheduled Task を有効にする前に、設定を確認してください。
API key と token は profile ごとの Hermes secret store、または Hermes の文書に従って
`.env` に保存し、secret ではない設定は `config.yaml` に保存します。

## 12. 更新と upstream 統合の方針

upstream は統合対象であり、ダウンストリーム製品の正本ではありません。各 campaign では
`.codex/UPSTREAM_SNAPSHOT.json` に正確な SHA を固定し、commit を
`UPSTREAM_ADOPTION.yaml` で分類し、直接保持する変更を `CARRY.yaml` に記録します。
`scripts/upstream/snapshot_sync.py` は明示的な SHA を受け取り、変動する最新 branch を
解決しません。保持している release-provenance snapshot は
`b51c055a12220f8c7c18660e8599365012e19532` です。

公式の public API を優先します。security と data integrity の修正は、検証済みのより
強いダウンストリーム特性と組み合わせます。upstream に似た名前の機能が加わったという
理由だけでダウンストリーム機能を削除せず、置き換えには parity の証拠を要求します。
upstream の一括 merge、rebase、cherry-pick を契約レビューの代わりにしないでください。

稼働中のワークステーションを更新する前に、未 commit の作業と各 profile を保存し、現在の
commit を記録し、配備済み Desktop のロールバック用コピーを残してください。Desktop の
control backend、メッセージング gateway、llama server、embedding server、Go watchdog は
それぞれ別の lifecycle を持ち、1つのウィンドウを閉じても全部が再起動したことにはなりません。
再起動後は、アプリケーションのウィンドウ、backend の応答、実際のモデル準備状況を確認して
ください。[ローカルランタイム設定](docs/local-secretary-runtime.md)、
[release policy](docs/windows/RELEASE_POLICY.md)、[AGENTS.md](AGENTS.md) を参照してください。

## 13. アーキテクチャ

fork 所有の Python boundary は `downstream/` 配下に置きます。`compat/hermes` は公式
contract へ委譲し、`platform/windows` は native policy を所有し、`services` は
long-lived service contract を定義し、`features` は product ledger を検証します。
意図的に `platform` という名前の top-level Python package は設けません。

共通の agent core は CLI、メッセージング gateway、TUI、Electron Desktop の背後にあります。
その周囲に、集中管理された slash command registry、cron スケジューリング、複数 profile で
使う kanban board、subagent への委譲、skill curator、Mixture of Agents（`hermes moa`）、
MCP client/server（`hermes mcp`）、ACP、profile があります。core は狭い共通境界のままで、
plugin と skill が capability を保持し、profile-aware な公式 path helper が state path を
所有し、prompt cache と message role の invariant は必須です。

## 14. セキュリティ

secret、個人の runtime data、profile database、model file、local artifact、生成された
credential を commit しないでください。write、publish、destructive、shell action は
明示的な approval の内側に置きます。child service の environment には必要な variable
だけを渡し、ambient credential を継承させません。

provider の base URL は log 出力前にマスクされます。Relay 0.8 の trace-context header
（`traceparent`、`tracestate`、`baggage`）は、`config.yaml` で
`telemetry.relay.propagate_trace_headers: true` を設定しない限り provider 呼び出しから
除去されます。`hermes security` は supply-chain 監査と Windows ワークステーションの
マルウェア対策を実行し、`hermes egress` は credential 注入型 egress firewall を管理し、
`hermes secrets` は Bitwarden や 1Password などの外部 secret source と接続します。

security gate は、lock 済み Python graph、Python advisory、production npm advisory、
Go module integrity、OSV result、supply-chain policy、この repository の security
regression test を検査します。green の local unit test は、exact-head CI や live
runtime evidence の代わりにはなりません。[SECURITY.md](SECURITY.md) を読んでください。
未解決の private contract は認定されていません。

## 15. Upstream プロジェクト

オリジナルのプロジェクトは [NousResearch/hermes-agent](https://github.com/NousResearch/hermes-agent)
です。公式 upstream の installer、website、documentation、issue tracker、support channel は
upstream distribution に適用され、このダウンストリーム repository を install または
endorse するものではありません。upstream への貢献は、その作者と帰属表示を保持します。

## 16. ライセンスと帰属表示

オリジナルの Hermes Agent は Nous Research が開発し、MIT License の下で提供しています。
このダウンストリームはその帰属表示、オリジナルの copyright と contributor history、
[MIT License](LICENSE) を保持します。ダウンストリームの作業は独立して保守されており、
upstream と downstream の issue、release、製品上の主張は明確に区別する必要があります。
