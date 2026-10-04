# 独立ランタイム科学・コードレビュー（runtime-r3）

- 作成: 2026-10-04T11:07:05.932645+00:00（UTC）
- 対象絶対パス: `C:\Users\downl\Documents\New project\hermes-agent\rsi\experiments\hakua-epistemic-r3-qlora-pilot-runtime-r3`
- **現snapshotの結論: NO_CURRENT_CRITICAL_DEFECT_IDENTIFIED_IN_REVIEWED_SCOPE。これはPASS認証ではない。**
- 元来歴UNRESOLVED、正式承認PENDING、NOT_CERTIFIED。Level 3、formal safety、配備モデル改善は主張しない。
- 読み取り専用のcode/methodology review。学習・test・修復・process操作はしていない。r2成果物の再監査でもなく、results/weight_change/adapter binaryの認証でもない。

## 要約

runtime-r2の起動引数不整合と9対8項目manifest不整合は、operatorのruntime-r3改訂で解消。trainer/evaluator/data/testコードとtrain/evalの本体bytesはr2と同一。8宣言凍結ファイルの全hash、旧方式72個別hash、新NFKC方式72個別hashは全て一致する。旧prompt_hash比較のfalseは方式違いであり、評価破損ではない。

確認中に保存pilot003-exit.jsonが存在し、returncode=0/timed_out=false。保存実行logはoptimizer_step=1..32、親・子・親repeatの72/72とSTOP_AND_REPORTを記録。ログのsignal=Falseを観測したが、結果score vectorは読んでいない。正常終了は実装経路の実行記録で、能力改善やadapter真正性の独立認証ではない。現在の全process状態は主張しない。

## 前改訂の重大所見（解消履歴として保持）

### C1 [CRITICAL, r2限定] 起動引数名の不整合で、記録されたpilot002は学習に到達していない

- 元影響: 保存されたこの起動の失敗は観測済み。これはoptimizer、親評価、量子化モデル読み込みより前のCLI停止であり、学習完了や重み更新の証拠にはならない。別プロセスの現在状態は調査していない。
- r3解消根拠: runtime-r3/supervise_runtime.py:23 は --run-id pilot003。
- r3解消根拠: pilot003の保存logはCLIを通過し親評価・学習へ到達。
- 状態: `RESOLVED_BY_OPERATOR_REVISION_NOT_BY_REVIEWER`。元reviewとrunを上書きしない。

### C2 [CRITICAL, r2限定] 凍結マニフェスト9項目と学習コード8項目の完全一致条件が矛盾

- 元影響: C1を外部から直しても、今回の凍結ファイルのままではPREFLIGHT以前に停止する静的に必然の第2障害。チェックはfail-closedであり、評価汚染ではない。failure.jsonもこの経路では保存されない。現pilot002でこの経路が実行されたとは言わない。
- r3解消根拠: runtime-r3/frozen_inputs.jsonは8項目。AST抽出protected_namesの集合と一致。
- r3解消根拠: supervisorはexecution_manifest.jsonに別hashとして記録。
- 状態: `RESOLVED_BY_OPERATOR_REVISION_NOT_BY_REVIEWER`。元reviewとrunを上書きしない。

## 問数と分離（実ファイル優先）

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

- permission除外epistemic40問、permission8問。コード内epistemic集合はpermission込み48問。coding/tool各12問は選択肢proxy。
- train64例=4 reconstruction roots各16例。全136 IDは一意。train/eval IDとNFKC/空白正規化prompt+options hashの重複0。
- 4導入句を除き4対象名+番号を置換するとtrain4template群。evalの8対象名を置換してoptions順序を無視すると36群（6つの8問family各2群）。この36は独立サンプル数の推定ではない。
- train/eval意味・template重複の排除ではなく、近接転移/回答様式学習の可能性が残る。

## 現在の所見と妥当性限界

### V1 [HIGH] 64学習例は4ルートの反復で、72評価例も独立72事例ではない

状態: `LIMITATION`

