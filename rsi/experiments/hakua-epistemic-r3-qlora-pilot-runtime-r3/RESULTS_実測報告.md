# r3 QLoRA試行 実測結果

**結論：重み変更と比較評価は実行完了。事前規約による総合改善判定は不成立。採用なし。**

## 実際に行ったこと

- 隔離base：`Qwen/Qwen2.5-0.5B-Instruct`。現在のHermesモデルは変更していない。
- 歴史再構成4件からの合成派生64例。64件の実経験ではない。
- 先に固定された72問を親・子・adapter無効再親で評価。
- NF4 QLoRA、rank8/alpha16/dropout0.05/LR2e-5/2epochs、32 optimizer steps。
- supervisorの実終了コード0、timeoutなし。
- 学習区間の実測時間：111.854秒。
- 平均訓練損失：0.470293 → 0.182845。汎化の証拠ではない。
- 保存adapter：192/192テンソルのbytesが変更。
- 量子化backboneのテンソル/量子化状態hashと元checkpointファイルhashは不変。
- adapterを無効に戻した親の72選択は学習前とすべて一致。

## 凍結評価の結果（条件付き4択の代理指標）

|評価軸|親|子|差|
|---|---:|---:|---:|
|根拠に応じた主張強度|8/8|8/8|+0.00ポイント|
|反証に応じた訂正|8/8|8/8|+0.00ポイント|
|検索不在と不存在の区別|8/8|8/8|+0.00ポイント|
|引用と現在の権限|6/8|8/8|+25.00ポイント|
|打切り観測|2/8|4/8|+25.00ポイント|
|未解決の出自|6/8|7/8|+12.50ポイント|
|コード選択問題|9/12|8/12|-8.33ポイント|
|ツール選択問題|8/12|6/12|-16.67ポイント|

## なぜ不採用か

1. コード選択は1問、ツール選択はnet2問悪化。事前の非退行許容幅を超えた。
2. 引用と権限は子8/8だが親6/8。事前規約は親・子の両方を全問正解と要求していたため、そのgateは不成立。
3. 結果を見てから「子だけ満点でよい」へ書き換えない。
4. 一部の選択正答は改善した。しかし、この試行の総合改善signalはfalseであり、自己改善認証は行わない。

## 検査範囲と未実施

- 72問はテンプレート派生を含む作成者goldの合成課題。独立標本の有意差や一般化を主張しない。
- 条件付き4択logitと第一token形式を測定した。自然文での訂正過程・実際のツール権限・コード生成/実行退行は未評価。
- 共有GPUでのforward時間は記述値のみ。protocolのlatency toleranceを独立採用gateとして実装したとは主張しない。
- 正規化hash重複0は実検査で確認。意味上の近似重複排除を保証しない。
- 原4 memory/revisionはUNRESOLVEDのまま。r2の監査NEEDS_REVISIONも変更していない。
- r3正式独立成果物監査は未実施。別コンテキストのコード/方法論レビューを正式監査と混同しない。
- Codex readonlyレビューは選択モデル非対応の400で失敗。Black/flake8依存欠落も履歴に残す。
- runtime実モデルテスト2件・整合性テスト9件PASS、ruff0.15.10とcompile PASS。repository全suite未実施。

## 状態

```text
重み変更の観測                 = YES
凍結評価と親再現コントロール     = COMPLETED
事前規約の総合改善signal        = FALSE
正式自己改善/Level3認証         = NO
正式成果物承認                  = PENDING
base merge / live activation   = NO
最終状態                        = STOP_AND_REPORT
```

## 証拠

`runs/pilot003/results.json`、`training_history.json`、`weight_change.json`、親/子/再親の各JSON。
`adapter_parent_readback.json`、`result_parent_verification.json`、`pilot003-exit.json`。
旧失敗・比較方法の訂正は各revisionと`hash_comparator_correction.json`に保全。

学習後adapter SHA-256: `1a286bc00e353e059e83cdfd034a8d89d1380b8936daeae48cd1b791205a1e52`

## 保存adapterの追加読み戻し

- 全72問を新規プロセスで再評価する補助確認は、190秒上限で36問経過時に打切り。exit15。
  これは完了でも全72問一致でもない。`artifact-reload-exit.json`とlogを保全。
- 別の限定確認はexit0。保存adapter192テンソルすべてが学習後のidentityと一致し、
  再構成NF4 backboneのhashも学習時と一致。凍結評価の最初の1問だけでforward一致を確認。
- この1問を全72問の再現や能力再実験へ一般化しない。元試行での親・子・再親72問は完了済み。
- 元NVCC発見処理のUTF-8 decode thread例外は補助実行でも残る。成功表示で消さない。

## 別コンテキストの読み取り専用レビュー

保存されたJSON/Markdownレビューを回収し、記載された全ファイルhashを親が照合。
結論は「検査範囲内で現在の重大欠陥を特定せず」。**監査PASSではない**。
レビューは学習・テスト・保存adapter検証を実行せず、結果vector/binaryの独立成果物監査でもない。
4ルートの反復、テンプレート相関、多肢選択proxy、1seed、producer-authored goldの限界を指摘。
レポートは原文のまま保存。追加範囲指定は親assistantのsteerであり、本人の新たな正式承認ではない。
親による後続adapter読み戻しも独立監査へ足し込まない。
