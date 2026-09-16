# Windows Desktop Backend Lifecycle — Authority Census (Before)

## 0. Metadata
- **Date**: 2026-09-16
- **Target Repository**: `zapabob/hermes-agent-windows`
- **Baseline Commit**: `97ff5b6249e4b0d968a1b6bb6f6c69fc2f0ed487`
- **Scope**: Windows AI Workstation Harness — Desktop/Python Backend Lifecycle Authority Census

---

## 1. Executive Summary & Dual Authority Proof

現在、`hermes-agent-windows` において Python backend（`hermes serve`）のライフサイクル管理権限（起動・監視・終了・再接続）は、**Electron Desktop main プロセス** と **Go Watchdog デーモン** の両方に分散・重複（二重 authority）している。

```text
                     Current Backend Spawn/Recovery Authority (DUAL)

Electron main ───────────────┐
  - startHermes()            ├──> Python Backend (`hermes serve`)
  - backendConnectionState   │    (PIDs, tokens, ports differ or collide)
                             │
Go Watchdog ─────────────────┘
  - BackendManager.EnsureHealthy()
  - desktop-backend.json
  - PrewarmBackend() / recovery loop
```

### 二重 Authority による障害メカニズム
1. **競合する起動経路**:
   - Go Watchdog は起動時または定期サイクルで `BackendManager.EnsureHealthy()` を呼び出し、固定ポート（デフォルト 9119）で `hermes serve` を prewarm 起動して `%LOCALAPPDATA%\HermesWatchdog\desktop-backend.json` に PID・ポート・トークンを書き出す。
   - Electron Desktop main は `startHermes()` 実行時、`primary-backend-startup.ts` 内の `resolvePrewarmedLocal` 経由で `watchdog-backend.ts` の `resolveWatchdogPrewarmedBackend()` を呼び、`desktop-backend.json` が有効であればそれを `kind: 'prewarmed-local'` として採用する。
   - 一方で、`desktop-backend.json` の検証が失敗するか、または Desktop が独自に起動した場合は、Electron main 自身が `--port 0` で child process として `hermes serve` を spawn し、`backendConnectionState.attachProcess()` で保持する。
2. **所有権の喪失と状態の乖離**:
   - Desktop が `prewarmed-local` に接続した場合、Desktop 側には ChildProcess ハンドルが存在しない。そのため、Desktop 再起動時やクラッシュ時にプロセスを適切に終了・追跡できず、古い PID やポートが取り残される。
   - 逆に Go Watchdog は Desktop 側の `backendConnectionState` の generation や in-flight dial を認知できないため、Desktop が新しい backend を spawn している最中に古い prewarmed backend を再起動したり、`desktop-backend.json` を上書きして Desktop の接続先を混乱させる。
3. **stale manifest / fence による拘束**:
   - `desktop-backend.json` や `DESKTOP_STOP`（`maintenance.json`）がファイルシステム上に永続化され、それが「権限（Authority）」として扱われているため、プロセス再起動やクラッシュ後に古いファイル情報に拘束されて再疎通不能に陥る。

---

## 2. Tracked Symbols & Location Census

### 2.1 Electron Main Process (`apps/desktop/electron/`)
- **`startHermes`** (`apps/desktop/electron/main.ts:12202`):
  - Primary backend 起動のエントリーポイント。
  - `backendConnectionState.getPromise()` による重複排除。
  - `runPrimaryBackendStartup()` の呼び出し。
  - `resolvePrewarmedLocal` のハンドラ内で `resolveWatchdogPrewarmedBackend()` を呼び出し。
  - fallback または標準として自身の `spawn()` によるローカル backend 起動と `claimBackendChild()`、`backendConnectionState.attachProcess()`。
- **`runPrimaryBackendStartup`** (`apps/desktop/electron/primary-backend-startup.ts:86`):
  - 起動シーケンスのオーケストレーション。
  - 現状: `resolvePrewarmedLocal` / `kind: 'prewarmed-local'` が残存。
  - 欠落: upstream に存在する `AbortSignal`、`runBackendStartStep()`、`assertCurrentAttempt()` による各境界の世代・キャンセルチェック。
