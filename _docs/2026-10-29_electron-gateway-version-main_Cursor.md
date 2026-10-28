# 2026-10-29_electron-gateway-version-main_{Cursor}

## 概要

feat worktree に残っていた Electron 接続まわりのうち、**ライブ gateway `/api/health` 版解決**を main へ移植。`gateway-version.ts` + `main.ts` の `resolveHermesVersion` を接続優先に変更。vitest electron 3/3、tsc electron GREEN。

## 背景・要求

ユーザー: feat 側の Electron 接続修正を main に載せる（cherry-pick）。

## 前提・判断

- フル upstream About（`app-version` / `local-runtime-version` / `install-stamp` / `feature-flags` / `updater/external`）は desktop/update BFS になるため今回は見送り。
- 接続の観測契約は `resolveGatewayVersion` → `handleHermesApiRequest('/api/health')`。オフライン時は `__init__.py` フォールバック。

## 変更対象

| Path | Change |
|------|--------|
| `apps/desktop/electron/gateway-version.ts` | 上流ロック SHA から追加 |
| `apps/desktop/electron/gateway-version.test.ts` | 同上 |
| `apps/desktop/electron/main.ts` | import + async live version + About/IPC |

## テスト・検証結果

| Gate | Result |
|------|--------|
| vitest `electron/gateway-version.test.ts` | **3 passed** |
| `tsc -p tsconfig.electron.json --noEmit` | **PASS** |
| desktop force-build | 後続 |

## 時刻

2026-10-29T01:00:03+09:00
base_sha=4dce500787e0f27e67118a1021972cf5b5e7c2cc
