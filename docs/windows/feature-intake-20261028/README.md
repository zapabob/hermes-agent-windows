# Hermes Windows-native — Cursor実装計画一式

2026-10-28 JST作成。Windowsネイティブ版の既存機能を守り、上流の有用な機能を差分として導入するための実装計画です。

## 読む順序

1. [CURSOR_START_HERE.md](CURSOR_START_HERE.md)：配置方法とCursorへ貼る開始・再開プロンプト。
2. [CURSOR_WINDOWS_NATIVE_FEATURE_PLAN_20261028.md](CURSOR_WINDOWS_NATIVE_FEATURE_PLAN_20261028.md)：接続点、T00〜T14、TDD、回帰、mutation、Windows E2E、rollback。
3. [SPEC_WINDOWS_NATIVE_20261028.md](SPEC_WINDOWS_NATIVE_20261028.md)：要件R01〜R13、所有境界、製品判断。
4. [ACCEPTANCE_MATRIX.md](ACCEPTANCE_MATRIX.md)：検証IDと要件・task・破壊変異・Windows試験の対応。
5. [SOURCE_EVIDENCE.json](SOURCE_EVIDENCE.json)：固定SHA、確認したsource、事実と設計判断、実施していない検証。
6. [PLAN_REVIEW.md](PLAN_REVIEW.md)：文書レビューで修正した点と、文書そのものの検査結果。
7. `SHA256SUMS.txt`：この一式の本文ファイルのSHA-256。

## 最初の開発範囲

T00で現checkoutを照合してから、M1のT01/T02/T03/T05/T06/T07/T08/T09/T10を順に進めます。T04とT11以降は後続の選択的な段階です。queue・local prefill等の実装済み部分は、受け入れ条件が通れば作り直しません。

調査時の下流は `5531c849b424cdfee17946935eec73363917e5e7`、上流参照は `e5ea5fd9ccdf2913c0b21b24eb3d22b321d2e2a6`。これらは実checkoutを強制的にresetする指示ではありません。

本一式の状態はPLAN_ONLYです。ソースの静的調査と文書の設計レビューを実施しました。ユーザー環境でのCodeGraph、コード変更、TDD、mutation、Windows実機試験は未実施です。