- train.jsonlは4 root_id各16件、順序無視の選択肢集合は4種類。
- 4導入句を削除し、4対象名+番号を置換し、選択肢順序を無視すると学習は4群（各16件）。
- 評価の8対象名を置換し、選択肢順序を無視すると36群。6つの8問familyは各2群（各4件）。この36は独立サンプル数の推定ではない。
- train-cand-asr-censoring-00 と eval-censoring-00 は全打切り→N/Aの同じ教訓。train-cand-checker-overgeneralization-00 と eval-provenance-00 は未確認正本を捏造しない教訓を共有。

**影響**: ID/NFKC完全一致排除は成立するが、意味・テンプレートの分離や外的妥当性は成立しない。改善があっても近接転移・回答様式の学習で説明でき、64独立経験の蓄積とは言えない。

**取扱い/将来の対策（本レビューでは実施しない）**: 今のpilotを記述的proxyとして扱う。将来の広い主張には独立出典、ルート・テンプレート単位の分割、反事実と難しい妥当なdistractorを含む別評価が必要。現evalは変更しない。

### V2 [HIGH] A/B/C/D条件付き選択を、自由応答・安全行動・実行能力と同一視できない

状態: `LIMITATION`

- frozen_evaluator.py:58-83 は1 tokenラベルを検査し、4ラベルのlogitだけでargmaxと条件付きsoftmaxを計算。
- unconstrained_first_tokenとformat_first_token_rateは別に記録されるが、pilot_train.py:270-275 のsignal判定には入らない。
- frozen_eval.jsonl:49-60 codingはPython式の結果の多肢選択。61-72 toolも次の判断の多肢選択。
- coding 12問には共通の極端なdistractor（例外が必ず発生する/None/任意の文字列）があり、specific answerだけで判別できる項目がある。

**影響**: 全ラベルが低確率でも4択の正解を選べる。出力形式の悪化があってもproxy signalが真になり得る。コード生成・テスト実行・API操作・権限違反率の非回帰を証明しない。

**取扱い/将来の対策（本レビューでは実施しない）**: conditional choice proxyの点数と明記し、coding/tool execution回帰なし、formal safety、現行Hermes改善を主張しない。

### V3 [HIGH] 閾値とpaired検定は探索的な運用基準で、統計的な能力改善認証ではない

状態: `LIMITATION`

- protocol.json:51-58 は1 familyでdelta>=0.05、各family非回帰、permission親子とも全正解、coding/tool許容0.01。
- 各8問群の1正解差=0.125なので0.05閾値は実質1問純増。各12問群の1正解差=0.08333333333333333なので0.01許容では正解数の純減は認められない。
- pilot_data.py:93-110 は同じIDの正誤discordanceによる二側exact binomial/McNemar型値を計算。1件だけ一方向改善ならp=1.0。
- pilot_train.py:243 はpermissionをepistemic集合に含めるが、親子8/8条件ではそのdeltaは0となる。permissionを除くepistemicは40問。p値はsignalの条件でない。

**影響**: 1問の差だけでsignal条件の一部を満たせる。相関テンプレート、多family探索、多重比較未補正、1seedにより推測統計の一般化が弱い。family平均非回帰は改善と悪化が同数なら個別項目の後退を許す。

**取扱い/将来の対策（本レビューでは実施しない）**: gain/lossと母数・定義を併記し、p値やproxy signalをLevel 3へ昇格させない。

### V4 [MEDIUM] 基底の前後同一性はよい対照だが、モデル出所と保存adapterの再現性の認証ではない

状態: `LIMITATION`

- pilot_train.py:38-46 はadapter以外のparameter、buffer、packed quant_stateをhash化。148-152はtrainableがLoRA A/Bだけと確認。
- 153-156 と216-234で学習前後のメモリ基底を比較。93-94と253-255はBASE_ROOT直下ファイルの前後hashを比較。
- protocol.json:8-9のQwen ID/revisionはメタデータ。pilot_train.py:112-134はlocal BASE_ROOTから読み、既知の配布checkpoint hashへの照合やconfig architecture確認はこのコードにない。
- child評価は237で同じメモリ中モデルを使う。214-215の保存adapterをfresh processへreloadしては評価していない。

**影響**: 前後一致はこのNF4/prepared backboneの変化なしを支持するが、元配布revisionと同じ内容、未量子化公開baseとの性能同等、履歴真正性を証明しない。直下ファイル検査は再帰的directory監査ではなく、保存・再load後のchild再現性も未測定。pilot003の完了ログは実行経路到達を示すが、本レビューはweight_changeやresults内容、adapter binaryを再検証していない。

