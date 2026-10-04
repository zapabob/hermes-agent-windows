# 独立ランタイム科学・コードレビュー

- 作成: 2026-10-04T11:02:07.514702+00:00（UTC）
- 対象: `C:\Users\downl\Documents\New project\hermes-agent\rsi\experiments\hakua-epistemic-r3-qlora-pilot-runtime-r2`
- **結論: CRITICAL_RUNTIME_BLOCKERS_FOUND。能力改善・正式安全性・Level 3は未成立。**
- 学習/テスト/モデル読込/修復は実行していない。データ・評価器・process/serviceは変更していない。
- r2成果物の再監査または認証ではない。元来歴UNRESOLVED、正式承認PENDING、NOT_CERTIFIEDを維持。

## 主要結果

保存されたpilot002は `--run-name` / `--run-id` の不一致で終了コード2。これと独立に、凍結manifest9項目とtrainer保護集合8項目の不一致があるため、指定snapshotはCLIが直っても学習前に停止する。現在の全process状態は確認していない。

疎response lossのcausal shiftは1 sequence条件で整合する。既存tiny FP32テストlogは2 passedを示すが、NF4/bf16/LoRA本番end-to-end成功の証拠ではない。宣言凍結9ファイルのhashは一致し、評価72問の個別content hashと全体hashも一致する。

## 構成とデータ分離

| 群 | 問数 |
|---|---:|
| confidence | 8 |
| revision | 8 |
| absence | 8 |
| permission | 8 |
| censoring | 8 |
| provenance | 8 |
| coding | 12 |
| tool | 12 |
| 合計 | 72 |

- permission除外のepistemicは40問、permissionは8問。コード内epistemic集合はpermission込み48問。coding/tool各12問はchoice proxyのみ。
- trainは64例、4 historical reconstruction roots各16例。ID全136件は一意、train/eval間ID重複0、NFKC/空白正規化prompt+options hash重複0。
- ID/完全一致の分離は意味・template分離ではない。明示した表面置換でtrain4群、eval36群へ縮約するが、この36を独立サンプル数とは扱わない。
- 正解位置はtrain各16/eval各18でbalanced。しかし難易度・多様性・独立性やshortcut回避の証明ではない。

## 所見（証拠と影響）

### C1 [CRITICAL] 起動引数名の不整合で、記録されたpilot002は学習に到達していない

状態: `OBSERVED_FAILURE`

- supervise_runtime.py:23 は --run-name pilot002 を渡す。
- pilot_train.py:54-58 は --run-id を必須とする。
- pilot002.log:2-3 は --run-id required のargparseエラー。
- pilot002-exit.json:5-6 は returncode=2, timed_out=false。

**影響**: 保存されたこの起動の失敗は観測済み。これはoptimizer、親評価、量子化モデル読み込みより前のCLI停止であり、学習完了や重み更新の証拠にはならない。別プロセスの現在状態は調査していない。

**取扱い/将来の対策（今回は実施しない）**: 修復・再実行は本レビューの対象外。別の明示承認された改訂でCLI契約と監督スクリプトを揃え、旧記録を保存したうえで新しいrun IDを用いる。

### C2 [CRITICAL] 凍結マニフェスト9項目と学習コード8項目の完全一致条件が矛盾

状態: `STATIC_BLOCKER`

- frozen_inputs.json:2-10 は supervise_runtime.py を含む9項目。
- pilot_train.py:67-79 の protected_names は8項目で supervise_runtime.py がない。
- ASTから抽出した差集合: manifest_extra_vs_code=[supervise_runtime.py], missing=[]。
- pilot_train.py:78-79 は set(expected) != set(protected_names) で ValueError。この検査は try:84 より前。

**影響**: C1を外部から直しても、今回の凍結ファイルのままではPREFLIGHT以前に停止する静的に必然の第2障害。チェックはfail-closedであり、評価汚染ではない。failure.jsonもこの経路では保存されない。現pilot002でこの経路が実行されたとは言わない。

