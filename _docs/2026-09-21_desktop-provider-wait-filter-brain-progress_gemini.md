# 監査ログ: Desktop (TypeScript) でのローカルLLM進捗表示 (🧠) フィルター解放

- **実施日時**: 2026-09-21 23:01 JST
- **実装担当**: Gemini (Pair-programmer Antigravity)
- **対象ファイル**:
  - `apps/desktop/src/store/provider-wait.ts`
  - `apps/desktop/src/app/session/hooks/use-message-stream/provider-wait-event.test.tsx`

## 1. 課題と根本原因
ユーザーより「映ってないよTSのほうも手を加えないとだめじゃない？」との指摘。
コードベース調査の結果、Desktop アプリ（React / Nanostores）の `providerWaitText` 関数において、
以下の正規表現フィルターが適用されていたことが判明：
```typescript
return /^(?:⏳|⚠|↻)\s*(?:waiting on|no (?:output|response)|model returned)/i.test(value) ? value : ''
```
このため、Python バックエンド（`_LlamaProgressTracker`）から `thinking.delta` で配信されていたリアルタイム進捗通知：
- `🧠 Reading context: 50.0% (4,096/8,192 tokens) [~540 t/s]`
- `🧠 Reading context: 50.0% (4,096/8,192 tokens) [processing batch... 45s]`
- `🧠 Thinking / Generating: 15 tokens [~18 t/s] (1s)`
がすべて空文字 `""` に置換され、Desktop UI 上で完全に破棄（ドロップ）されていた。

## 2. 実装内容
1. **`providerWaitText` の正規表現更新**:
   `🧠`（Brain絵文字）で始まるローカル推論進捗フレームを許可するよう正規表現を改修：
   ```typescript
   return /^(?:(?:⏳|⚠|↻)\s*(?:waiting on|no (?:output|response)|model returned)|🧠)/i.test(value) ? value : ''
   ```
2. **Vitest 単体テスト拡充**:
   `provider-wait-event.test.tsx` に `🧠 Reading context...` が `sessionProviderWait` に正しく保持され、generic spinner（`◉_◉`）は除外される挙動のテストを追加。8テスト全PASS（64ms）。

## 3. ビルドと配備
- `Restart-HermesDesktopAndLlama.ps1 -SkipLlama` を実行し、Desktop アプリを `pnpm run pack` で完全再ビルドして起動。
