# 2026-10-27_strata_research_openmanus

**実装内容**: Strata に関する包括的リサーチを実施。OpenManus エージェントによる調査とコードベース検証を併用し、Hermes Agent 内の `hermes-strata` プラグインが参照する Niko1221 の Strata LLM と、Strata Labs の Rust 製 strata-inference、Atomic Strata の記憶基盤の混同を解消。

**実装 AI**: OpenManus

## 要約

Hermes Agent 環境における Strata は **Niko1221 Strata LLM** を指す。`plugins/hermes-strata` はローカル推論エンジン `http://127.0.0.1:8080/v1` へ OpenAI Chat Completions 互換で接続し、`strata_status / strata_infer / strata_memory_sync / strata_inspect_gguf` を提供する。

## 調査結果

### 1. Hermes 内 Strata 実装

**プラグインパス**
- `plugins/hermes-strata/__init__.py`
- `plugins/hermes-strata/core.py`

**提供ツール**
- `strata_status`: `GET /models` でサーバ alive 判定。ハードウェア想定 RTX 5060 Ti 16GB + 32GB Zero-VRAM Drafter。対応アーキテクチャ `deepseek2 / deepseek_v3 / qwen2 / qwen2_moe / spin8`
- `strata_infer`: `/chat/completions` へ POST。既定モデル `deepseek-v4.1-flash` / `qwen3.8-flash-next`。thinking モードで DeepSeek MLA reasoning 有効化。`inject_memory` で SOUL.md / MEMORY.md 注入
- `strata_memory_sync`: Hakua SOUL.md と MEMORY.md 同期。action `read / append / context / stats`
- `strata_inspect_gguf`: GGUF ヘッダ解析。RTX 5060 Ti 16GB + 32GB RAM 基準で VRAM 直接適合 / CPU オフロード適合を判定

**core.py 設定**
- `DEFAULT_STRATA_URL = "http://127.0.0.1:8080/v1"`
- `find_strata_bin()` 探索先: `AppData\Local\Programs\Strata\engine-bundle\0.1.47-windows-x86_64-cuda-cuda13\strata.exe`
- `run_strata_inference()` は `extra_body.thinking` と `reasoning_effort` を DeepSeek モデルへ付与、`<think>` タグを分離

### 2. Strata 勢力の整理

#### A. Strata Labs strata-inference
- Repo: https://github.com/stratalab/strata-inference
- Zero-dependency Rust inference engine for GGUF
- 機能: GGUF v3 parser, BPE/WordPiece tokenizer, Metal/CUDA backend, BERT/LLaMA/Gemma
- ライセンス: MIT
- Hermes 関係: なし。名称が重複

#### B. Niko1221 Strata LLM
- Repo: https://github.com/Niko1221/Strata  33.7k stars
- Site: https://stratallm.org/
- 目的: 12GB VRAM で 125B+ MoE を動かすコンシューマ推論エンジン
- 技術: Predictive Sparse Routing, Tiered VRAM-RAM Cache, Zero-Copy Pinned Memory
- 要件: RTX 3060 12GB + 64GB RAM 最低、RTX 4070 Ti 16-24GB 推奨
- モデル: Qwen3.8-Flash-Next 125B, Qwen3.6-35B-A3B, DeepSeek-V4.1-Flash
- API: OpenAI / Anthropic 互換 `localhost:8080/v1`
- ライセンス: MIT
- Hermes 統合: `strata connect` で公式対応。プラグインはこれを前提

ベンチマーク Qwen3.8-Flash-Next 125B RTX 4070 12GB +64GB
- Strata: 21.4 tok/s
- Ollama: OOM
- vLLM: 3.8 tok/s

#### C. Atomic Strata / Atomic Memory
- Docs: https://docs.atomicstrata.ai/integrations/coding-agents/hermes/local
- 役割: Hermes 永続クロスセッション記憶基盤
- `am init --local` + `npx -y @atomicmemory/hermes-plugin install`
- Strata LLM とは別軸

#### D. その他同名
- Strata Research 市場調査
- Strata AI 法律事務所向け AI エージェント
- 技術的関係なし

## 比較表

| プロジェクト | 開発者 | 目的 | API 互換 | Hermes 統合 |
|---|---|---|---|---|
| hermes-strata plugin | Hermes コミュニティ | ローカル Strata 推論 + Hakua メモリ同期 | OpenAI 経由 | ネイティブツール 4種 |
| Strata Labs strata-inference | Strata Labs | Rust製 GGUF 推論 | なし | 無関係 |
| Niko1221 Strata LLM | Niko1221 | コンシューマ MoE 推論 | OpenAI / Anthropic | `strata connect` 公式 |
| Atomic Memory | Atomic Strata | 永続記憶基盤 | — | プラグイン `atomicmemory` |

## 制限事項
- `strata_infer` はサーバ `http://127.0.0.1:8080` が稼働必須。未起動時は `Strata inference server offline` エラー
- `strata_inspect_gguf` は RTX 5060 Ti 16GB + 32GB RAM 基準のヒューリスティック判定
- `strata_memory_sync` は MEMORY.md を `§` 区切りで読み書き、ファイル競合に注意
- OpenManus 調査はネットワークスコープ `none` で計画のみ生成、実Web抽出は並行で実施

## 検証
- プラグインファイル存在確認: `plugins/hermes-strata/__init__.py` 186行、ツール登録確認済み
- `core.py` ハードウェア記述 `NVIDIA GeForce RTX 5060 Ti 16GB` 確認
- GitHub リポジトリメタ確認: Niko1221/Strata 33.7k stars、`stratallm.org` ドキュメント取得

## 変更履歴
- 2026-10-27: 初回リサーチ完了、MILSPEC ドキュメント生成

---
*ASI_ACCEL*