- **`createBackendConnectionState`** (`apps/desktop/electron/backend-connection-state.ts:11`):
  - generation 管理（`startAttempt`, `attachProcess`, `clearForCurrentProcess`, `invalidate`）。
  - 現状: upstream に存在する `pendingPromise`、`getPendingPromise()`、および promise settle 時の generation-aware な自動 cleanup が未実装。
- **`resolveWatchdogPrewarmedBackend`** (`apps/desktop/electron/watchdog-backend.ts:62`):
  - `%LOCALAPPDATA%\HermesWatchdog\desktop-backend.json` を読み取り、`/api/sessions` probe を行って Go Watchdog 起動の backend を Desktop に接続させる。
- **`BackendDialClaims`** (`apps/desktop/electron/backend-dial-claim.ts:20`):
  - 同一 scope (`connectionId`, `profile`) に対する並行 dial の単一フライト集約。
- **`claimBackendChild`** (`apps/desktop/electron/main.ts:12474` / `backend-claim.ts`):
  - 自身が spawn したプロセスに対する child lifecycle 登録。
- **`watchdog-stop-fence.ts`** (`apps/desktop/electron/watchdog-stop-fence.ts`):
  - `DESKTOP_STOP` / `maintenance.json` を書き込み、Desktop 終了時に Go Watchdog の再起動を抑制する。

### 2.2 Go Watchdog (`scripts/windows/watchdog-go/`)
- **`BackendManager`** (`scripts/windows/watchdog-go/backend.go:41`):
  - Go 側での `hermes serve` の spawn、固定ポート（9119）リッスン、トークン生成、ヘルスチェック、`desktop-backend.json` への出力。
- **`Watchdog.PrewarmBackend()`** (`scripts/windows/watchdog-go/watchdog.go:96`):
  - Go Watchdog 起動時・サイクルでの backend prewarm。
- **`Watchdog.RunCycle()`** (`scripts/windows/watchdog-go/watchdog.go:216`):
  - Desktop プロセス監視とともに backend ヘルスをチェックし、連続失敗時に再起動や復旧を実行。
- **`embedding.go`** (`scripts/windows/watchdog-go/embedding.go`):
  - 埋め込みモデル（`llama-server.exe`）の独立監視・ヘルスチェック・起動。
  - loopback 限定、GGUF 検証、引数検証、自分のプロセスのみ再起動。

---

## 3. Authority Comparison Table

| 機能 / 責務 | 現状の所有者 (Before) | 本来あるべき単一所有者 (Target Architecture) |
|---|---|---|
| **Python Backend 起動 (Spawn)** | **Electron main** AND **Go Watchdog** | **Electron main ONLY** |
| **Python Backend 停止/Kill** | **Electron main** AND **Go Watchdog** | **Electron main ONLY** |
| **Python Backend 世代管理** | Electron main (不完全) / Go (PID/Manifest) | **Electron main (generation-fenced)** |
| **Manifest (`desktop-backend.json`)** | Go Watchdog が Authority として出力 | **廃止 (診断用ログ/ヒントのみ、Authority不可)** |
| **Prewarmed Local 接続** | Electron main が Watchdog backend を採用 | **完全廃止** |
| **Startup Cancellation** | なし (境界越えの競合発生) | **Electron main (`AbortSignal` + step assertion)** |
| **Embedding `llama-server`** | Go Watchdog | **Go Watchdog ONLY (完全維持)** |
| **DESKTOP_STOP / Maintenance** | Go Watchdog の再起動抑止用ファイル | **Desktop backend watchdog用としては不要/保守リース限定** |

---

## 4. Conclusion & Next Steps

現状のコードベースにおいて、Desktop/Python backend の二重管理がクラッシュ・再起動後の接続不能（stale identity 拘束）の主因であることが確認された。
次フェーズ（Phase 2 以降）において：
1. 現象を再現・検出する RED tests を作成する。
2. Electron main への完全な単一所有権化（generation-fenced, cancellation, prewarmed-local 廃止）。
3. Go Watchdog から backend supervision を撤去し、embedding llama-server 専用 supervisor として純化する。
