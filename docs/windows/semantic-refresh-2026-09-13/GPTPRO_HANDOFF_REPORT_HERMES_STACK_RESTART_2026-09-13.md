# GPT Pro Handoff Report — Hermes Full-Stack Restart (Windows)

| 項目 | 値 |
|---|---|
| 報告日時 | 2026-09-14T00:56+09:00（最終検証反映） |
| 実行担当 | Cursor（continuation / System32 footgun recovery） |
| 対象リポジトリ | `c:\Users\downl\Documents\New project\hermes-agent` |
| Canonical Desktop | `apps\desktop\release\win-unpacked\Hermes.exe` |
| 作業開始 HEAD | `dd481b75f561b5635b1c38ee845b9c7224b96324` |
| 最終観測 HEAD | `b8c3a13727350cd32e50b18cb7ff1246dc132801`（本ターンは commit していない） |
| 本報告の性質 | **ローカルフルスタック再起動の正式引き継ぎ**。MAIN_PUSHED / RELEASE ではない。 |

---

## 1. Purpose / Operator request

オペレータ依頼:

1. GPT Pro 向けハンドオフ報告書を作成・更新する。
2. System32 cwd からの相対パス失敗を正し、Go watchdog を ForceRestart する。
3. 未完了スタック再起動（Desktop build / llama / Desktop launch / verify）を続ける。

制約（厳守）:

- force-push / HOLD unlock / MoA・model swap / public Release tag **禁止**
- `.worktrees/` から Desktop を起動しない
- `HERMES_DESKTOP_HERMES_ROOT` は Documents の canonical root のみ
- commit はユーザー未依頼のため **未実施**

---

## 2. Frozen SHAs reminder（変更禁止）

Campaign 開始時刻 `2026-09-13T13:10:05+09:00` に一度だけ凍結。**U を再ターゲットしない。** `allow_upstream_sync: false` 維持。

| 役割 | Exact SHA / 値 |
|---|---|
| **D0** | `7c697a8a658d4ceadb80276f37b90cd93d84d6a9` |
| **U** | `6dd091a89c33e6e4909a80f78343bb384deb5ca8` |
| **R** | `v2026.9.11` / product **0.21.2**（annotated `2160b2d59c…` ≠ peeled） |
| **R peeled** | `939e45c91d751fadd94dcd1b873ac3cb44846213` |
| **H** snapshot | `b51c055a12220f8c7c18660e8599365012e19532` |
| **H** release commit | `29112bef099274229cadff79cdff7bf7b99c4b77` |
| merge-base(D0,U) | `1fe0f2f3ac9748ce799272eb93bee2937b5ab802` |

根拠: `docs/windows/semantic-refresh-2026-09-13/baseline.json`

本再起動作業は **凍結比較基準を動かさない**。ローカル稼働プロセスの再束ね直しのみ。

---

## 3. Operator footgun — System32 relative `-File` path（必須注意）

オペレータが **昇格 PowerShell** で次を **逆順 / cwd=System32** で実行した:

```powershell
# BAD — cwd が C:\WINDOWS\system32 のまま相対パス
powershell -NoProfile -ExecutionPolicy Bypass -File ".\scripts\windows\Start-HermesGoWatchdog.ps1" -ForceRestart -ManagedBackendPort 9119
cd "C:\Users\downl\Documents\New project\hermes-agent"
taskkill /PID 4776 /T /F
taskkill /PID 2208 /T /F
```

| 観測 | 結果 |
|---|---|
| Error | `-File` path `.\scripts\windows\Start-HermesGoWatchdog.ps1` **does not exist**（解決先は `C:\WINDOWS\system32\scripts\...`） |
| PIDs 4776 / 2208 | 既に不在（taskkill は空振り） |
| 教訓 | **必ず先に `cd` するか、絶対パスで `-File` を指定する。taskkill は後。** |

### Correct command order（推奨）

**A. 非昇格シェルから UAC 自己昇格 helper（推奨）:**

```powershell
$root = "C:\Users\downl\Documents\New project\hermes-agent"
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "$root\tmp\probes\hermes-stack-restart-elevated.ps1" `
  -HermesRoot $root `
  -ManagedBackendPort 9119 `
  -ReceiptPath "$root\tmp\probes\hermes-stack-restart-elevated-receipt.json"
# UAC Yes → receipt の ok / health を確認（親 -Wait ハング時は receipt を権威に）
```

**B. 既に昇格している場合の絶対パス ForceRestart:**

```powershell
cd "C:\Users\downl\Documents\New project\hermes-agent"
powershell -NoProfile -ExecutionPolicy Bypass -File "C:\Users\downl\Documents\New project\hermes-agent\scripts\windows\Start-HermesGoWatchdog.ps1" `
  -ForceRestart -ManagedBackendPort 9119 `
  -HermesRoot "C:\Users\downl\Documents\New project\hermes-agent"
