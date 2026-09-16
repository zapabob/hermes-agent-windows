# Windows-native Single-Owner Desktop Backend Lifecycle 再構築 監査ログ

- **Date**: 2026-09-16
- **Feature**: `windows-desktop-single-owner-backend`
- **Implementer**: Antigravity / Gemini 3.8 Flash
- **Target Repo**: `zapabob/hermes-agent-windows`
- **Baseline Commit**: `97ff5b6249e4b0d968a1b6bb6f6c69fc2f0ed487`
- **Branch**: `fix/windows-single-owner-backend`

---

## 1. Before Architecture vs. After Architecture

### 1.1 Before Architecture (二重 Authority による障害状態)

```text
                     Dual Authority (Before)

Electron main ───────────────┐
  - startHermes()            ├──> Python Backend (`hermes serve`)
  - backendConnectionState   │    (PIDs/ports/tokens collide, race conditions)
                             │
Go Watchdog ─────────────────┘
  - BackendManager.EnsureHealthy()
  - desktop-backend.json
  - PrewarmBackend() / recovery loop
```

- **問題点**:
  - Go Watchdog が `desktop-backend.json` を書き出し、Desktop は `resolvePrewarmedLocal` 経由でそれを採用。
  - Desktop 側にプロセスハンドルが存在しないため、クラッシュ・再起動時に古い PID やポートが孤立。
  - Desktop 再起動時、Generation A の遅延した解決が Generation B の状態を上書き・切断。
  - 状態復旧の試みがさらなる競合を生み、再疎通不能に陥っていた。

---

### 1.2 After Architecture (明確な所有権分離)

```text
                     Single Owner Architecture (Target / Implemented)

Electron Desktop main
   │
   └─ Desktop/Python backend lifecycle (SOLE AUTHORITY)
       ├─ generation-fenced ownership
       ├─ startup cancellation (`AbortSignal` + `runBackendStartStep`)
       ├─ current-process ChildProcess handle ownership
       ├─ single in-flight dial deduplication (`BackendDialClaims`)
       ├─ crash loop guard & bounded recovery
       └─ renderer rebind via authenticated `/api/ws` probe

Go auxiliary supervisor
   │
   └─ Embedding llama-server (SOLE AUTHORITY)
       ├─ GGUF model loading & loopback endpoint (e.g. :8082)
       ├─ `/health` monitoring & probe
       ├─ owned-process restart only (PID-verified)
       └─ foreign occupant preservation (no blind kill)
```

---

## 2. Why Go Desktop Supervision Was Retired & Why Embedding Supervision Remains

### 2.1 Why Go Desktop Backend Supervision Was Retired
1. **二重管理の原理的破綻**:
   Electron main と Go Watchdog という異なるランタイム・異なるメモリ空間のプロセスが、同一の Python backend プロセスを独立して起動・監視・終了しようとすると、どちらの generation が最新かを保証できず、常に競合（race condition）が発生する。
2. **所有権の喪失**:
   Go Watchdog が起動したプロセスを Desktop がファイル経由（`desktop-backend.json`）で引き受けると、Desktop はネイティブの ChildProcess ハンドルを持たないため、適切な終了やシグナル伝達が不可能になる。
3. **安全なシャットダウンの阻害**:
   Electron main が Single Owner となることで、自身のメモリ内で generation をインクリメントし、古い attempt を abort し、保持している ChildProcess のみを安全に終了・再起動できるようになった。

### 2.2 Why Go Embedding Supervision Remains
1. **完全な責務分離**:
   埋め込みモデル（Embedding llama-server）は Desktop UI やセッション状態から完全に独立したローカルの共有インフラである。
2. **既存の安全性インバリアント**:
   `embedding.go` はすでに loopback 限定、GGUF パス検証、引数検証、healthy 外部エンドポイントの保護、未所有ポート占有者の保護など、極めて堅牢なセキュリティ境界が確立されている。
3. **無停止・ホットスタンバイ**:
   Desktop の再起動やクラッシュに巻き込まれず、バックグラウンドで安定してベクトル埋め込み API（`/v1/embeddings`）を提供し続けることが最適である。

---

## 3. Authority Matrix

| 責務 | Electron Desktop Main | Go Auxiliary Supervisor | 備考 |
|---|---|---|---|
| **Python Backend 起動 (Spawn)** | **YES (Sole Owner)** | **NO** | `prewarmed-local` 廃止 |
| **Python Backend 停止/Kill** | **YES (Sole Owner)** | **NO** | 保持した `ChildProcess` のみ |
| **Python Backend 世代管理** | **YES (`generation`)** | **NO** | 世代不一致の操作を即座に破棄 |
| **Startup Cancellation** | **YES (`AbortSignal`)** | **NO** | 遅延した起動結果の反映を遮断 |
| **Manifest (`desktop-backend.json`)** | **NO (Not used)** | **NO (Not authoritative)**| 永続ファイルを Authority にしない |
| **Embedding Server 起動・監視** | **NO** | **YES (Sole Owner)** | loopback `:8082`, `/health` |
| **Embedding Server 停止・再起動** | **NO** | **YES (Owned only)** | 自分が起動したプロセスのみ再起動 |