**取扱い/将来の対策（本レビューでは実施しない）**: run完了後でも観測範囲を限定する。保存artifactのreload・別環境での再現性や配布SHAとの同定は別の承認された検証とする。

### V5 [MEDIUM] 疎logit方式の数式は整合するが、tiny FP32テストの成功はNF4本番全体の成功ではない

状態: `BOUNDED_POSITIVE`

- frozen_evaluator.py:25-34 はprefixを-100、gold token+EOSだけを教師ラベルとし、空/切り捨てを拒否。
- 42-52でlabels[0,1:]の非-100の添字jをlogit位置とし、labels[0,j+1]へcross_entropy(mean)。1-sequence causal shiftと一致する。
- test_runtime.py:9-19 はtiny Qwen CPU FP32の全logitとlast-token比較（rtol1e-5/atol1e-7）および全語彙argmax一致。4ラベルargmaxを個別assertはしていない。
- 22-36はtiny eval-mode FP32モデルのsparse lossとlossのgradientを比較（loss rtol1e-5, gradient rtol1e-4, atol1e-7）。tdd-runtime-final-green.logは2 passed,4 warningsを記録。
- runtime-r3/runs/pilot003/execution.log:9-54 は学習32steps、子/親repeat各72問と完了を記録。test_integrity.log:2 は9 passed。いずれもreviewer再実行でない。

**影響**: off-by-one欠陥は見つからない。gold+EOSを教師にするMC SFTであり、文章の訂正行為を直接生成して学習する設計ではない。tiny 2テスト自体は実checkpoint、CUDA NF4/bf16、LoRA/dropout train mode、checkpointing、tokenizer整合、optimizer end-to-endの比較検証ではない。pilot003の既存ログは実学習経路に32stepsと3回の72問評価を記録するが、bit-identical等価性の一般保証や保存adapterの独立監査ではない。

**取扱い/将来の対策（本レビューでは実施しない）**: tiny equivalenceを実装局所の数値近似検査として報告する。本レビューではtestを再実行しない。

### V6 [MEDIUM] 元memory/revisionの来歴は引き続きUNRESOLVED

状態: `LIMITATION`

- historical_roots.json:2-4 は historical_reconstruction / original_memory_revision_status=UNRESOLVED。
- 4ルートのsource_record_statusはいずれもunresolved。train.jsonlはルートIDへの参照のみで元記録を解決しない。
- protocol.json:60-65 はproducer-authored gold、独立semantic gold監査なし、r2 verdict NEEDS_REVISIONを明記。

**影響**: 本レビューはローカル8ファイルと補助証跡のcode/methodology review。r2成果物の再監査、原記録の追跡解決、人間承認の代替ではない。synthetic authoring metadataは独立した作成者のgoldや歴史的真正性の証拠ではない。

**取扱い/将来の対策（本レビューでは実施しない）**: 元来歴のUNRESOLVED、正式承認PENDING、NOT_CERTIFIEDを維持する。

### V7 [LOW] latency toleranceは実装されたacceptance gateではない

状態: `LIMITATION`

- protocol.json:55-56 はlatency_relative_tolerance=0.05、shared-GPU descriptive timing。
- frozen_evaluator.py:64-85は同期したsingle forwardを計時。tokenization時間と外部処理は含まない。
- pilot_train.py:270-275 のsignal判定にlatency_relative_toleranceは使用されず、282-286でforward_secondsを報告するだけ。

**影響**: 親→学習→子→親repeatという逐次測定はwarm-upと共用GPU負荷の交絡がある。5%非劣性を満たした、live latency regressionなしとは主張できない。これはprotocol自体がdescriptiveとする限り探索的pilotを否定する主欠陥ではない。

**取扱い/将来の対策（本レビューでは実施しない）**: latencyは記述値として扱い、閾値が検査済みとの表示をしない。

### R1 [LOW] 読取threadのUTF-8 decode例外が記録されているが、pilot003は完了を記録

状態: `OBSERVED_WARNING`

