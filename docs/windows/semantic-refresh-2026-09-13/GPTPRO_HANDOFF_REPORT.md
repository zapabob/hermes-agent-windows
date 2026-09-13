# GPT Pro 提出用報告書
## Hermes Agent Windows — Semantic Refresh Campaign 2026-09-13

| 項目 | 値 |
|---|---|
| 報告日時 | 2026-09-13T14:46:56+09:00 |
| 実行担当 | Cursor |
| 対象リポジトリ | `zapabob/hermes-agent-windows` |
| 仕様書 | `CURSOR_HERMES_WINDOWS_SEMANTIC_REFRESH_2026-09-13.md` |
| 作業枝 | `feat/windows-semantic-refresh-2026-09-13` |
| 作業 worktree | `.worktrees/semantic-refresh-d1` |
| Candidate HEAD | `a537893877dcf67df8832a37b775df08d6f77ec3` |
| 本報告の性質 | **途中経過の正式引き継ぎ**。RELEASE_READY / PUBLISHED ではない。 |

---

## 1. 結論（1段落）

Windowsネイティブ長時間稼働ハーネスの独自契約を維持したまま、上流 `NousResearch/hermes-agent` の最新契約を**選択的に**取り込む campaign を開始した。Task 0–3（SHA凍結・CodeGraph・保護契約・採否台帳）は完了。実装は依存順の小さい slice として 2 本をローカル commit 済み（profile write-guard 全通、multiplex tool credential の一部）。push / main merge / tag / release / 本番操作は未実施。24h soak・private GHSA・packaging は NOT_RUN。版番号だけで完了宣言はしていない。

---

## 2. 凍結比較基準（exact SHA）

開始時刻 `2026-09-13T13:10:05+09:00` に一度だけ凍結。以降 upstream main が動いても今回の U は変更しない。

| 役割 | Exact SHA / 値 | 備考 |
|---|---|---|
| **D0** downstream baseline | `7c697a8a658d4ceadb80276f37b90cd93d84d6a9` | origin/main と一致。計画草稿と同じ |
| **U** upstream target | `6dd091a89c33e6e4909a80f78343bb384deb5ca8` | 草稿 `205645ee…` より **+26 commits** |
| **R** release tag | `v2026.9.11` / Hermes Agent **0.21.2** | annotated tag object `2160b2d59c…` ≠ peeled |
| **R peeled commit** | `939e45c91d751fadd94dcd1b873ac3cb44846213` | `target_commitish: main` と同一視しない |
| **H** historical snapshot | `b51c055a12220f8c7c18660e8599365012e19532` | distribution / UPSTREAM_SNAPSHOT  provenance |
| **H release commit** | `29112bef099274229cadff79cdff7bf7b99c4b77` | 歴史的 provenance（製品版の根拠ではない） |
| merge-base(D0,U) | `1fe0f2f3ac9748ce799272eb93bee2937b5ab802` | |

### 比較窓（機械的件数）

| 窓 | commits | files |
|---|---:|---:|
| H..U | 2129 | 3130 |
| R..U | 391 | 861 |

### 製品版（D0時点・未更新）

- downstream product: **0.21.1**
- historical upstream.version in distribution: **0.21.0**
- `allow_upstream_sync`: **false**（変更禁止を維持）

### 開始時 dirty（main）— 未取り込み・未破壊

- modified: `scripts/windows/watchdog-go/{backend.go,backend_test.go,watchdog.go}`
- untracked: `airi-pr2520-work/`, `quake_check.py`, `tmp_status.json`
- 方針: 隔離 worktree のみで実装。main WIP はブロッカーとして保持。

---

## 3. 作業領域と禁止事項の遵守

| 項目 | 状態 |
|---|---|
| bulk merge / rebase / 大量 cherry-pick | **未実施** |
| WSL 逃避 | **未使用** |
| 第二 supervisor / credential owner | **追加なし** |
| push / PR / main merge / tag / release / install / reboot | **未実施** |
| 本番 Desktop / Gateway / Watchdog / llama / VOICEVOX / VRChat | **未操作** |
| hakuapulse-orchestrator MoA / モデル状態 | **非接触** |
| 実 profile / secret / 実 DB をテストに使用 | **なし**（`%TEMP%\hermes-sr-test-*` のみ） |

---

## 4. CodeGraph（探索証拠のみ）

| 項目 | 値 |
|---|---|
| CLI | `.tools/codegraph-cli/.../codegraph.cmd` |
| Version | **1.6.0**（approved pin 一致。`@latest` 更新なし） |
| D1 index | 8773 files / 188304→188315 nodes（sync後） / H: junction |
| U index | 9637 files / 217260 nodes / H: junction |
| 初回障害 | C: 空き不足で `database or disk is full` → H: junction で復旧 |
| 再sync | write-guard 変更後 2 files synced。impact 再確認済 |

