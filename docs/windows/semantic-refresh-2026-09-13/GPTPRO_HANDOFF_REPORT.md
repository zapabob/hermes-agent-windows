# GPT Pro 提出用報告書（第二版）
## Hermes Agent Windows — Semantic Refresh Campaign 2026-09-13

| 項目 | 値 |
|---|---|
| 報告版 | **v2**（第一版 `2026-09-13T14:46:56+09:00` / HEAD `a537893…` を置換） |
| 報告日時 | 2026-09-13T15:23:29+09:00 |
| 実行担当 | Cursor |
| 対象リポジトリ | `zapabob/hermes-agent-windows` |
| 仕様書 | `CURSOR_HERMES_WINDOWS_SEMANTIC_REFRESH_2026-09-13.md` |
| 再開指示 | 本文指示（Downloads の `CURSOR_RESUME_…` は未着；checkpoint 本文で継続） |
| 作業枝 | `feat/windows-semantic-refresh-2026-09-13` |
| 作業 worktree | `.worktrees/semantic-refresh-d1` |
| Candidate HEAD | **`89b2004b4bea5fa3b8ab365097533b8cccd5f9ed`** |
| 本報告の性質 | **実行差分の正式引き継ぎ**。報告書としての完成。**SOURCE 完了 / RELEASE_READY / PUBLISHED ではない。** |

---

## 0. 第一版からの差分サマリ（GPT Pro が先に読む節）

| 項目 | 第一版 (v1) | 本版 (v2) |
|---|---|---|
| Candidate HEAD | `a537893877…` | **`89b2004b4b…`** |
| 再開 | 未実施 | `a537893` を ancestor として確認し **reset せず** `f5b3fcc` から継続 |
| SR-004 | 004a のみ PARTIAL | **004b/c/d/e 追加実装・14本 focused PASS** |
| MCP same-name | 残件 | **未着手のまま**（次 exact 作業） |
| push / main | 未実施 | **未実施**（本版は報告書のみ完成） |

今回セッションの開始HEAD → 終了HEAD:

```text
start: f5b3fcc3d9127e3bd35b54cedbc40ac14d85d2c4   # v1 後の GPT Pro 報告書 commit
end:   89b2004b4bea5fa3b8ab365097533b8cccd5f9ed   # 004e camofox/tirith/skill-sync
dirty: clean（worktree）
```

---

## 1. 結論（1段落）

Windowsネイティブ長時間稼働ハーネスの契約を維持したまま、凍結上流 U=`6dd091a89c…` から multiplex credential / profile 境界を**選択的 COMPOSE**し続けている。Task 0–3 は完了のまま再利用。第一版以降、SR-20260913-004 の memory identity・aux/proxy URL・agent-cache release scope・tool-side memo（camofox/tirith/skill-sync）をローカル commit し、隔離 TEMP HOME 上で focused 回帰 **14 passed**（tested SHA=`89b2004b`）。**MCP same-name 接続キーは未実装**のため SR-004 はなお PARTIAL。push / PR / main merge / tag / release / 本番操作は未実施。24h soak・private GHSA・packaging は NOT_RUN。本第二版は「報告書の完成」であり、campaign の SOURCE/RELEASE 完成ではない。

---

## 2. 凍結比較基準（exact SHA）— **変更なし**

開始時刻 `2026-09-13T13:10:05+09:00` に一度だけ凍結。U を現在の `upstream/main` や草稿 `205645ee…` へ動かしていない。歴史的 provenance も未改変。

| 役割 | Exact SHA / 値 |
|---|---|
| **D0** | `7c697a8a658d4ceadb80276f37b90cd93d84d6a9` |
| **U** | `6dd091a89c33e6e4909a80f78343bb384deb5ca8` |
| **R** | `v2026.9.11` / 0.21.2（annotated `2160b2d59c…` ≠ peeled） |
| **R peeled** | `939e45c91d751fadd94dcd1b873ac3cb44846213` |
| **H** snapshot | `b51c055a12220f8c7c18660e8599365012e19532` |
| **H** release commit | `29112bef099274229cadff79cdff7bf7b99c4b77` |
| merge-base(D0,U) | `1fe0f2f3ac9748ce799272eb93bee2937b5ab802` |

