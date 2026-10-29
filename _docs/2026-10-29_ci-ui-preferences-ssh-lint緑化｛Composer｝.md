# 2026-10-29 CI 緑化: ui_preferences / SSH suffix / lint

- **日時**: 2026-10-29 18:07 +09:00
- **実装AI**: Composer (Auto)
- **対象 tip (親)**: `11855ec30c0` — browser webapp bridge は typecheck まで到達していたが CI 本体が赤

## 仮説

1. Electron `ui-preferences` テストが `hermes_cli.ui_preferences` を要求するのに Python 側が未復元
2. `controlSocketPath` が `.hermes` 直書きで `HERMES_DATA_DIR_SUFFIX` を無視
3. `updater-process.test.ts` が `/min` 期待のまま実装（`/b`）と乖離
4. bridge port 由来の eslint import / `import()` 型注釈エラーで Tier-1 Desktop が赤
5. carry metrics が stale で Downstream policy が赤
6. Python tests の failure は JS 失敗後の runner cancel 連鎖の可能性が高い

## 検証結果

| 項目 | 結果 |
|------|------|
| `hermes_cli/ui_preferences.py` + router + tests を a4392f1 から復元 | OK |
| `web_server` に `route_on("ui_preferences")` で mount | OK |
| `defaultControlDir` → `platformDefaultHermesHome` + `shortControlDir` | OK |
| `updater-process.test.ts` を a4392f1 に戻す | OK（data-paths/updater vitest 緑） |
| eslint import / type import 修正 | OK（`--quiet` 対象ファイル緑） |
| `pytest tests/hermes_cli/test_ui_preferences.py` | 11 passed, 1 skipped |
| carry metrics 再生成 | OK |

## 変更ファイル（要旨）

- `hermes_cli/ui_preferences.py`, `hermes_cli/web_routers/ui_preferences.py`, `tests/hermes_cli/test_ui_preferences.py`
- `hermes_cli/web_server.py`（router mount）
- `apps/desktop/electron/ssh-connection.ts`, `updater-process.test.ts`
- Desktop lint 対象: `global.d.ts`, `gateway-settings.tsx`, `browser-connection.ts`, `webapp-port-*.ts(x)`, `session-states.ts`
- `_docs/carry-surface-20260826.{json,md}`

## 非コミット

- `plugins/hermes-strata/core.py`（ローカル実験差分）
- `.build/`, `apps/desktop/dist-webapp/`, 未追跡の `auth_nous.py` 等
