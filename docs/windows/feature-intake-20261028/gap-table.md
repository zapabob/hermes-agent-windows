# Feature gap table — campaign 20261028

**HEAD:** `5531c849b424cdfee17946935eec73363917e5e7`（計画下流SHAと一致）  
**記録時刻:** 2026-10-28 JST  
**方針:** `EXISTS_EQUIVALENT` は作り直さない。`PARTIAL`/`MISSING` だけ実装。

| Task | Req | Classification | Owner / evidence | Gap (行動) | Next |
|---|---|---|---|---|---|
| T00 | baseline | DONE | source-lock.json, CodeGraph local 1.6.0 | — | done |
| T01 | R01 MCP progress | IMPLEMENTED (E2E NOT_RUN) | sink + mcp_progress + gateway emit + Desktop unit | call単位progress接続済み | Desktop stdio E2E |
| T02 | queue/prefill境界 | EXISTS_EQUIVALENT | queue 23✓ / aux+native+llama 70✓; local_prompt 1 baseline FAIL | 新規実装なし | ACK-loss E2E任意 |
| T03 | 子agent設定GUI | IMPLEMENTED (E2E NOT_RUN) | `delegation_config` + `GET/PUT /api/delegation` + Desktop `subagent-settings`（profileEpoch）。pytest 11✓ / vitest 5✓。`output/reports/feature-intake-20261028/T03_subagent-settings.md` | 原子的Apply・secret非露出・stale Apply破棄 | JP profile / local-remote E2E |
| T05 | plugin更新共通化 | IMPLEMENTED (UX/E2E NOT_RUN) | `update_user_plugin_core` 共有。GUIもscan/disable/needs_consent | CLI/GUI gate一致 | Desktop status UX |
| T06 | plugin OAuth broker | IMPLEMENTED (live E2E NOT_RUN) | upstream `e5ea5fd9` を選択移植: `plugin_oauth` / `plugin_provider_requests` / `auth_oauth_pkce_plugin` + `auth_constants` shim + `pm/plugin_declarations` + `hermes auth add\|status\|refresh\|logout` 配線。41✓ 1skip（catalog未移植）。`output/reports/feature-intake-20261028/T06_plugin-oauth.md` | token-never-to-plugin / 4-origin allowlist / profile scope 契約green | 実vault/実IdP E2E, `plugins_cmd_catalog` 移植(T07隣接) |
| T07 | ask_choice | IMPLEMENTED (live Desktop/Ink/CLI E2E NOT_RUN) | upstream `e5ea5fd9` を適応: `hermes_cli/plugin_choices.py`（`bind_asker`/`ask_choice`/`clarify_asker`）+ `PluginContext.ask_choice` + `gateway/plugin_command_choice.py`（chat: `adapter.send_clarify` / TUI: `_clarify_block`）。配線: `gateway/run.py` plugin slash dispatch、`tui_gateway` `slash.exec`、`cli.py` `process_command`。新規テスト73✓。`output/reports/feature-intake-20261028/T07_ask-choice.md` | 未知値→None、曖昧→None、ContextVar例外時reset、並行session非交差、async handler/headless/hook→None、approval API非流用 | `command.dispatch`（reader thread）は未bind→None、実Desktop/Ink/Windows CLI E2E |
| T08 | vault keychain | IMPLEMENTED (native E2E UNIT-LEVEL ONLY / CI-lane NOT_RUN) | upstream `e5ea5fd9` を選択移植: `agent/vault_keychain.py` + `vault_errors.py` + `vault_store` 鍵保管/移行/跨process lock + `hermes vault key [migrate --to file\|keychain]` + `vault.key_storage` 既定file + `create_profile --clone-all` 鍵所有。`output/reports/feature-intake-20261028/T08_vault-keychain.md` | write→readback→復号→pointer commit→旧鍵削除。鍵欠落時に新規鍵を作らない。明示keychain失敗はfile fallbackせずerror | `keyring` extra の pyproject/uv.lock 宣言（他worker編集中のため未着手）, Windows CI lane E2E, Desktop UI |
| T09 | R08 ctx.files | IMPLEMENTED (Windows E2E NOT_RUN) | upstream `e5ea5fd9` を選択移植: `electron/plugin-files{,-ops,-guards,-ipc,-roots}.ts` + `src/contrib/plugin-files.ts` + `fs-ipc`/`preload`/`global.d.ts`/`createPluginContext`。electron 164✓ 16skip（host条件）/ UI 12✓ / mutation 6件検出。output/reports/feature-intake-20261028/T09_ctx-files.md | picker専用grant / handle・plugin ID別 / Windows path別表記・junction・hardlink拒否 / 合成protected roots / list上限はerror / 不正grants.json fail-closed / **exact BigInt identity**（NTFS id > 2^53 の丸め不具合を修正） | 実picker・ゴミ箱・file symlink(権限)・local→remote E2E、grant一覧UI/uninstall連動revoke未配線、senderは app window 検証なし |
| T10 | post_compaction hook | IMPLEMENTED (E2E NOT_RUN) | VALID_HOOKS + fire_post_compaction + durable notify配線 | commit後1回 | Windows listener E2E |
| T04 | advanced delegation | IMPLEMENTED | unit PASS（48+3）。live E2E NOT_RUN | `agent/delegation_*`, `tools/delegate_tool_routes.py`, `plugins/advanced_delegation` | Desktop `/delegation` UXは任意follow-up |
| T11–T14 | prepared/download/sleep/webapp | DEFERRED | M2/M3。今回scope外 | — | 指定時のみ |

## CodeGraph notes

- `_on_tool_progress` owners: `tui_gateway/server.py`, `gateway/platforms/api_server.py`, `cli.py`, stream consumers.
- `compress_context` impact: conversation_compression + run_agent + compression tests（hook追加時は commit fence 後のみ）.
- Indexは途中kill警告あり。広範refactorは避け、具体ファイル読取りで補完済み。

## Desktop規約

- `apps/desktop/AGENTS.md` / `DESIGN.md` 確認済み。
- Backend ownerはElectron main。古いwatchdog owner記述で復活させない。
- Destructive/本番Desktop・llama-serverの停止再起動は本campaign既定では行わない。
