# Hermes Go Watchdog（Windows）

Hermes Desktop（`Hermes.exe`）と Desktop が spawn する `hermes serve` バックエンドを**相互監視**する独立プロセスです。  
**Hermes Agent の plugin / tool / skill / MCP / cron には一切登録しません。**

## 隔離（AI から制御不可）

| 項目 | 内容 |
|------|------|
| プロセス | Hermes Python/Electron とは別バイナリ |
| 設定 | `%LOCALAPPDATA%\HermesWatchdog\`（ロック・状態 JSON） |
| ログ | `%HERMES_HOME%\logs\hermes-go-watchdog.log` |
| 変更 API | 公開しない（認証付き管理口も存在しない） |
| 読取 API | `GET /health`, `GET /api/status`, `GET /api/v1/status`（ローカル / tailnet） |

## ビルド

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts\windows\Build-HermesGoWatchdog.ps1
```

成果物: `scripts\windows\watchdog-go\dist\hermes-watchdog.exe`

## 起動

通常のワークステーション起動では、管理者が登録した
`HermesGoWatchdogBootAutoStart` Scheduled Task がブート時に
`Start-HermesGoWatchdog.ps1` を非表示 PowerShell で実行します。手動操作では、
管理者 PowerShell から同じ launcher を実行します。どちらも最終的に
Windows GUI subsystem の `hermes-watchdog.exe` を画面なしで起動し、別の
Watchdog 起動機構は設けません。

```powershell
# 環境変数（例）
$env:HERMES_WATCHDOG_TS_AUTHKEY = "<ts-authkey>"   # 任意: tsnet 有効化

powershell -NoProfile -ExecutionPolicy Bypass -File scripts\windows\Start-HermesGoWatchdog.ps1
```

launcher は管理者として実行した PowerShell だけを受け付けます。これにより、通常権限の
Hermes Agent と watchdog プロセスの間に Windows のプロセス権限境界を設けます。

### フラグ（Start スクリプト経由）

| フラグ | 既定 | 説明 |
|--------|------|------|
| `-IntervalSec` | 20 | 監視周期 |
| `-FailThreshold` | 2 | backend 連続失敗で Desktop 再起動 |
| `-Once` | off | 1 周期だけ実行して終了 |
| `-NoTsnet` | off | tsnet を強制 OFF |
| `-Listen` | 127.0.0.1:9920 | ローカル HTTP |

`plugins.entries.semantic-graph.config.embedding.runtime.enabled: true` の場合、
Start スクリプトは同じ `config.yaml` から 8082 の llama.cpp 起動情報を読み、Go
watchdog に渡します。watchdog は `/health` が healthy な既存プロセスを置換せず、
停止後または自ら起動したプロセスが初期化 timeout を超えた場合だけ stock
`llama-server` を再起動します。モデル取得、8080 への操作、未知 PID の停止は行いません。

## Tailscale（tsnet）

1. Tailscale 管理画面で **auth key** を発行（推奨: reusable + タグ付き）
2. 環境変数 `HERMES_WATCHDOG_TS_AUTHKEY` または `TS_AUTHKEY` に設定（**リポジトリにコミットしない**）
3. 起動すると tailnet 上で `hermes-watchdog` として `:443` で待受
4. 他ノードから: `curl -k https://hermes-watchdog/health`（MagicDNS / ホスト名）

## HTTP API

| Method | Path | 認証 | 説明 |
|--------|------|------|------|
| GET | `/health` | 不要 | 生存確認 |
| GET | `/api/status` | 不要 | ウォッチドッグ状態 JSON |
| GET | `/api/v1/status` | 不要 | バージョン付き状態 JSON |

HTTP は読み取り専用です。pause、resume、cycle、stop、restart、force-restart、
ロック削除、PID 指定停止を行う API は、HTTP、MCP、tool、plugin、skill、cron の
いずれにも公開しません。

## 監視ロジック

1. **起動時 prewarm（非同期）** — HTTP / RunLoop 起動後に goroutine で managed `hermes serve --skip-build`（既定 `:9119`）を立ち上げ、`%LOCALAPPDATA%\HermesWatchdog\desktop-backend.json` に URL/token/port を公開。cold start で制御プレーンをブロックしない
2. `Hermes.exe` 不在 → 管理 backend は reaping しない → Desktop 起動（manifest があれば `HERMES_DESKTOP_REMOTE_*` も注入）
3. Desktop 生存 + backend 不在 → **Electron 再起動の前に** managed serve を起動/復旧
4. 連続失敗が `-FailThreshold` 以上 → Desktop 強制再起動
5. 予約 ops ポート (9120/8787/9920/…) は backend 判定・reap 対象外（従来どおり）
6. A2A Hub (`:9123`) と A2A Round-Robin (`:9124`) は別系統のバックグラウンドサービスであり、watchdog の直接監視・reap 対象外

### Desktop ショートカット

パッケージ `Hermes.exe` 直起動は `HERMES_DESKTOP_*` を付けない。Go watchdog が prewarm していれば Desktop は `desktop-backend.json` を読んで **15s 以内** に既存 serve へ接続する（`apps/desktop/electron/watchdog-backend.ts`）。

## 追加フラグ（exe / Start スクリプト）

| フラグ | 既定 | 説明 |
|--------|------|------|
| `-prewarm-backend` | on | serve の prewarm / 常時監督 |
| `-managed-backend-port` | 9119 | watchdog 管理の固定 serve ポート（9120/8787/9920 とは別） |
| `-backend-start-timeout` | 120 | `/api/status` 待ち (秒) |
| `-backend-ready-timeout` | 45 | `/api/status` 待ち (秒) |
| `-embedding-enabled` | off | 設定済み loopback embedding server の監督 |
| `-embedding-endpoint` | なし | `http://127.0.0.1:8082` のような健康確認先 |
| `-embedding-server` / `-embedding-model` | なし | 既存 llama-server と GGUF の絶対パス |
| `-embedding-args-json` | `[]` | `--embedding` を含む固定 llama.cpp 引数配列 |
| `-embedding-start-timeout` | 180 | watchdog 所有 PID を再起動するまでの初期化待機秒数 |

## 監視ロジック（旧 PowerShell 版との差分）

## 停止

- ユーザーまたは管理者が `Start-HermesGoWatchdog.ps1 -Stop` を直接実行
- 強制置換は同スクリプトの `-ForceRestart` を operator-only 経路で実行
- ロック: `%LOCALAPPDATA%\HermesWatchdog\watchdog.lock`

更新、計画停止、uninstall は launcher を Agent から呼ぶ経路では行わず、承認付き
ライフサイクル管理経路が `maintenance.json` の fence を取得してから実行します。
watchdog は有効な fence が存在する間、Desktop、backend、embedding を復旧しません。

## スタック再起動との関係

`restart-hermes-stack.ps1 -StartGoWatchdog` で**明示指定時のみ**起動（既定 OFF）。  
既存 `dist/hermes-watchdog.exe` があれば rebuild しない。欠落時のみ `BuildIfMissing`（SkipTest・180s タイムアウト）。失敗時はスタック全体を止めず watchdog 起動をスキップ。  
Hermes Agent から launcher の直接実行と変更操作は到達不可です。状態と PID、直近結果
だけを読み取れます。
