# 監査ログ: ローカルLLM進捗トラッカーの effective base_url 解決修正

- **実施日時**: 2026-09-21 23:15 JST
- **実装担当**: Gemini (Pair-programmer Antigravity)
- **対象ファイル**:
  - `agent/chat_completion_helpers.py`
  - `tests/test_local_llama_progress.py`

## 1. 課題と根本原因
ユーザーより「まったくステータスラインが変わっていない」との報告。
調査により、以下の致命的な判定欠落が判明：
- `config.yaml` で `model.base_url: "http://127.0.0.1:8080/v1"` が設定されている場合、`AIAgent` インスタンスの `agent.base_url` は `None` のまま初期化される（`_client_kwargs["base_url"]` や `api_kwargs["base_url"]` にのみ保持される）。
- `agent/chat_completion_helpers.py` の `_is_local_request = bool(agent.base_url and is_local_endpoint(agent.base_url))` が `agent.base_url` のみを参照していたため、**常に False と判定されていた**。
- 同様に `_progress_tracker = _LlamaProgressTracker(agent, agent.base_url, ...)` でも `agent.base_url`（`None`）が渡されていたため、`tracker.start()` の先頭チェックで即座に return し、**進捗監視スレッドが一切起動していなかった**。

## 2. 実装内容
1. **`_resolve_effective_base_url` ヘルパー関数の追加**:
   - `agent.base_url`
   - `agent._client_kwargs.get("base_url")`
   - `api_kwargs.get("base_url")`
   - `config.yaml` の `model.base_url` / `base_url`
   - `provider` が `llama-server` / `custom` / `local` / `ollama` の場合のデフォルト `http://127.0.0.1:8080/v1`
   を順次フォールバック検索し、確実に実効 URL を解決する設計とした。
2. **すべての判定・初期化箇所への適用**:
   - `_LlamaProgressTracker.__init__`: `base_url or _resolve_effective_base_url(agent)`
   - `interruptible_api_call`: `_resolve_effective_base_url(agent, api_kwargs)`
   - `interruptible_streaming_api_call`: `_resolve_effective_base_url(agent, api_kwargs)`
   - `_stream_stale_timeout` 判定
   - `_is_local_request` 判定
3. **ロギング追加**:
   - `_LlamaProgressTracker._run` で wait notice 発行時に `logger.info("Local llama progress: %s", notice_msg)` を出力し、`agent.log` で常時トレース可能にした。
4. **テスト拡充**:
   - `tests/test_local_llama_progress.py` に `test_resolve_effective_base_url` を追加。9テスト全PASS（0.108s）。

## 3. 検証結果
- `py -3 -m unittest tests.test_local_llama_progress`: PASS (9/9)
- `py -3 -m py_compile agent\chat_completion_helpers.py`: 警告0
