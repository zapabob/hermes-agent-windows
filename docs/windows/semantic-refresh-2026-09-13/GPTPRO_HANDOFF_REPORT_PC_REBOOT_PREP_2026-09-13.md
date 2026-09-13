# GPT Pro Handoff — PC Reboot Prep (Windows)

| 項目 | 値 |
|---|---|
| 報告日時 | 2026-09-13 23:15 JST 前後 |
| 実行担当 | Cursor（reboot-prep subagent） |
| 対象リポジトリ | `C:\Users\downl\Documents\New project\hermes-agent` |
| HEAD | `b8c3a13727350cd32e50b18cb7ff1246dc132801` |
| C: free | ~15.19 GB |
| Manifest | `%LOCALAPPDATA%\HermesWatchdog\desktop-backend.json`（port 9119 / managed; token は本報告に載せない） |
| Stop receipt | `tmp\probes\pc-reboot-prep-stop-receipt.json` |
| 判定 | **再起動してOK** |

---

## 1. Purpose

オペレータ依頼「PC再起動するわ準備して」。再起動直前に Hermes スタックを graceful stop し、オートスタート可否と再起動後チェックリストを残す。長時間 Desktop rebuild / ForceRestart は **実施しない**。

---

## 2. Pre-stop health（停止直前）

| ポート / 対象 | 状態 |
|---|---|
| `:8080` llama-server | LISTENING（hotswap / turboquant） |
| `:9119` managed backend | LISTENING |
| `:9920` Go watchdog | LISTENING |
| `:8787` hermes-WebUI | LISTENING（停止対象外・ノートのみ） |
| `:9120` python | LISTENING（停止対象外・ノートのみ） |
| Packaged `win-unpacked\Hermes.exe` | **未起動** |
| 残存 `hermes desktop --build-only --force-build` | PID 36604 / 33048（中断対象） |

---

## 3. What was stopped

| 対象 | 結果 |
|---|---|
| Stuck `desktop --build-only --force-build` | **STOPPED**（36604, 33048） |
| Packaged Desktop | N/A（未起動） |
| Go watchdog (`Start-HermesGoWatchdog.ps1 -Stop` elevated) | **STOPPED**（`:9920` DOWN） |
| Managed backend `:9119` | **STOPPED** |
| Llama hotswap `:8080` + llama-server | **STOPPED**（elevated 含む；`:8080` DOWN） |
| GPU llama occupancy | 停止後 `nvidia-smi` に llama なし（hung 兆候なし） |
| `:8787` / `:9120` | **残置**（messaging / WebUI；再起動で自然消滅） |

Stop helper: `tmp\probes\pc-reboot-prep-stop.ps1`  
Receipt verify: `port_8080/9119/9920 = DOWN`

---

## 4. Cancelled / incomplete prior restart work

先の elevated full-stack restart（`GPTPRO_HANDOFF_REPORT_HERMES_STACK_RESTART_2026-09-13.md`）は **PC 再起動優先で中断**。

| Flag | 状態 |
|---|---|
| **LOCAL_DEPLOYED** | **INCOMPLETE / CANCELLED_FOR_REBOOT** |
| Desktop `--force-build` | 途中プロセスを kill（再起動後に必要ならやり直し） |
| ForceRestart soak | **NOT_CLAIMED** |

---

## 5. Autostart — what comes back alone

### Task Scheduler（Ready = 自動起動候補）

| Task | State | RunLevel | 再起動後 |
|---|---|---|---|
| `HermesGoWatchdogBootAutoStart` | Ready | **Highest** | Watchdog + managed backend `:9119` が起動する想定 |
| `HermesGoWatchdogLogonAutoStart` | Ready | **Highest** | 同上（ログオン時二重起動に注意；既存設計） |
| `HermesDesktopAutoStart` | Ready | Limited | Desktop（canonical root） |
| `HermesGatewayBootAutoStart` | Ready | Highest | Messaging gateway |
| `HermesWebUIBootAutoStart` | Ready | Highest | WebUI `:8787` |
| `HermesDashboardBootAutoStart` | Ready | Highest | Dashboard |
| `HermesMemoryGraphBootAutoStart` | Ready | Highest | Memory graph |
| `HermesLlamaLogonAutoStart` | **Disabled** | Limited | **自動起動しない** → 手動必須 |
| `HermesFullStackAutoStart` | **MISSING** | — | `Register-HermesFullAutostart.ps1` 未登録 |

### Startup フォルダ（ログオン）

- `Hermes Desktop.lnk` → `start-hermes-desktop.ps1`（canonical Documents root）
- `Hermes_Gateway*.vbs`（複数プロファイル）
- `Hermes-A2A-Launcher.lnk` → `hermes-stack-restart.ps1 -A2A`

### 手動が必要

1. **Llama hotswap `:8080`**（タスク Disabled）
2. Watchdog が UAC / Highest 失敗した場合の elevated 再起動
3. Desktop が二重起動したら片方を閉じる

---

## 6. Post-reboot checklist（絶対パス）

```powershell
cd "C:\Users\downl\Documents\New project\hermes-agent"

# 1) Llama（必須・手動）
powershell -NoProfile -ExecutionPolicy Bypass -File "C:\Users\downl\Documents\New project\hermes-agent\scripts\windows\start-llama-hotswap.ps1" -ForceRestart -WarmSecondary

# 2) Go watchdog が起きていなければ（UAC Yes / elevated）
powershell -NoProfile -ExecutionPolicy Bypass -File "C:\Users\downl\Documents\New project\hermes-agent\scripts\windows\Start-HermesGoWatchdog.ps1" -HermesRoot "C:\Users\downl\Documents\New project\hermes-agent" -HermesHome "C:\Users\downl\.hermes" -ManagedBackendPort 9119

# 3) Desktop（未起動なら）
powershell -NoProfile -ExecutionPolicy Bypass -File "C:\Users\downl\Documents\New project\hermes-agent\scripts\windows\start-hermes-desktop.ps1" -HermesRoot "C:\Users\downl\Documents\New project\hermes-agent" -Cwd "C:\Users\downl\Documents\New project\hermes-agent" -HermesHome "C:\Users\downl\.hermes"

# 4) Verify
# http://127.0.0.1:8080/health
# http://127.0.0.1:9119/api/health
# http://127.0.0.1:9920/health
# Manifest: %LOCALAPPDATA%\HermesWatchdog\desktop-backend.json
```

禁止: `.worktrees/` から Desktop 起動 / force-push / HOLD unlock / MoA。

---

## 7. Signal

**再起動してOK。** コア（8080 / 9119 / 9920 / build-only）は停止済み。8787/9120 は残置だが再起動で消える。