- pilot003.log:3-13 に subprocess._readerthread の UnicodeDecodeError(byte 0x82)。
- pilot003.log:14-66とpilot003-exit.json:5は、その後の評価/32steps/STOP_AND_REPORTとreturncode=0を記録。

**影響**: 警告を隠さず残すべき。これだけで学習破損と断定も、例外の根因が解決したと断定もできない。内部thread例外は主process終了コードだけでは検出できない一般的な報告限界もある。

**取扱い/将来の対策（本レビューでは実施しない）**: 元ログを保存し、Windows runtime調達/encodingの観測上の限界として明記する。本レビューは環境を修理しない。

## response lossとpaired gate

`positions=nonzero(labels[0,1:]!=-100)` は教師token直前のlogit位置。targetは `labels[0,positions+1]`。`[-100,-100,-100,-100,5,6]`ならlogit3,4→target4,5（5,6）。1 sequenceのmean CE/causal shiftと整合しoff-by-oneを認めない。MC gold+EOS教師であり、自由訂正文生成の学習ではない。tiny FP32等価検査は近似toleranceでありNF4/LoRA bit-identical一般保証ではない。

同じNF4/prepared backboneで親disable→学習→子enable→親repeatは有用なpaired設計。8問群の1正解純増は0.125で、0.05閾値は1問で足りる。1件の一方向discordanceではexact二側p=1.0。12問群の1正解差は0.08333333333333333で0.01許容は純減なし。family平均非回帰は個別問題の後退と改善の相殺を許し、pはsignal gateでない。permissionは親子8/8必須なのでdelta0で、40問の残るepistemicが改善候補。相関template/多重比較未補正/1seedにより能力認証はできない。

## 基底・保存物・latencyの境界

コードはLoRA A/Bのみtrainableを確認し、adapter以外のparameter/buffer/packed quant_stateの前後hash、checkpoint直下ファイル前後hashを比較する。これはそのprepared NF4 backboneの安定性検査で、公開Qwen revisionの真正性や未量子化baseとの同等性ではない。保存adapter reload検査もない。本レビューはweight_change/results/binaryを独立再検証せず、完了ログとコードの到達範囲を分けて報告する。

latency 5% toleranceはcode gateに使用されず、同期single-forward timingの記述値だけ。順次評価・warm-up・共用GPU負荷の交絡があり、実latency非劣性を認証しない。

## 凍結hashの正確な方式と範囲

- r2: canonical UTF-8 JSON `{prompt,options}`、sort_keys=True、compact separators、ensure_ascii=FalseのSHA-256。全72一致。
- r3: NFKC→空白collapse→stripした `prompt + LF + LF.join(options)` のUTF-8 SHA-256。全72一致。
- train/eval bytes/gold/thresholdは不変。metadata registry方式だけを新revisionとして記録した。
- 個別hashはgoldを含まないがevalファイル全体SHAは含む。作成時系列、署名、writer identity、ACL、外部署名による真正性を証明しない。
- supervisorは8 trainer入力へ混入させずexecution_manifestに別hashとして記録。manifest/test_runtime自身はtrainer凍結リスト対象外。

## 検査ファイル（absolute pathと正確なSHA-256）

以下は対象root `C:\Users\downl\Documents\New project\hermes-agent\rsi\experiments\hakua-epistemic-r3-qlora-pilot-runtime-r3` からの相対名。JSONに各absolute_pathを収録。