比較窓: H..U = 2129 commits / 3130 files；R..U = 391 / 861。  
製品版は D0 時点のまま **0.21.1**（本 campaign で SemVer 未更新）。`allow_upstream_sync: false` 維持。

### 本家 main dirty（未取り込み・未破壊）

観測時点（報告書執筆時）の本家 checkout:

- modified: `scripts/windows/watchdog-go/{backend,backend_test,recovery,recovery_test,watchdog}.go`
- untracked: `airi-pr2520-work/`, `eq.json`, `quake_check.py`, `tmp_status.json`

方針: 隔離 worktree のみ。main WIP と campaign を混ぜない。

---

## 3. 禁止事項の遵守

| 項目 | 状態 |
|---|---|
| bulk merge / rebase / 大量 cherry-pick | **未実施** |
| WSL 逃避 | **未使用** |
| 第二 supervisor / credential / SessionDB owner | **追加なし**（`_profile_home_for_key` は既存 SessionStore へ最小追加） |
| push / PR / main merge / tag / release / install / reboot | **未実施** |
| 本番 Desktop / Gateway / Watchdog / llama / voice / VRChat | **未操作** |
| hakuapulse-orchestrator MoA | **非接触** |
| 実 profile / secret / 実 DB テスト | **なし**（`%TEMP%\hermes-sr-test-*`） |
| §9.2「子へ渡した secret を lease 無効化だけで回収」主張 | **していない** |

---

## 4. CodeGraph（探索証拠のみ・再全索引なし）

| 項目 | 値 |
|---|---|
| Version | **1.6.0** pin |
| 方針 | stale/影響範囲のみ補完。全 repo 再構築なし |
| 注意 | navigation のみ。実行・意味論一致の証明ではない |

---

## 5. 保護契約（FEATURES / CARRY）— 変更なし

- FEATURES 18/18・CARRY 24/24 分類済み（退役なし）
- semantic-graph abstention HOLD 維持
- Go Watchdog ≠ Desktop backend ≠ Gateway ≠ model/embedding 寿命分離、Browser handoff、Hypura、local llama/hot-swap、VRChat/Unity、VOICEVOX/Irodori/AITuber、prompt cache を退行させていない（本差分の対象外パス）

---

## 6. 採否台帳サマリ

成果物: `docs/windows/semantic-refresh-2026-09-13/change-inventory.json`

| ID | 判定 | 検証 | 内容 |
|---|---|---|---|
| SR-001 | COMPOSE | **PASS_FOCUSED** | write-guard per-call |
| SR-002 | SKIP_WITH_REASON | CLASSIFIED | POSIX state.db modes |
| SR-003 | COMPOSE | PENDING | SessionDB registry |
| SR-004 | COMPOSE | **PARTIAL_PASS** | 004a–004e 済；MCP same-name 等残り |
| SR-005 | COMPOSE | PENDING | gateway mid-turn authz（004 MCP残と依存） |
| SR-006 | PORT | PENDING | MCP breaker / SSE |
| SR-007 | DEFER_WITH_BLOCKER | NOT_STARTED | Desktop onboarding |
| SR-008 | SKIP_WITH_REASON | — | Linux LC_CTYPE |
| CARRY-RECHECK | KEEP/EQUIV | PENDING_PER_ITEM | 二重実装禁止 |

H..U 2129 の全件個別分類は未完（優先 path seed のみ）。

---

## 7. 実装済み slice と exact-head 検証

### 7.1 ローカル commit 列（D0 以降・campaign）

```text
89b2004b4b fix(multiplex): key camofox/tirith/skill-sync memos by profile home     ← 004e
734d6a6b57 fix(multiplex): scope memory identity, aux URLs, and agent-cache release ← 004b/c/d
f5b3fcc3d9 docs(windows): add GPT Pro handoff report …                            ← v1
a537893877 docs(windows): record write-guard PASS and multiplex tool-credential slice
c0446b9209 fix(multiplex): scope Modal/Browser-Use/Weixin credentials             ← 004a
081e8d075e fix(file-tools): resolve write-guard home/config per active profile    ← 001
ac48f6fa45 docs(windows): freeze semantic-refresh 2026-09-13 baseline …
```

