# r3 QLoRA pilot003 成果物

このbundleは隔離した探索的試行の実測記録とadapterです。正式昇格・配備物ではありません。
優先して `hakua-epistemic-r3-qlora-pilot-runtime-r3/RESULTS_実測報告.md` を読んでください。
最終状態はSTOP_AND_REPORT。改善採用条件は不成立です。

## 内容

- runtime-r3: 凍結入力、訓練/評価code、親/子/再親72件、optimizer32steps、初期/学習後adapter、検証receipt。
- original-pilot と runtime-r2: 学習前に停止した失敗・修正履歴。成功runへ付け替えません。
- 読取専用別コンテキスト科学/コードレビュー: 正式成果物auditではなく、能力・安全認証でもありません。
- 基底safetensors、CUDA環境、既存r2ZIPは容量/権限境界のため同梱しません。
  基底の実ファイルhashはbase_pretrain.json、tensor fingerprintはweight_change.json。
- bundle_manifest.json: 自分自身を含まないfile hash一覧。bundle全体hashは別納品receipt。

## 再実行について

このコードは記録されたrepoのsibling base checkpointと既存CUDA Python環境に依存します。
ZIP単体で即実行できる独立installerではありません。元場所での参照コマンドは
`../hakua-epistemic-r3-qlora-pilot/.venv-cuda/Scripts/python.exe -B pilot_train.py --run-id replica001`
です（runtime-r3をcwdとする）。新しい出力IDを使い、既存runを上書きしません。
再実行は新たな資源使用と実験なので、このbundleの確認だけで自動実行しないでください。

## 解釈境界

4 historical-reconstruction rootsの64合成派生例を学習。4実経験追加とは言いません。
評価72件にはテンプレート相関があります。A/B/C/D条件付き選択proxyであり、自然言語訂正、
実コード生成/実行、実権限動作の検証ではありません。元memory/revisionはUNRESOLVED。
r2監査NEEDS_REVISION、正式承認PENDING、Level2/3未到達は維持します。
保存adapter fresh-process読み戻しは192全tensor identity+base fingerprint+1問で成功。
その前の全72問読み戻しは190秒打切り（36問経過）であり、完了扱いしません。