**注意:** CodeGraph は navigation 用。実行・テスト証跡ではない。

主要 owner 例（D1）:
- `_get_hermes_config_resolved` → `tools/file_tools.py` → callers: `_check_sensitive_path` → `write_file_tool` / `patch_tool`
- `SessionDB`, `CredentialPool`, `WinPtyBridge`, `get_hermes_home`, Watchdog Go structs

---

## 5. 保護契約（FEATURES / CARRY）

成果物: `docs/windows/semantic-refresh-2026-09-13/protected-contracts.md`

- **FEATURES.yaml**: 18/18 分類
- **CARRY.yaml**: 24/24 分類（退役なし）
- ledger の `verified` 文字 ≠ 本 campaign の実機 qualification
- semantic-graph `abstention_enabled` default **False**（HOLD 維持・勝手に昇格なし）
- 必須保護: Go Watchdog ≠ Desktop backend ≠ Gateway ≠ model/embedding 寿命分離、Browser handoff、Hypura、local llama/hot-swap、VRChat/Unity、VOICEVOX/Irodori/AITuber、prompt cache

---

## 6. 採否台帳サマリ

成果物: `docs/windows/semantic-refresh-2026-09-13/change-inventory.json`

依存順 DAG:
`B profile/credential → C storage → D handoff/lifecycle → E MCP/provider → F edge+非退行 → G packaging/version → H soak/review`

| ID | 判定 | 検証 | 内容 |
|---|---|---|---|
| SR-20260913-001 | COMPOSE | **PASS_FOCUSED** | #107327/#107335 write-guard per-call |
| SR-20260913-002 | SKIP_WITH_REASON | CLASSIFIED | POSIX 0600 state.db（nt early-return） |
| SR-20260913-003 | COMPOSE | PENDING | SessionDB registry（第二 owner 禁止） |
| SR-20260913-004 | COMPOSE | **PARTIAL_PASS** | multiplex credentials（004a 完了、残りあり） |
| SR-20260913-005 | COMPOSE | PENDING | gateway mid-turn authz |
| SR-20260913-006 | PORT | PENDING | MCP breaker / SSE |
| SR-20260913-007 | DEFER_WITH_BLOCKER | NOT_STARTED | Desktop onboarding（defaults 不変条件） |
| SR-20260913-008 | SKIP_WITH_REASON | — | Linux LC_CTYPE |
| CARRY-RECHECK | KEEP/EQUIV | PENDING_PER_ITEM | 既存 PORT の二重実装禁止 |

H..U 2129 commits の**全件個別分類は未完**。優先 path + keyword で seed。release notes 上位だけでの網羅主張はしていない。

---

## 7. 実装済み slice と exact-head 検証

### ローカル commits（D0 からの 4 commits）

```
a537893877 docs(windows): record write-guard PASS and multiplex tool-credential slice
c0446b9209 fix(multiplex): scope Modal/Browser-Use/Weixin credentials per profile
081e8d075e fix(file-tools): resolve write-guard home/config per active profile
ac48f6fa45 docs(windows): freeze semantic-refresh 2026-09-13 baseline and adoption ledger
```

Candidate HEAD: **`a537893877dcf67df8832a37b775df08d6f77ec3`**

### Slice A — SR-20260913-001（write-guard）

| 項目 | 内容 |
|---|---|
| 意図した差分 | process-global memo をやめ、active profile の home/config を per-call 解決。例外 fallback も `get_hermes_home()` に拘束 |
| Owner | `tools/file_tools.py`（upstream の module 分割は採用せず COMPOSE） |
| Test | `TestMultiplexProfileCacheGuardsAreProfileScoped` |
| Receipt | `pytest …::TestMultiplexProfileCacheGuardsAreProfileScoped -q` → **5 passed** |
| HOME | isolated `%TEMP%\hermes-sr-test-*` |
| OS | Windows 11 |

### Slice B — SR-20260913-004a（tool credential 部分集合）

| 項目 | 内容 |
|---|---|
| 意図した差分 | Modal / Browser-Use / Weixin home が default profile の `os.environ` を継承しない |
| Owners | `tool_backend_helpers.has_direct_modal_credentials`, `browser_use_cli.is_legacy_browser_use_cloud_config`, `send_message_tool._weixin_home_channel_override` |
| Test | `tests/tools/test_multiplex_tool_credential_scope.py` |
| Receipt | 当該 2 + write-guard 5 → **7 passed** |
| 残り（004） | memory tenant/env、aux base URL、agent-cache thread context、MCP same-name、FIRECRAWL hosted OCR（本 fork に該当経路なし） |

### 既存 Windows 失敗（今回差分と無関係・PASS に算入しない）

