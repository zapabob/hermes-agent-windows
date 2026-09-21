# 監査ログ: ローカルLLMバッチ計算中のリアルタイム秒数ハートビート表示 & 非ストリーミング対応

- **実施日時**: 2026-09-21 22:50 JST
- **実装担当**: Gemini (Pair-programmer Antigravity)
- **対象ファイル**:
  - `agent/chat_completion_helpers.py`
  - `tests/test_local_llama_progress.py`

## 1. 課題と根本原因
ユーザーから「80s経つけど表示が変わらない」との報告。
原因の追究により、以下の 2 点が判明：
1. **llama-server のバッチ処理構造による表示静止**:
   - `llama-server` は Prefill 処理を `--batch-size 2048` 単位で一括計算する。
   - 27B クラスのモデル（例: `qwen3.8-27b-abliterated-mtp`）でコンテキストが 8k トークンに達する場合、1バッチ（2048トークン）の CPU/VRAM 計算に 60〜180秒要する。
   - このバッチ計算中、`n_prompt_tokens_processed` はバッチ完了までインクリメントされず固定値（例: 4096）のままとなる。
   - 前回の実装ではトークン数が変化した時（Delta）のみ通知していたため、バッチ計算中の 60〜180秒間は画面の表示が完全に静止し、ユーザー側ではフリーズや未動作に見えていた。
2. **非ストリーミング呼び出しパスでの進捗トラッカー未適用**:
   - `interruptible_api_call` に `_LlamaProgressTracker` が仕込まれておらず、非ストリーミング時に進捗が出ず汎用待機メッセージになっていた。

## 2. 実装内容
1. **`_LlamaProgressTracker` のリアルタイムハートビート更新**:
   - トークン変化時（Delta）は即座に通知（パーセント、トークン数、t/s速度）。
   - バッチ計算中（トークン未変化時）であっても、**1秒ごとにハートビート通知**を発行。
   - バッチ計算経過秒数（`[processing batch... {elapsed}s]`）をリアルタイムにインクリメント表示。
   - 生成フェーズ（`Thinking / Generating`）でも同様に経過秒数・生成トークン数を毎秒カウントアップ。
   - HTTP Connection timeout を 0.4s から 1.0s に緩和し、高負荷時のソケット切断を防止。
2. **`interruptible_api_call` への組み込み**:
   - 非ストリーミング時も `_LlamaProgressTracker` を開始・終了。
   - ローカルLLM呼び出し時は 30秒ごとの汎用待機メッセージによる上書きをガード。
3. **単体テスト拡充**:
   - `tests/test_local_llama_progress.py` にバッチ計算中ハートビート通知のテストを追加（8テスト全PASS、0.014s）。

## 3. 検証結果
- `py -3 -m unittest tests.test_local_llama_progress`: PASS (8/8)
- `py -3 -m py_compile agent\chat_completion_helpers.py`: 構文警告0