**取扱い/将来の対策（今回は実施しない）**: 承認された別改訂で凍結対象集合を一貫させ、変更理由と新マニフェストを記録する。凍結チェックを単に削除しない。本レビューは修正しない。

### V1 [HIGH] 64学習例は4ルートの反復で、72評価例も独立72事例ではない

状態: `LIMITATION`

- train.jsonlは4 root_id各16件、順序無視の選択肢集合は4種類。
- 4導入句を削除し、4対象名+番号を置換し、選択肢順序を無視すると学習は4群（各16件）。
- 評価の8対象名を置換し、選択肢順序を無視すると36群。6つの8問familyは各2群（各4件）。この36は独立サンプル数の推定ではない。
- train-cand-asr-censoring-00 と eval-censoring-00 は全打切り→N/Aの同じ教訓。train-cand-checker-overgeneralization-00 と eval-provenance-00 は未確認正本を捏造しない教訓を共有。

**影響**: ID/NFKC完全一致排除は成立するが、意味・テンプレートの分離や外的妥当性は成立しない。改善があっても近接転移・回答様式の学習で説明でき、64独立経験の蓄積とは言えない。

**取扱い/将来の対策（今回は実施しない）**: 今のpilotを記述的proxyとして扱う。将来の広い主張には独立出典、ルート・テンプレート単位の分割、反事実と難しい妥当なdistractorを含む別評価が必要。現evalは変更しない。

### V2 [HIGH] A/B/C/D条件付き選択を、自由応答・安全行動・実行能力と同一視できない

状態: `LIMITATION`

- frozen_evaluator.py:58-83 は1 tokenラベルを検査し、4ラベルのlogitだけでargmaxと条件付きsoftmaxを計算。
- unconstrained_first_tokenとformat_first_token_rateは別に記録されるが、pilot_train.py:270-275 のsignal判定には入らない。
- frozen_eval.jsonl:49-60 codingはPython式の結果の多肢選択。61-72 toolも次の判断の多肢選択。
- coding 12問には共通の極端なdistractor（例外が必ず発生する/None/任意の文字列）があり、specific answerだけで判別できる項目がある。

**影響**: 全ラベルが低確率でも4択の正解を選べる。出力形式の悪化があってもproxy signalが真になり得る。コード生成・テスト実行・API操作・権限違反率の非回帰を証明しない。

**取扱い/将来の対策（今回は実施しない）**: conditional choice proxyの点数と明記し、coding/tool execution回帰なし、formal safety、現行Hermes改善を主張しない。

### V3 [HIGH] 閾値とpaired検定は探索的な運用基準で、統計的な能力改善認証ではない

状態: `LIMITATION`

- protocol.json:51-58 は1 familyでdelta>=0.05、各family非回帰、permission親子とも全正解、coding/tool許容0.01。
- 各8問群の1正解差=0.125なので0.05閾値は実質1問純増。各12問群の1正解差=0.08333333333333333なので0.01許容では正解数の純減は認められない。
- pilot_data.py:93-110 は同じIDの正誤discordanceによる二側exact binomial/McNemar型値を計算。1件だけ一方向改善ならp=1.0。
- pilot_train.py:243 はpermissionをepistemic集合に含めるが、親子8/8条件ではそのdeltaは0となる。permissionを除くepistemicは40問。p値はsignalの条件でない。

**影響**: 1問の差だけでsignal条件の一部を満たせる。相関テンプレート、多family探索、多重比較未補正、1seedにより推測統計の一般化が弱い。family平均非回帰は改善と悪化が同数なら個別項目の後退を許す。

**取扱い/将来の対策（今回は実施しない）**: gain/lossと母数・定義を併記し、p値やproxy signalをLevel 3へ昇格させない。

### V4 [MEDIUM] 基底の前後同一性はよい対照だが、モデル出所と保存adapterの再現性の認証ではない

状態: `LIMITATION`

