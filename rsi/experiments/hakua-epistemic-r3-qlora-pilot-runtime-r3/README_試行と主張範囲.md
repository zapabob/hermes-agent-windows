# r3 QLoRA試行：実行・監査の分離

この成果物は、Qwen/Qwen2.5-0.5B-Instructの隔離したQLoRA試行です。
現在のHermesサービス、r2の独立監査判定、正式昇格、採用状態を変更しません。

## 実験契約
- base revision: `7ae557604adf67be50417f59c2c2f167def9a775`。
- 歴史再構成4 rootからの合成派生64例。64件の独立した実経験ではありません。
- 凍結評価72問：根拠強度・訂正・検索不在・引用と権限・打切り・出自 各8問、coding/tool各12問。
- 訓練と評価のIDおよびNFKC/空白正規化した本文＋選択肢のhash重複は実検査で0。
- rootの原memory/revisionは未解決のまま。r2 ZIPと関連証拠は実際の再構成元であり、原記憶の正本ではありません。
- 学習はrank8、alpha16、dropout0.05、LR2e-5、2epochs、NF4、base固定、mergeなし。
- 親は同じNF4 backboneでadapter無効。子はadapter有効。学習後に親の再評価も実施。
- 判断規約は`protocol.json`、実行前の8入力hashは`frozen_inputs.json`。

## 主張の限界
- 条件付きA/B/C/D logit判定の試行であり、自然文生成・実ツール実行・一般的安全性の実証ではありません。
- 4つのrootの合成派生例は相関します。72問も独立母集団からの抽出ではありません。
- goldは作成者が付けたもので、独立した正解監査済みとは主張しません。
- coding/toolは選択問題です。実コード生成・テスト実行の退行評価は未実施です。
- 許可境界はこの8問すべて正解が試行のhard gateであり、安全性全体のPASSではありません。
- 共有GPUの時間測定は記述統計。遅延への因果効果とは解釈しません。
- 良化が見えても正式Level3やRSI成功の認証にはしません。

## 失敗・訂正を保全
1. pilot001：親評価中のnative memory allocation failure。根本原因は未確定。
2. runtime-r2/pilot002：私の監視スクリプトの誤った`--run-name`でexit2。学習前。
3. runtime-r2は監視コードを8件固定一覧へ追加した契約不整合もあり、別revisionで切り離した。
4. 項目hashの不一致という自己報告は撤回。旧registryは`canonical({prompt,options})`で72問一致。
   当初の照合方法が異なっていた。`hash_comparator_correction.json`が訂正記録。
5. runtime-r3：課題・正解・訓練bytesを保ったまま、起動引数・hash規約・監視manifestを整合。
6. Codex独立CLIレビューは選択モデルがChatGPTアカウントで非対応との400で失敗。レビューPASSではない。
7. borrowed環境のBlack/flake8は補助依存欠落でERROR。隔離uv toolのruff0.15.10実行はPASS。

## 実行
このcheckout内では、元試行の`.venv-cuda/Scripts/python.exe`と`base_checkpoint`を参照します。
元試行環境は既存irodori CUDA runtimeをread-onlyで参照し、その他の環境を書き換えません。
再実行する場合は、新たな実験revision・run ID・固定hashを用意してください。既存runを上書きしません。

最後は常に`STOP_AND_REPORT`。正式成果物承認は`PENDING`、自動昇格とlive activationはありません。