| ファイル | SHA-256 | trainer凍結一致 |
|---|---|---|
| `protocol.json` | `71c3f137c53520ca84abb1bc220daa5e746c7dafb14859a03ca900d8dcf512ff` | 一致 |
| `frozen_inputs.json` | `244486f0c8e5979783e17a31a61edeb5906695e3b6988064d1026e67c8aa3933` | 対象外 |
| `pilot_train.py` | `d0449eeb1bfd740172f23ad6f67d356ee394850a754a908271199b63c3bdc234` | 一致 |
| `frozen_evaluator.py` | `c7952d9becd81e7b722cdcbb9dd78a50c95ef48849e6d2e4e1d7963f1cc757dc` | 一致 |
| `pilot_data.py` | `49c8ba303bf37ef315515e25c6f10e66625c1289ce557e5b2025905cc056c125` | 一致 |
| `frozen_eval.jsonl` | `2cde0d19f7ae1341c71e87359b199f49d5b4b6f1f42be9eebd57ce5eea706061` | 一致 |
| `train.jsonl` | `79e127c51c0be0ebfbce3ca43395ce124d0d18f95747ad80a6b6d351da827732` | 一致 |
| `test_runtime.py` | `f519256f62f1f3b09350fd9fe0fc81c84f389f6f0c2279c75b41c7e6d16fbbfe` | 対象外 |
| `frozen_eval_manifest.json` | `906f24df0f0605febaabd3956a70956f0c7a059f905531b0555674f83184a1fa` | 一致 |
| `historical_roots.json` | `a56a2c9a9ea45508f03f286bca64873dbda393f249f6b5a763d5b383830d02c2` | 一致 |
| `supervise_runtime.py` | `eabcc62791fc1e9ceb0d3b7f2b0ab3ea9d6f46c6165b69586c6004e35f31a601` | 対象外 |
| `hash_comparator_correction.json` | `17177a632c0005aa1b3a22a342b2effe56106fe6a2ec881ab54c04fd62c72030` | 対象外 |
| `execution_manifest.json` | `4a85de7f650a0945b389f10b0f2cc4f08f714d2c7eed22a351a25eb0def511a1` | 対象外 |
| `revision_receipt.json` | `97afa48bce2f73b3b6a851efcbbad02ca089205180200f1ee6cbfbe1cbd26a6b` | 対象外 |
| `prelaunch_verification.json` | `8c96c69d99132b1979b32c6be3a342965f37af25f50e8948c07f15afffc2d840` | 対象外 |
| `test_integrity.py` | `9c374216caa7c68b770978b7c3c86b4652f1c86f84277910c4d867748a655176` | 対象外 |
| `test_integrity.log` | `028c01fe5c28a82ee0f8a97511c96684b84266f7e0bb9b53f8eb68c9afda29bd` | 対象外 |
| `pilot003-launch.json` | `4b2950cf10770c7712dab95f18708850edb8b05750079548b3f27a22d8b2041b` | 対象外 |
| `pilot003-exit.json` | `a11685ef4d775bf470f4facb34b0090af9916fb3be1632bffd679bc8f5eb9545` | 対象外 |
| `pilot003.log` | `a08fcb794d09a58ffb0c31bd61c3959ed8653f35b670a2f77a4b72c11d9ceed6` | 対象外 |
| `runs/pilot003/execution.log` | `f286e5de15fd86a37c3d4b5f7e1acb914d1597283d16560301f39b6785ff38e2` | 対象外 |

### 保存r2の参照証跡（現r3ファイルではない）