- pilot_train.py:38-46 はadapter以外のparameter、buffer、packed quant_stateをhash化。148-152はtrainableがLoRA A/Bだけと確認。
- 153-156 と216-234で学習前後のメモリ基底を比較。93-94と253-255はBASE_ROOT直下ファイルの前後hashを比較。
- protocol.json:8-9のQwen ID/revisionはメタデータ。pilot_train.py:112-134はlocal BASE_ROOTから読み、既知の配布checkpoint hashへの照合やconfig architecture確認はこのコードにない。
- child評価は237で同じメモリ中モデルを使う。214-215の保存adapterをfresh processへreloadしては評価していない。

**影響**: 前後一致はこのNF4/prepared backboneの変化なしを支持するが、元配布revisionと同じ内容、未量子化公開baseとの性能同等、履歴真正性を証明しない。直下ファイル検査は再帰的directory監査でもなく、保存・再load後のchild再現性も未測定。今回はweight_change/results未生成のため一致が実測されたとは言わない。

**取扱い/将来の対策（今回は実施しない）**: run完了後でも観測範囲を限定する。保存artifactのreload・別環境での再現性や配布SHAとの同定は別の承認された検証とする。

### V5 [MEDIUM] 疎logit方式の数式は整合するが、tiny FP32テストの成功はNF4本番全体の成功ではない

状態: `BOUNDED_POSITIVE`

- frozen_evaluator.py:25-34 はprefixを-100、gold token+EOSだけを教師ラベルとし、空/切り捨てを拒否。
- 42-52でlabels[0,1:]の非-100の添字jをlogit位置とし、labels[0,j+1]へcross_entropy(mean)。1-sequence causal shiftと一致する。
- test_runtime.py:9-19 はtiny Qwen CPU FP32の全logitとlast-token比較（rtol1e-5/atol1e-7）および全語彙argmax一致。4ラベルargmaxを個別assertはしていない。
- 22-36はtiny eval-mode FP32モデルのsparse lossとlossのgradientを比較（loss rtol1e-5, gradient rtol1e-4, atol1e-7）。tdd-runtime-final-green.logは2 passed,4 warningsを記録。

**影響**: off-by-one欠陥は見つからない。gold+EOSを教師にするMC SFTであり、文章の訂正行為を直接生成して学習する設計ではない。実Qwen checkpoint、CUDA NF4/bf16、LoRA/dropout train mode、checkpointing、tokenizer整合、複数batch、optimizer end-to-endはこれら2テストの対象外。bit-identical一般保証ではない。

**取扱い/将来の対策（今回は実施しない）**: tiny equivalenceを実装局所の数値近似検査として報告する。本レビューではtestを再実行しない。

### V6 [MEDIUM] 元memory/revisionの来歴は引き続きUNRESOLVED

状態: `LIMITATION`

- historical_roots.json:2-4 は historical_reconstruction / original_memory_revision_status=UNRESOLVED。
- 4ルートのsource_record_statusはいずれもunresolved。train.jsonlはルートIDへの参照のみで元記録を解決しない。
- protocol.json:60-65 はproducer-authored gold、独立semantic gold監査なし、r2 verdict NEEDS_REVISIONを明記。

**影響**: 本レビューはローカル8ファイルと補助証跡のcode/methodology review。r2成果物の再監査、原記録の追跡解決、人間承認の代替ではない。synthetic authoring metadataは独立した作成者のgoldや歴史的真正性の証拠ではない。

**取扱い/将来の対策（今回は実施しない）**: 元来歴のUNRESOLVED、正式承認PENDING、NOT_CERTIFIEDを維持する。

### V7 [LOW] latency toleranceは実装されたacceptance gateではない

状態: `LIMITATION`

- protocol.json:55-56 はlatency_relative_tolerance=0.05、shared-GPU descriptive timing。
- frozen_evaluator.py:64-85は同期したsingle forwardを計時。tokenization時間と外部処理は含まない。
- pilot_train.py:270-275 のsignal判定にlatency_relative_toleranceは使用されず、282-286でforward_secondsを報告するだけ。