Candidate HEAD: **`89b2004b4bea5fa3b8ab365097533b8cccd5f9ed`**

### 7.2 第一版までに完了（再掲・拡大解釈禁止）

| Slice | 契約 | Receipt |
|---|---|---|
| **001** | home/config per-call；A→B→A 順序独立 | write-guard class **5 passed** |
| **004a** | Modal / Browser-Use / Weixin が default environ 非継承 | tool credential **2 passed** |

※「write-guard 全通」≠ Task 5 全体完了。

### 7.3 本版で追加した実装（意図した意味論差分）

| Slice | Upstream seed | Owner（COMPOSE先） | 意図した差分 |
|---|---|---|---|
| **004b** | a9838c F7 | `plugins/memory/{mem0,honcho,hindsight,supermemory,retaindb,openviking}` | secondary scope miss 時、identity/tenant/endpoint は **provider 自身の default**。default `os.environ` の bank/project/user に書き込まない |
| **004c** | a9838c F8 | `auxiliary_client` / `auth._nous_inference_env_override` / `GatewayRunner._get_proxy_url` / browserbase・firecrawl URL | scoped API key が **default の proxy/host** を叩かない。UnscopedSecretError のみ environ（単一 profile） |
| **004d** | a9838c agent-cache | `gateway/run.py` `_spawn_release_thread` + `session._profile_home_for_key` | eviction thread は `copy_context`；unscoped housekeeping は owning profile の `_profile_runtime_scope`。U の `run_agent_cache.py` 分割は採用せず |
| **004e** | 4b8c01 部分集合 | `browser_camofox` / `tirith_security` / `skill_manager` sync timer | VNC・tirith path・sync debounce が **profile home / Camofox URL** で分離。timer は scheduling turn の context で発火 |

**未実施（004 残）**

- MCP same-name per-profile connection keys（ceaf622；D1 は `tools/mcp_tool.py` monolith）
- 4b8c01 残り（aux semaphore、image_token_cost、computer_use aux-vision、MCP discovery lock）
- outbound webhook `secret_env` / i18n `HERMES_LANGUAGE`（a9838c F11）
- mem0 OSS `DirectOpenAILLM` / read_extract FIRECRAWL hosted OCR — **本 fork に経路なし**

### 7.4 検証 receipt（OS / runtime / tested SHA）

```text
OS:      Windows 11
Runtime: worktree venv Python；pytest
HOME:    isolated %TEMP%\hermes-sr-test-*
Command:
  python -m pytest
    tests/plugins/memory/test_multiplex_memory_identity_scope.py
    tests/agent/test_multiplex_base_url_scope.py
    tests/gateway/test_agent_cache_release_profile_scope.py
    tests/tools/test_multiplex_tool_cache_scope.py
    tests/tools/test_multiplex_tool_credential_scope.py
    tests/tools/test_file_write_safety.py::TestMultiplexProfileCacheGuardsAreProfileScoped
    -q
Result:  14 passed in ~5.5s
Tested:  89b2004b4bea5fa3b8ab365097533b8cccd5f9ed
```

事前（004e 前）の 004b–d + 001/004a: **12 passed @ `734d6a6b57`**。

### 7.5 PASS に算入しない既存 Windows 失敗

- `TestAtomicWrite::…` — POSIX `0o600`
- `TestProtectedInstructionFiles::…` — WinError 1314 symlink 特権

---

## 8. 完了ゲート（分割状態）

| Gate | 状態 |
|---|---|
| Task 0–3 | **COMPLETE** |
| 本報告書 v2 | **COMPLETE**（文書） |
| SOURCE_IMPLEMENTATION_COMPLETE | **false** |
| SEMANTIC_SCOPE_VERIFIED | **false** |
| WINDOWS_NATIVE_VERIFIED | **false** |
| PRIVATE_SECURITY_VERIFIED | **false** / UNVERIFIED_PRIVATE_CONTRACT |
| LONG_RUNNING_VERIFIED | **false** / soak NOT_RUN |
| PACKAGING_VERIFIED | **false** |
| RELEASE_READY | **false** |
| PUBLISHED | **false** |