- `C:\Users\downl\Documents\New project\hermes-agent\rsi\experiments\hakua-epistemic-r3-qlora-pilot-runtime-r2\protocol.json` — `59ef599d16ad126e5fd30cec51b9c54256ce08e8c6e9dc77041df3153ee7b5c4`
- `C:\Users\downl\Documents\New project\hermes-agent\rsi\experiments\hakua-epistemic-r3-qlora-pilot-runtime-r2\frozen_inputs.json` — `2f4032e511b08357d7ba8ff1831a966706fa4d8752ac0738ff738da62a758c81`
- `C:\Users\downl\Documents\New project\hermes-agent\rsi\experiments\hakua-epistemic-r3-qlora-pilot-runtime-r2\frozen_eval_manifest.json` — `4d60203a446c46e583386db27822ee3616df8b9a790464f2a24a22f5e549b494`
- `C:\Users\downl\Documents\New project\hermes-agent\rsi\experiments\hakua-epistemic-r3-qlora-pilot-runtime-r2\pilot_train.py` — `d0449eeb1bfd740172f23ad6f67d356ee394850a754a908271199b63c3bdc234`
- `C:\Users\downl\Documents\New project\hermes-agent\rsi\experiments\hakua-epistemic-r3-qlora-pilot-runtime-r2\frozen_evaluator.py` — `c7952d9becd81e7b722cdcbb9dd78a50c95ef48849e6d2e4e1d7963f1cc757dc`
- `C:\Users\downl\Documents\New project\hermes-agent\rsi\experiments\hakua-epistemic-r3-qlora-pilot-runtime-r2\supervise_runtime.py` — `ead9451af6de9a57a33099902564a59fa135dc95e881cddbd997ae1b69b2c050`
- `C:\Users\downl\Documents\New project\hermes-agent\rsi\experiments\hakua-epistemic-r3-qlora-pilot-runtime-r2\pilot002.log` — `c406fedc9589e24170e4cab31b42b07b67e5315e0ab0649fd0ee976f74883006`
- `C:\Users\downl\Documents\New project\hermes-agent\rsi\experiments\hakua-epistemic-r3-qlora-pilot-runtime-r2\pilot002-exit.json` — `1c2e31aaeb0606e6497a0b911346ee75e0454d32a8b5218c9db0e18df8fa22ad`
- `C:\Users\downl\Documents\New project\hermes-agent\rsi\experiments\hakua-epistemic-r3-qlora-pilot-runtime-r2\tdd-runtime-final-green.log` — `3b79ee3796f9cc7428289118f66e6525270984e04a9889177cc35cb73b58a7e1`
- `C:\Users\downl\Documents\New project\hermes-agent\rsi\experiments\hakua-epistemic-r3-qlora-pilot-runtime-r2\review\independent_runtime_review.json` — `9b491341630954ce46b4f2267883509c4044fcec8e164ecd3e2471b23dff7e86`
- `C:\Users\downl\Documents\New project\hermes-agent\rsi\experiments\hakua-epistemic-r3-qlora-pilot-runtime-r2\review\independent_runtime_review.md` — `3a9ef85728a69e92fbdd8a8d64e8e1f6488b08cfe8f88bd2e6840131c3c5376a`

## 主張の境界

- 許される: 局所loss shiftと8ファイルfreeze hashの静的整合性が確認された
- 許される: 先のCLI/freeze集合2障害はruntime-r3で解消されている
- 許される: 保存pilot003ログ/exitが32steps・3回の72問評価・正常終了STOP_AND_REPORTを示す
- 許される: 保存ログのexploratory signalはFalse。点数vectorを本レビューでは読んでいない。
- 許されない: Level 3
- 許されない: formal safety認証
- 許されない: 実coding/tool execution非回帰認証
- 許されない: 現行Hermes/配備モデル改善
- 許されない: 未解決memory/revisionをresolved扱い
- 許されない: r2 artifact監査PASSまたは人間正式承認の代替

**保留**: 元memory/revisionの真正な原記録 / 基底checkpoint配布revisionの実ファイル同定（本レビュー未検査） / 保存adapterのfresh-load後再現性 / 幅広い能力と自由応答/実coding/tool execution行動 / binary/weight_change/resultsの独立artifact検証 / 別processの現在状態

## レビュー中の問題

- ユーザーのmid-turn更新で対象が保存済みruntime-r2からruntime-r3へ変わったため、新規の許可出力だけを作成する。
- 読取時にpilot003は保存exit/log上で既に完了。runningという以前の状況を現在状態として引き継がない。
- Windows subprocess readerthreadにUnicodeDecodeErrorの保存警告がある。process全体はreturncode0を記録。
- 旧eval個別hashはcanonical {prompt,options}で正しく、prompt_hashとの比較falseを破損と誤認しない。

## 出力と保存方針

- 新規JSON: `C:\Users\downl\Documents\New project\hermes-agent\rsi\experiments\hakua-epistemic-r3-qlora-pilot-runtime-r3\review\independent_runtime_review.json`
- 新規Markdown: `C:\Users\downl\Documents\New project\hermes-agent\rsi\experiments\hakua-epistemic-r3-qlora-pilot-runtime-r3\review\independent_runtime_review.md`
- 保存r2 JSON: `C:\Users\downl\Documents\New project\hermes-agent\rsi\experiments\hakua-epistemic-r3-qlora-pilot-runtime-r2\review\independent_runtime_review.json`
- 保存r2 Markdown: `C:\Users\downl\Documents\New project\hermes-agent\rsi\experiments\hakua-epistemic-r3-qlora-pilot-runtime-r2\review\independent_runtime_review.md`
- 既存出力は上書きせず、新規r3の2ファイルだけを書いた。