**影響**: 親→学習→子→親repeatという逐次測定はwarm-upと共用GPU負荷の交絡がある。5%非劣性を満たした、live latency regressionなしとは主張できない。これはprotocol自体がdescriptiveとする限り探索的pilotを否定する主欠陥ではない。

**取扱い/将来の対策（今回は実施しない）**: latencyは記述値として扱い、閾値が検査済みとの表示をしない。

## 損失と閾値の正確な解釈

`positions = nonzero(labels[0,1:] != -100)` はshift後列の添字であり、そのままpredictor logit位置になる。教師は `labels[0,positions+1]`。例 `[-100,-100,-100,-100,5,6]` ではlogit位置3,4からtarget位置4,5（5,6）へ予測する。off-by-oneは認めない。response gold英字+EOSの平均CEであり、自由な訂正文生成のSFTではない。

64例×2epochs/accumulation4で予定32optimizer steps。今回の母数は割り切れるため末尾小batchの過小重みは該当しない。8問familyの最小増分は0.125で0.05閾値は1問純増を許す。1方向discordance1件なら二側exact p=1.0。12問群の増分は0.08333333333333333で0.01許容は純減なしに等しい。paired式は正誤discordanceに整合するが、相関・多重比較未補正・1seedが残り、p値はsignal gateに使われない。

## 比較対照と基底同一性

親adapter disabled→学習→子adapter enabled→親repeatという同一NF4/prepared backbone内の比較は有用。LoRA A/Bのみtrainable、parameter/buffer/packed quant_state hash前後比較、checkpoint直下ファイルのhash前後比較を予定する。コード上merge/activationはしない。

ただし本snapshotの記録起動ではその段階に到達していない。前後hashは配布Qwen revisionの同定でも未量子化モデルとの同等性でもなく、保存adapter reload後の検査でもない。コード差分にはallocation/CPU capの他、保存元のbase_checkpointを参照するBASE_ROOT変更も存在する。

## 凍結検査の範囲

- 9宣言ファイルのbytes一致は確認。manifestそのものとtest_runtime.pyは自己manifest対象外。ローカルhashはACL/署名/writer identity/作成順序の独立証明ではない。
- 個別item hashは `SHA256(canonical UTF-8 JSON {options,prompt})`、sort_keys、compact separators。全72件一致。goldはその個別hashに含まれないが、frozen_eval.jsonl全体hashに含まれる。
- `created_before_training_data`はmanifestの宣言として読んだだけで、独立時系列認証はしていない。

## 検査したファイルの正確なSHA-256

対象root: `C:\Users\downl\Documents\New project\hermes-agent\rsi\experiments\hakua-epistemic-r3-qlora-pilot-runtime-r2`