```

順序の鉄則: **`cd` または絶対パス → ForceRestart →（必要なら）taskkill / Desktop stop → health 確認**。System32 から相対 `-File` を叩かない。

---

## 4. Failure class — why UAC was required

| 現象 | 説明 |
|---|---|
| Unelevated stop | 非昇格シェルから Desktop / Go watchdog を ForceRestart できない |
| Required action | Elevated: packaged Desktop 停止 + `Start-HermesGoWatchdog.ps1 -ForceRestart -ManagedBackendPort 9119` |
| Helper | `tmp\probes\hermes-stack-restart-elevated.ps1` |
| Receipts | `…-receipt.json`（初回） / `…-receipt-20260913-2257.json`（本ターン System32 復旧） / `…-r2.json`（中間復旧） |

---

## 5. Planned restart sequence

1. **Elevated**: stop packaged Desktop + Go watchdog ForceRestart `:9119`
2. `hermes desktop --build-only --force-build`
3. `scripts\windows\start-llama-hotswap.ps1 -ForceRestart -WarmSecondary`
4. Launch Desktop via `scripts\windows\start-hermes-desktop.ps1`
5. Verify matrix: `8080` / `9119` / `9920` + manifest + `Hermes.exe` path

---

## 6. Status flags（proven only）

| Flag | 状態 | 根拠 |
|---|---|---|
| **MAIN_PUSHED** | **NOT_CLAIMED** | push なし |
| **LOCAL_DEPLOYED** | **PARTIAL_PASS** | health 8080/9119/9920 PASS + canonical Desktop 稼働。Desktop **force-build FAIL**（旧 EXE 17:28 のまま） |
| **soak (24h)** | **NOT_RUN** | 対象外 |
| **allow_upstream_sync** | **false** | 凍結維持 |
| **HOLD unlock** | **NOT_DONE** | 禁止事項遵守 |

---

## 7. Risks / residual

| リスク | 詳細 |
|---|---|
| Desktop rebuild 未完了 | `PARSE_ERROR Unterminated string` in corrupted `@shikijs/langs` `emacs-lisp.mjs`（null bytes）。旧 EXE 稼働 |
| System32 relative path | 昇格プロンプト既定 cwd が System32 → 相対 `-File` が即死 |
| UAC parent hang | `Start-Process -Verb RunAs -Wait` が子完了後も親に戻らない → receipt を権威に |
| Disk free ~15.6 GB | force-build 再試行で逼迫しうる |
| Session0 / elevated watchdog | 昇格 watchdog とユーザー Desktop の境界 |
| HEAD drift | 開始 `dd481b75` → 観測 `b8c3a137`（他作業の可能性；本ターン未 commit） |
| Desktop attach verify warn | `start-hermes-desktop.ps1` が「exited during attach verify」を出しても、後続で canonical Hermes.exe が稼働する事例あり |

---

## 8. Actual outcomes（証拠付き）

### Step 1 — Elevated Desktop stop + Go watchdog ForceRestart

| 項目 | 結果 |
|---|---|
| Status | **PASS** |
| Method | `tmp\probes\hermes-stack-restart-elevated.ps1`（UAC Yes） |
| Receipt | `tmp\probes\hermes-stack-restart-elevated-receipt-20260913-2257.json` |
| Receipt fields | `ok=true`, `watchdogExit=0`, `finishedAt=2026-09-13T23:02:31+09:00` |
| Health in receipt | llama 200 / backend 200 / watchdog 200 |
| `stoppedDesktop` | `[]`（当時 packaged Hermes.exe なし） |

### Step 2 — `hermes desktop --build-only --force-build`

| 項目 | 結果 |
|---|---|
| Status | **FAIL** |
| Attempts | (1) ENOTEMPTY `node_modules\lodash-es` → exit `-1`；(2) lodash-es 削除後リトライ → exit `1` |
| Root cause (attempt 2) | Rolldown `[PARSE_ERROR] Unterminated string` at `node_modules/@streamdown/code/node_modules/@shikijs/langs/dist/emacs-lisp.mjs`（ファイル破損 / null bytes） |
| Env | `HERMES_DESKTOP_HERMES_ROOT=c:\Users\downl\Documents\New project\hermes-agent` |
| Artifact | 既存 EXE 残存（LastWriteTime **2026-09-13 17:28:11**, 223813120 bytes） |
| Note | `@shikijs/langs` 再インストールは Auto-review により未実施 → 次作業で承認後に修復 |

### Step 3 — llama hotswap ForceRestart WarmSecondary

| 項目 | 結果 |
|---|---|
| Status | **PASS** |
| Evidence | log `tmp\probes\llama-hotswap-20260913-2345.log`: `llama.cpp hot-swap ready`；primary `qwen3.8-27b-abliterated-mtp=loaded` |
| Live PID（最終） | `llama-server` pid=`2480`（StartTime `2026-09-14 0:42:17`）ほかワーカーあり |
| Note | 親 wrapper がログ完了後もハング → llama-server は維持したまま wrapper のみ停止 |

### Step 4 — Desktop launch (`start-hermes-desktop.ps1`)

| 項目 | 結果 |
|---|---|
| Status | **PASS**（canonical path で稼働） |
| Launch | `started pid=21872` → attach verify WARNING（code=0 / no port-0 serve within 40s） |
| Live | canonical `...\win-unpacked\Hermes.exe` が複数 PID で稼働（例: 19024 / 4700 / 12440） |
| Root | Documents canonical only（**not** `.worktrees/`） |

### Step 5 — Final verification matrix（2026-09-14 ~00:56+09）

証跡 JSON: `tmp\probes\stack-verify-matrix-clean-20260914.json`

| Probe | Status | Evidence |
|---|---|---|
| `:8080/health` | **PASS** | 200 `{"status":"ok"}` |
| `:9119/api/health` | **PASS** | 200 `{"ok":true,"version":"0.21.2","auth_required":false}` |
| `:9920/health` | **PASS** | 200 `{"status":"ok"}` |
| Manifest | **PASS** | `%LOCALAPPDATA%\HermesWatchdog\desktop-backend.json`；`hermesRoot`=Documents；`managed=true`；`port=9119`；`pid=7532`；`updatedAt=2026-09-14T00:41:22+09:00` |
| `hermes-watchdog` | **PASS** | pid=`3636` StartTime `2026-09-14T00:40:39+09:00` |
| `Hermes.exe` path | **PASS** | canonical `win-unpacked`（**rebuild FAIL のためバイナリ世代は 17:28 のまま**） |

---

## 9. Exact re-run commands（operator / GPT Pro）

```powershell
$root = "C:\Users\downl\Documents\New project\hermes-agent"
Set-Location $root   # NEVER run relative -File from C:\WINDOWS\system32