---

## 4. RED Repro & Verification Tests

### 4.1 Implemented Test Suites
1. **`apps/desktop/electron/single-owner-backend-lifecycle.test.ts`**:
   - `7.1`: stale `desktop-backend.json` があっても Desktop がそれを authoritative として採用しないこと。
   - `7.2`: Generation A の起動完了が遅れても Generation B の状態を上書き・クリアしないこと。
   - `7.3`: 複数ウィンドウが同時に再接続を要求しても 1 回の dial / spawn に集約されること (`BackendDialClaims`)。
   - `7.4`: backend クラッシュ時に exactly one の代替 backend が spawn されること。
   - `7.5`: 同一 `HERMES_HOME` であれば起動元パスが違っても同一 lifecycle identity を保持すること。
   - `7.6`: MSYS path (`/c/Users/...`) と native Windows path (`C:\Users\...`) が同一 native lifecycle identity に正規化されること。
   - `Phase 26 (Desktop side)`: Desktop が embedding サーバーの PID を adopt したり terminate しないこと。
2. **`apps/desktop/electron/backend-start-cancellation.ts` & `primary-backend-cancellation.test.ts`**:
   - `runBackendStartStep`: キャンセル時に即座に中断し、後続処理を起動しないこと。
3. **`apps/desktop/electron/primary-backend-startup.test.ts`**:
   - `prewarmed-local` 依存のテストを撤去し、単一所有権フロー（remote / local）のみを検証。
4. **`apps/desktop/electron/backend-connection-state.test.ts`**:
   - `pendingPromise`, `getPendingPromise()`, generation-aware auto-cleanup を検証。
5. **`apps/desktop/electron/watchdog-backend.test.ts`**:
   - `main.ts` が `resolveWatchdogPrewarmedBackend` を一切使用していないことを検証。
6. **`scripts/windows/watchdog-go/authority_test.go`**:
   - `TestWatchdogDefaultDisablesDesktopBackendPrewarm`
   - `TestEmbeddingSupervisorDoesNotSpawnOrKillDesktopBackend`
7. **`scripts/windows/watchdog-go/embedding_test.go`**:
   - 既存の埋め込みモデル管理テスト全件が継続して PASS。

---

## 5. Summary of Code Changes

1. **`apps/desktop/electron/backend-connection-state.ts`**:
   - `pendingPromise` の追跡および settle 時の generation 整合性確認に基づく自動クリアを追加。
2. **`apps/desktop/electron/backend-start-cancellation.ts`**:
   - `runBackendStartStep(signal, run)` による非同期ステップキャンセル境界を確立。
3. **`apps/desktop/electron/primary-backend-startup.ts`**:
   - `signal?: AbortSignal` を受領し、全ステップを `step()` でラップ。
   - `resolvePrewarmedLocal` / `kind: 'prewarmed-local'` を完全削除。
4. **`apps/desktop/electron/main.ts`**:
   - `resolveWatchdogPrewarmedBackend` の import と呼び出しを削除。
   - `runPrimaryBackendStartup` から `resolvePrewarmedLocal` を削除。
   - `setup.kind === 'prewarmed-local'` の分岐を削除。
5. **`scripts/windows/watchdog-go/main.go`**:
   - `prewarm-backend` のデフォルトを `false` に変更。
6. **`scripts/windows/watchdog-go/watchdog.go`**:
   - `PrewarmBackend` フラグが false の場合、Desktop backend の spawn・再起動・orphan kill を一切行わないようガード。
   - 責務を embedding llama-server のヘルス管理に純化。
7. **`FEATURES.yaml` & `CARRY.yaml`**:
   - `watchdog-managed-desktop-backend` を `status: retired` に更新。
   - `windows-desktop-single-owner-backend` を `status: verified` で登録。
   - upstream provenance および Windows-native インバリアントを明記。

---

## 6. Known Remaining Risks & Operational Guidance

- **Windows Reboot / Cold Start**:
  - Windows 再起動後、Go Watchdog サービスが起動しても Desktop backend のポートやトークンを予約・占有しないため、Desktop は常にクリーンな状態で起動できる。
- **Crash Recovery**:
  - Desktop backend がクラッシュした場合、Electron main の `hermesProcess.once('exit')` ハンドラと `backendConnectionState` が唯一の復旧者として動作し、世代を更新して単一の代替プロセスを起動する。
- **Job Object Teardown**:
  - Desktop が終了する際は、保持している `ChildProcess` ハンドルに対して `stopBackendChild` を通じてシグナル伝達・終了待機を行うため、`taskkill` 等による無差別キルの危険性はない。
