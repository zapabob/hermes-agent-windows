# 2026-10-29_windows-desktop-force-rebuild-main_{Cursor}

## 概要

**main** ブランチ上で hermes desktop --build-only --force-build を実行し、pps/desktop/release/win-unpacked/Hermes.exe を再生成。BUILD_EXIT=0。9120 PID 13940 は未kill。release/dist は .gitignore のためソース差分なし → 本ログのみ commit 対象。

## 背景・要求

ユーザー指示: デスクトップ再ビルドはメインブランチで。完了後 main に commit/push。

## 前提・判断

- Checkout: `C:\Users\downl\Documents\New project\hermes-agent` @ `f268176a012920974475865c02b7ec7872dd8fb0` (main)
- C: 空き逼迫 → TEMP/npm/electron cache は H:\Temp / H:\npm-cache / H:\electron-cache
- ビルド前に win-unpacked の Hermes.exe を停止（Startup 再起動を再kill）
- Electron ソース修正はこのターンでは main に未投入（worktree feat/windows-webapp-port-20261028 側に残存）

## 変更対象

| Path | Change |
|------|--------|
| `apps/desktop/release/win-unpacked/**` | electron-builder --dir 再pack（gitignored） |
| `apps/desktop/dist/**` | vite + electron-main/preload bundle（gitignored） |
| `_docs/2026-10-29_windows-desktop-force-rebuild-main_Cursor.md` | 本ログ |

## テスト・検証結果

| Gate | Result |
|------|--------|
| `hermes desktop --build-only --force-build` | **PASS** exit=0 |
| Hermes.exe | `C:\Users\downl\Documents\New project\hermes-agent\apps\desktop\release\win-unpacked\Hermes.exe` size=235409920 mtime=2026-10-29T00:49:25.6962287+09:00 |
| 9120 occupant | **PID 13940 untouched** |
| Log | `H:\hermes-desktop-build\force-build-main-20261029.log` |

## 次の推奨アクション

1. 必要なら Desktop を `start-hermes-desktop.ps1` で再起動し、local backend 接続を目視確認。
2. Electron 接続修正（webapp-port / READY publish 等）を main へ載せる場合は feat worktree から選択 cherry-pick。

## 時刻

2026-10-29T00:50:22+09:00