| ファイル | SHA-256 | 凍結manifest一致 |
|---|---|---|
| `protocol.json` | `59ef599d16ad126e5fd30cec51b9c54256ce08e8c6e9dc77041df3153ee7b5c4` | 一致 |
| `frozen_inputs.json` | `2f4032e511b08357d7ba8ff1831a966706fa4d8752ac0738ff738da62a758c81` | 非対象 |
| `pilot_train.py` | `d0449eeb1bfd740172f23ad6f67d356ee394850a754a908271199b63c3bdc234` | 一致 |
| `frozen_evaluator.py` | `c7952d9becd81e7b722cdcbb9dd78a50c95ef48849e6d2e4e1d7963f1cc757dc` | 一致 |
| `pilot_data.py` | `49c8ba303bf37ef315515e25c6f10e66625c1289ce557e5b2025905cc056c125` | 一致 |
| `frozen_eval.jsonl` | `2cde0d19f7ae1341c71e87359b199f49d5b4b6f1f42be9eebd57ce5eea706061` | 一致 |
| `train.jsonl` | `79e127c51c0be0ebfbce3ca43395ce124d0d18f95747ad80a6b6d351da827732` | 一致 |
| `test_runtime.py` | `f519256f62f1f3b09350fd9fe0fc81c84f389f6f0c2279c75b41c7e6d16fbbfe` | 非対象 |
| `frozen_eval_manifest.json` | `4d60203a446c46e583386db27822ee3616df8b9a790464f2a24a22f5e549b494` | 一致 |
| `historical_roots.json` | `a56a2c9a9ea45508f03f286bca64873dbda393f249f6b5a763d5b383830d02c2` | 一致 |
| `supervise_runtime.py` | `ead9451af6de9a57a33099902564a59fa135dc95e881cddbd997ae1b69b2c050` | 一致 |
| `runtime_revision_receipt.json` | `ba770ddb7b184387a24d5cf8ef4c6003d57657da40373c84d6dfb97d3cad6177` | 非対象 |
| `tdd-runtime-final-green.log` | `3b79ee3796f9cc7428289118f66e6525270984e04a9889177cc35cb73b58a7e1` | 非対象 |
| `pilot002-launch.json` | `39b157099cd05684d0ff6369dd605c1b236e38c79d5af66940a9f86880ceb34f` | 非対象 |
| `pilot002-exit.json` | `1c2e31aaeb0606e6497a0b911346ee75e0454d32a8b5218c9db0e18df8fa22ad` | 非対象 |
| `pilot002.log` | `c406fedc9589e24170e4cab31b42b07b67e5315e0ab0649fd0ee976f74883006` | 非対象 |

すべて上記対象rootからの相対名。JSONには各absolute_path・bytes・linesを収録。元runの差分参照ファイル:

- `C:\Users\downl\Documents\New project\hermes-agent\rsi\experiments\hakua-epistemic-r3-qlora-pilot\pilot_train.py` — `e6c2ef88a8c16cee7efccba0608f7ad7f202f963ab664c1b6fb54cbbe4988049`
- `C:\Users\downl\Documents\New project\hermes-agent\rsi\experiments\hakua-epistemic-r3-qlora-pilot\frozen_evaluator.py` — `fa2a44dc4d257ca0900cc061eb89e82c2879efc5248f0ed6b69a618f618630ac`

## 許される主張と保留事項

- 許される: 局所loss shiftとfreeze hashの静的整合性が確認された
- 許される: 保存tiny FP32テストlogが2件成功を示す
- 許される: 起動記録がCLIエラーを示す
- 許される: 将来の別runが完了した場合も事前定義されたchoice proxy差だけを限定報告する
- 許されない: Level 3
- 許されない: formal safety認証
- 許されない: 実coding/tool execution非回帰認証
- 許されない: 現行Hermes/配備モデル改善
- 許されない: 未解決memory/revisionをresolved扱い
- 許されない: r2 artifact監査PASSまたは人間正式承認の代替

**保留**: 元memory/revisionの真正な原記録 / 共有環境でのCUDA NF4/LoRA end-to-end実行結果 / 基底checkpoint配布revisionの実ファイル同定（本レビュー未検査） / 保存adapterのfresh-load後再現性 / 幅広い能力と自由応答行動 / 別processの現在状態

## レビュー中の制限・問題

- 一部train表示がstdout上限で切れたため、欠けた行だけを再取得した。全JSON行の解析は完了。
- eval個別hashはprompt_hashや全record hashではない。探索確認でcanonical {options,prompt}と分かり72件全一致。途中のfalse結果はhash方式の相違でありintegrity欠陥とは報告しない。

## 出力（唯一の許可書込み）

- `C:\Users\downl\Documents\New project\hermes-agent\rsi\experiments\hakua-epistemic-r3-qlora-pilot-runtime-r2\review\independent_runtime_review.json`
- `C:\Users\downl\Documents\New project\hermes-agent\rsi\experiments\hakua-epistemic-r3-qlora-pilot-runtime-r2\review\independent_runtime_review.md`