---

## 9. 版整合

| 層 | 現状 | 本 campaign |
|---|---|---|
| downstream product | 0.21.1 | 未更新 |
| upstream semantic target（候補） | 0.21.2 + U=`6dd091a…` | coverage 未完；宣言不可 |
| historical provenance | 0.21.0 / H=`b51c055…` | **上書き禁止** |

---

## 10. Rollback

```powershell
cd ".worktrees/semantic-refresh-d1"
git log --oneline -12
git revert --no-edit 89b2004b4b   # 004e
git revert --no-edit 734d6a6b57   # 004b/c/d
# 必要なら 001/004a も slice 単位で revert
```

- 本家 main の dirty に `reset --hard` しない
- 本番 HERMES_HOME / secrets / live DB は未変更

---

## 11. GPT Pro への次アクション（推奨順）

1. **SR-004 残: MCP same-name connection-key** を `tools/mcp_tool.py` 台帳へ COMPOSE（U の `mcp_tool_scope.py` を参照するが、module 分割を強制しない）。合成 credential + 隔離 profile で A/B 同名サーバが別接続になること、cooldown/breaker が sibling を汚染しないことを RED→GREEN。
2. 4b8c01 残 memo（aux semaphore / image_token_cost / computer_use / MCP lock）を owner 単位で。
3. **SR-003** SessionDB registry（第二 DB owner 禁止）。
4. **SR-005** gateway mid-turn authz（004 MCP が閉じるか、依存を明示して部分進行）。
5. CARRY ALREADY_EQUIVALENT 再確認（二重実装禁止）。
6. 専用 test install で Windows-native 拡大。本番 claim/port に戻らない。
7. soak / private / packaging は別ゲート。未実行を PASS にしない。
8. **feature 枝 push / PR / main merge は別承認後のみ。** 本版では実施しない。main 直 push は dirty WIP 混線のため非推奨。

### 再開時の最短コンテキスト

```text
Worktree: .worktrees/semantic-refresh-d1
Branch:   feat/windows-semantic-refresh-2026-09-13
HEAD:     89b2004b4bea5fa3b8ab365097533b8cccd5f9ed
D0:       7c697a8a658d4ceadb80276f37b90cd93d84d6a9
U:        6dd091a89c33e6e4909a80f78343bb384deb5ca8
Ledger:   docs/windows/semantic-refresh-2026-09-13/
Next:     MCP same-name connection-key COMPOSE into tools/mcp_tool.py
          (ref: upstream ceaf622 + tools/mcp_tool_scope.py in .worktrees/semantic-refresh-u)
```

全文再読や全 index 再構築は不要。owner・diff・test 単位で進めること。

---

## 12. 添付・参照パス

```text
docs/windows/semantic-refresh-2026-09-13/baseline.json
docs/windows/semantic-refresh-2026-09-13/owner-map.md
docs/windows/semantic-refresh-2026-09-13/protected-contracts.md
docs/windows/semantic-refresh-2026-09-13/change-inventory.json
docs/windows/semantic-refresh-2026-09-13/decisions.md
docs/windows/semantic-refresh-2026-09-13/rollback.md
docs/windows/semantic-refresh-2026-09-13/verification-summary.json
docs/windows/semantic-refresh-2026-09-13/GPTPRO_HANDOFF_REPORT.md   ← 本ファイル（v2 正本）
_docs/2026-09-13_semantic-refresh-resume-multiplex_Cursor.md
_docs/2026-09-13_gptpro-handoff-report-v2_Cursor.md
```

---

## 13. クレジット（取り込んだ上流）

- PRATHAMESH75 — `#107327` / `#107335` write-guard
- Teknium et al. — a9838c（tool/memory/aux/agent-cache 部分集合）、4b8c01（camofox/tirith/skill-sync 部分集合）
- ceaf622（MCP same-name）— **未 COMPOSE**（次作業）

---

**本第二版は「報告書の完成」と「部分実装＋検証済み契約の引き継ぎ」である。上流全機能同一・長時間稼働合格・main 取り込み準備完了・リリース準備完了を意味しない。**