# 1) Elevated unlock + watchdog (UAC Yes) — preferred
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "$root\tmp\probes\hermes-stack-restart-elevated.ps1" `
  -HermesRoot $root `
  -ManagedBackendPort 9119 `
  -ReceiptPath "$root\tmp\probes\hermes-stack-restart-elevated-receipt.json"

# 1b) Already elevated — absolute path only
powershell -NoProfile -ExecutionPolicy Bypass -File "$root\scripts\windows\Start-HermesGoWatchdog.ps1" `
  -ForceRestart -ManagedBackendPort 9119 -HermesRoot $root

# 2) Desktop rebuild (blocked until @shikijs/langs repaired)
$env:HERMES_DESKTOP_HERMES_ROOT = $root
hermes desktop --build-only --force-build

# 3) Local llama hot-swap
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "$root\scripts\windows\start-llama-hotswap.ps1" `
  -ForceRestart -WarmSecondary

# 4) Launch packaged Desktop (never from .worktrees)
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "$root\scripts\windows\start-hermes-desktop.ps1"

# 5) Verify
Invoke-WebRequest http://127.0.0.1:8080/health -UseBasicParsing
Invoke-WebRequest http://127.0.0.1:9119/api/health -UseBasicParsing
Invoke-WebRequest http://127.0.0.1:9920/health -UseBasicParsing
Get-Content "$env:LOCALAPPDATA\HermesWatchdog\desktop-backend.json"
Get-CimInstance Win32_Process -Filter "Name='Hermes.exe'" | Select ProcessId, ExecutablePath
```

---

## 10. Script pointers

| Script | Role |
|---|---|
| `tmp\probes\hermes-stack-restart-elevated.ps1` | One-shot UAC elevate: stop Desktop + ForceRestart Go watchdog |
| `scripts\windows\Start-HermesGoWatchdog.ps1` | Go watchdog（`-ForceRestart -ManagedBackendPort 9119`） |
| `scripts\windows\start-llama-hotswap.ps1` | Local llama primary/secondary hot-swap |
| `scripts\windows\start-hermes-desktop.ps1` | Canonical packaged Desktop launcher |
| Receipts | `tmp\probes\hermes-stack-restart-elevated-receipt*.json` |
| Verify matrix | `tmp\probes\stack-verify-matrix-clean-20260914.json` |
| Impl log | `_docs/2026-09-13_hermes-stack-restart_Cursor.md` |

---

## 11. Related campaign docs

- `docs/windows/semantic-refresh-2026-09-13/GPTPRO_HANDOFF_REPORT.md`（campaign 本体）
- `docs/windows/semantic-refresh-2026-09-13/baseline.json`（凍結 SHA）
- `docs/windows/semantic-refresh-2026-09-13/protected-contracts.md`

---

## 12. Closing note for GPT Pro

- **稼働面（8080/9119/9920 + canonical Desktop + manifest）は最終検証 PASS。**
- **Desktop force-build は FAIL** — LOCAL_DEPLOYED は PARTIAL。旧 EXE（17:28）で運転中。
- **System32 相対パス足撃ち**を本報告 §3 に固定。正しい順序は helper または絶対 `-File`。
- Semantic refresh の SOURCE/RELEASE、upstream retarget、main push、soak 完了は **主張しない**。
- 次作業候補: 破損 `@shikijs/langs`（`emacs-lisp.mjs`）の限定修復 → `hermes desktop --build-only --force-build` 再試行。