- `TestAtomicWrite::test_patch_routes_through_atomic_write` — POSIX `0o600` 期待
- `TestProtectedInstructionFiles::test_symlink_to_protected_file_is_gated` — WinError 1314（symlink 特権）

---

## 8. 完了ゲート（分割状態）

| Gate | 状態 |
|---|---|
| Task 0–3 baseline / ledger | **COMPLETE** |
| SOURCE_IMPLEMENTATION_COMPLETE | **false**（部分 slice のみ） |
| SEMANTIC_SCOPE_VERIFIED | **false** |
| WINDOWS_NATIVE_VERIFIED | **false** |
| PRIVATE_SECURITY_VERIFIED | **false** / UNVERIFIED_PRIVATE_CONTRACT |
| LONG_RUNNING_VERIFIED | **false** / 24h soak NOT_RUN |
| PACKAGING_VERIFIED | **false** |
| RELEASE_READY | **false** |
| PUBLISHED | **false**（許可範囲外） |

製品 SemVer / upstream semantic target / historical provenance は**別管理**。番号だけ上げて全面互換と宣言しない。

---

## 9. 版整合（現状）

| 層 | 現状 | 本 campaign |
|---|---|---|
| downstream product | 0.21.1 | 未更新 |
| upstream semantic target（宣言候補） | 0.21.2 + U=`6dd091a89c…` | coverage は manifest 定義・除外開示が必要。未完了 |
| historical provenance | 0.21.0 / H=`b51c055…` | **上書き禁止**（採用証明なし） |

---

## 10. Rollback

詳細: `docs/windows/semantic-refresh-2026-09-13/rollback.md`

```powershell
cd ".worktrees/semantic-refresh-d1"
git log --oneline -10
git revert --no-edit <slice-commit-sha>   # 例: 081e8d075e / c0446b9209
```

- main の dirty に `reset --hard` しない
- 本番 HERMES_HOME / secrets / live DB は未変更
- テスト TEMP HOME は削除可

---

## 11. GPT Pro への次アクション（推奨順）

1. **SR-20260913-004 残り**（memory provider identity/tenant、aux URL、agent-cache `copy_context`、MCP same-name）を owner 単位の小 slice で COMPOSE。同一 SessionDB/credential/lockfile を複数 agent が同時編集しない。
2. **SR-20260913-003** storage registry — 第二 DB owner 禁止。既存 connection registry へ合成。
3. **SR-20260913-005** gateway mid-turn authz / routed profile policy。
4. CARRY PORT 群の **ALREADY_EQUIVALENT** 再確認（ConPTY、WS deadline、OAuth UI、aux origin 等）— 二重実装禁止。
5. 専用 test install で Windows-native 回帰拡大。本番 claim / port / mutex に戻らないこと。
6. 24h soak / private security / packaging は別ゲート。未実行を PASS にしない。
7. **push/PR は別承認後のみ。**

### 再開時の最短コンテキスト

```text
Worktree: .worktrees/semantic-refresh-d1
Branch:   feat/windows-semantic-refresh-2026-09-13
HEAD:     a537893877dcf67df8832a37b775df08d6f77ec3
D0:       7c697a8a658d4ceadb80276f37b90cd93d84d6a9
U:        6dd091a89c33e6e4909a80f78343bb384deb5ca8
Ledger:   docs/windows/semantic-refresh-2026-09-13/
Next:     SR-20260913-004 remaining (memory/MCP/aux), then 003 storage
```

全文再読や全 repo 検索は不要。該当節・owner・diff・test 単位で進めること。

---

## 12. 添付・参照パス（campaign 成果物）

```
docs/windows/semantic-refresh-2026-09-13/baseline.json
docs/windows/semantic-refresh-2026-09-13/owner-map.md
docs/windows/semantic-refresh-2026-09-13/protected-contracts.md
docs/windows/semantic-refresh-2026-09-13/change-inventory.json
docs/windows/semantic-refresh-2026-09-13/decisions.md
docs/windows/semantic-refresh-2026-09-13/rollback.md
docs/windows/semantic-refresh-2026-09-13/verification-summary.json
_docs/2026-09-13_windows-semantic-refresh_Cursor.md   # worktree local; often gitignored
tmp/probes/semantic-refresh-2026-09-13/               # machine-local raw probes
H:\hermes-codegraph\semantic-refresh-2026-09-13\      # CodeGraph indexes (junction targets)
```

---

## 13. クレジット（実装に取り込んだ上流）

- PRATHAMESH75 — `#107327` / `#107335` write-guard（1271622 / 7af5006）
- Teknium et al. — multiplex tool/memory env（a9838c）の **部分集合のみ** COMPOSE

---

**本報告書は「部分実装＋検証済み契約の引き継ぎ」であり、上流全機能同一・長時間稼働合格・リリース準備完了を意味しない。**
