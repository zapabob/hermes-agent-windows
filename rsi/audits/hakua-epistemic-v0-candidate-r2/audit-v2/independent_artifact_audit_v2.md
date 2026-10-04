# Hakua-RSI r2 独立成果物監査 v2

## 結論: NEEDS_REVISION

これは別agent contextによる**独立artifact audit**であり、human approvalではありません。v1のPASSは継承せず、封印ZIPを読み直し、隔離コピーの実compiler/schema/testsで確認しました。対象を修理していません。

- 対象: `C:\Users\downl\Downloads\hakua-epistemic-v0-candidate-r2-audit-bundle.zip`
- ZIP SHA-256（前後一致）: `52b4cdd858a7dc0bee15f38c41f6abdbd5cafb1d7594bc94f5c5f188074ad331`
- artifact_revision: `2`
- 親SHA-256: `5ab281294b79a33565e6f1b0705995a542cb0972b9847aa42278692c3af368aa` / 親監査: `NEEDS_REVISION`
- inherited_audit_verdicts: `false`
- human_approval: `PENDING` / automatic_promotion_allowed: `false`
- activation: `STOP_AND_REPORT` / independently-audited Level 1: `false` / Level 2: `NOT_REACHED`

## 6軸の新規判定

| 軸 | 判定 |
|---|---|
| causal_validity | NEEDS_REVISION |
| claim_strength | PASS |
| generalizability | NEEDS_REVISION |
| instruction_boundary | PASS |
| provenance_integrity | NEEDS_REVISION |
| artifact_integrity | NEEDS_REVISION |

### causal_validity: NEEDS_REVISION
コード抜粋、保存済み訂正メッセージ、ASRの打切りmetadata、PID観測は実元sourceに照合できた。しかし元memory/revision 4件が未解決で、元信念→revisionの実履歴全鎖を確認できない。ASR runは環境中断を跨ぐ記述的証拠のみで因果効果を確定できず、checker教材の当時の成果物不存在も独立した同時点全件証跡がない。訂正方向の妥当性と因果認証を分離する。

根拠: `R09#/references`, `R09#/message_exports`, `R09#/historical_observations`, `source_provenance.json#/records`, `evidence/asr-wire-observations.json#/source_freeze_status`, `source_snapshot.json#/candidates/3`

### claim_strength: PASS
実sourceとの新規照合により、fence存在の確認とauthority-semantics仮説が本文で分離され、asserted_with_caveatと整合する。ASRはCの3打切り/decision_valid=0を再集計しN/A、PIDはsocket owner未確認のleading candidate/hedged、checkerは保存された自己撤回だけを述べself_reportedへ限定する。PASSは現4行の表現強度の校正に限り、ID解決、行動改善、因果効果の認証ではない。

根拠: `R09#/historical_git`, `R09#/historical_observations/0/counts`, `R09#/message_exports`, `source_snapshot.json#/candidates`, `evidence/pid-observations.json#/anomaly/process_attribution`

### generalizability: NEEDS_REVISION
formatterはtransient factsと引用命令をassistant targetに直結せず、明示review map+固定1文のPREVIEW_ONLYへ分離することを実関数で確認した。一方、実snapshotのholdout registryは空でID照合だけ。frozen evaluation holdout、content/hash overlap監査、未知タスク/モデルへの転移測定がなく、有限語彙previewから4教材の汎化や学習効果を認証できない。

根拠: `R06#/checks`, `R13#/observations`, `source_snapshot.json#/holdout_registry`, `source_snapshot.json#/holdout_registry_scope`, `FORMATTER_CONTRACT.md:33-63`

### instruction_boundary: PASS
同梱Draft202012 schemaを実適用し4行のquoted_data/noneを確認した。permission/system-role違反、holdout、contradictionを実compilerで拒否し、formatterでは閉じfence+system風命令+PID/port/commit/dateを含むraw文面がsidecarだけに保持され、assistant targetは固定手続き文だけになる。偽boolean・raw target・transient scopeはdeny、学習許可false・人間承認PENDINGを維持する。PASSはStage-1データ/preview構造境界に限定し、モデルが引用命令に従わないというlive behavioral保証ではない。

根拠: `R06#/checks`, `candidate.schema.json#/properties/action_permission`, `candidate.schema.json#/properties/content_role`, `formatter.py:16-95`, `FORMATTER_CONTRACT.md:42-63`

### provenance_integrity: NEEDS_REVISION
19のcandidate→reference digest/linkageは一致。14 messageのlocator/full-source hash/文字spanと関連memory 2件のcanonical recordは現在のread-only DBで一致し、歴史git/probe sourceも一致する。しかし元4 alias/revisionは44の明示identity-column照会で一致0、memory_record_ref/revision_record_refはnull。関連records114695/114709は別IDかつbelief_version1で、元revision3/2の解決にはならない。compilerもsource ERROR・全体NEEDS_REVISIONを新規に返す。

根拠: `R09#/source_lookup`, `R09#/references`, `R09#/related_memory_exports`, `R06#/fresh_report/checks/source_provenance`, `SOURCE_LOOKUP.json`, `source_provenance.json#/records`

### artifact_integrity: NEEDS_REVISION
ZIP identity、49/49 LINEAGE file digestとbody digest、canonical schema/snapshot、compiler、train、manifest-body、25 parent保全digest、29 revision差分は一致。実default CLIはexit2で4 accepted/0 rejectedを生成し同梱dataset全5ファイルとbyte一致、27 unittestと独立63 assertions、10 fixtures/7拒否コード、実入力24順列も成功した。旧版の固定PASS/到達不能reject/default path欠陥は新規実行で解消確認。ただしfence-sourceのlast_line=403は空の終了境界行を指し、半開文字spanが実際に含む最終行は402。inclusive/exclusive行番号規約が未記載のため全span metadataを無条件PASSとしない。bytes破損のFAILではなく小さな契約明確化待ち。

根拠: `R02`, `R03`, `R05`, `R06`, `R09#/historical_git`, `R10`, `R12`, `R13`, `evidence/fence-source.json#/last_line`

## 実行receipt（生産者ログを結果の代用品にしていない）

- shipped unittest: **27 tests, OK**, exit 0。skip/error/failure 0。
- 独立assertion: **63/63**。62 main + 1追加、2つのscope observationはassertion数へ加算しない。
- 同梱synthetic fixture: **10ケース、7 reject codes**を実compilerで再実行。空の実rejected_examplesだけで拒否成功と判定していない。
- 実4行の入力順列: **24通り**、dataset hash/出力順はそれぞれ1種類。有限snapshotの結果であり一般証明ではない。
- default CLI: **exit 2**、4 accepted/0 rejected、source provenance ERROR、NEEDS_REVISION。同梱dataset 5ファイルと新規生成結果がbyte一致。これは意図通りの未解決sourceブロックでありruntime crashではない。
- report-derived mutants: schema-invalid→schema_result FAIL、holdout true→contamination true、contradiction true→combined FAIL、body/hash/manifest改ざん→output integrity FAIL。不可用checkはnull/ERROR、空datasetはFAIL。

### `shipped_unittest`
- cwd: `C:\Users\downl\Documents\New project\hermes-agent\tmp\probes\r2-auditor\audit-v2-cb8ab69a69564fd8bb99182ae6aeba83\execution-copy`
- exit: `0` / duration: `6.312s`
```text
"C:/Users/downl/Documents/New project/hermes-agent/.venv/Scripts/python.exe" -B -m unittest -v test_compiler
```
- counts: `{"tests_run": 27, "passed": 27, "failures": 0, "errors": 0, "skipped": 0}`

### `default_compiler`
- cwd: `C:\Users\downl\Documents\New project\hermes-agent\tmp\probes\r2-auditor\audit-v2-cb8ab69a69564fd8bb99182ae6aeba83`
- exit: `2` / duration: `0.516s`
```text
"C:/Users/downl/Documents/New project/hermes-agent/.venv/Scripts/python.exe" -B "C:\Users\downl\Documents\New project\hermes-agent\tmp\probes\r2-auditor\audit-v2-cb8ab69a69564fd8bb99182ae6aeba83\execution-copy\compiler.py"
```
- counts: `{"accepted": 4, "rejected": 0, "emitted_files": 5}`

### `independent_behavioral_probes`
- cwd: `C:\Users\downl\Documents\New project\hermes-agent\tmp\probes\r2-auditor\audit-v2-cb8ab69a69564fd8bb99182ae6aeba83`
- exit: `0` / duration: `3.094s`
```text
"C:/Users/downl/Documents/New project/hermes-agent/.venv/Scripts/python.exe" -B "C:\Users\downl\Documents\New project\hermes-agent\tmp\probes\r2-auditor\audit-v2-cb8ab69a69564fd8bb99182ae6aeba83\independent_probes.py"
```
- counts: `{"top_level_assertions": 62, "passed": 62, "failed": 0, "shipped_fixtures": 10, "reject_codes": 7, "permutations": 24}`

### `read_only_source_validation`
- cwd: `C:\Users\downl\Documents\New project\hermes-agent\tmp\probes\r2-auditor\audit-v2-cb8ab69a69564fd8bb99182ae6aeba83`
- exit: `0` / duration: `0.422s`
```text
"C:/Users/downl/Documents/New project/hermes-agent/.venv/Scripts/python.exe" -B "C:\Users\downl\Documents\New project\hermes-agent\tmp\probes\r2-auditor\audit-v2-cb8ab69a69564fd8bb99182ae6aeba83\source_validation.py"
```
- counts: `{"source_identity_queries": 44, "exact_alias_matches": 0, "message_exports": 14, "related_memory_exports": 2}`

### `additional_scoped_probes`
- cwd: `C:\Users\downl\Documents\New project\hermes-agent\tmp\probes\r2-auditor\audit-v2-cb8ab69a69564fd8bb99182ae6aeba83`
- exit: `0` / duration: `1.156s`
```text
"C:/Users/downl/Documents/New project/hermes-agent/.venv/Scripts/python.exe" -B "C:\Users\downl\Documents\New project\hermes-agent\tmp\probes\r2-auditor\audit-v2-cb8ab69a69564fd8bb99182ae6aeba83\additional_probes.py"
```
- counts: `{"top_level_assertions": 1, "passed": 1, "scope_observations": 2}`

## 出典・同一性の実測

- LINEAGE: **49/49** file digest一致、未列挙ファイル0（LINEAGE自己除外）。lineage body、canonical schema/snapshot、compiler、train、manifest bodyも一致。
- 親保全: 記録のcurrent paths **25/25** digest一致。親ZIP snapshotとのprovenance ID/type保存、revision diff **29/29** before/after一致。
- candidate reference: **19/19** file digest/linkage一致。
- 14 message exports: 全て現在のread-only state.dbでlocator、全文source hash、source長、文字spanが一致。reasoning columnsは選択していない。
- 関連memory 114695/114709: export canonical hash/現在DB projectionが2/2一致。ただし別ID、belief_version1で元aliasとrevision3/2を解決しない。
- 原probe 2件のsource hash、ASR projection/freeze metadata、PID観測/anomalyが一致。歴史git blob/excerptも一致。
- ASRの再集計: A attempted3/transport2/decision2、B3/2/2、C3/3/0（length3）、D3/1/1。CのASRはN/A。中断runを因果比較に使用しない。

### 元memory/revisionの欠落をそのまま保持

| candidate | source_memory_id | source_revision_id (integer literal) | 結果 |
|---|---|---|---|
| cand-fence-authority | `a2a:conf1:fence-semantics` | `3` | UNRESOLVED |
| cand-asr-censoring | `a2a:conf1:asr-denominator` | `2` | UNRESOLVED |
| cand-pid-attribution | `a2a:conf1:process-identity` | `1` | UNRESOLVED |
| cand-checker-overgeneralization | `rsi:stage0:claim-level` | `1` | UNRESOLVED |

- source_provenance.json/SOURCE_LOOKUP.jsonを読んだうえで、指定4ストアの明示identity列へ**44 exact alias照会、match0**を独立実行。別profile/archiveや全世界での不存在は主張しない。
- 原sourceを捏造せず、primary memory/revision refsはnullのまま。関連record、会話抜粋、candidate自身の文面を原IDの正本に置換しない。

## 全未解決finding（対象hashは上記ZIP）

### F001: UNRESOLVED / blocking
4つの元source_memory_id/source_revision_idへの逆引きが成立しない。null primary refs、現source ERRORを保持する。

必要な対応/制約: 既存の実元記憶・実revision・一次証拠との厳密なID/type/linkageを提出する。関連recordのこじ付けや過去revisionの生成をしない。
根拠: `R09#/source_lookup`, `R09#/references`, `source_provenance.json#/records`

### F002: UNRESOLVED / blocking_for_causal_certification
ASRはC3/3 length、decision_valid0でN/Aの記述的証拠。A/B/Dのtransport-valid数は2/2/1でserver epoch変化がありbetween-condition因果比較不可。checker当時の成果物不存在も独立同時点証跡未復元。

必要な対応/制約: 因果/不存在認証を求める場合のみ、固定環境の別実験・同時点一次証跡・実信念revision chainが必要。現限定表現は維持する。
根拠: `R09#/historical_observations/0`, `evidence/asr-wire-observations.json#/source_freeze_status`, `source_snapshot.json#/candidates/3`

### F003: UNRESOLVED / blocking_for_generalizability
holdout_registryは空。flag/experience_id/source_memory_idの明示一致だけでcandidate_idやcontent overlapは対象外。frozen evaluatorのholdout除外を証明しない。

必要な対応/制約: 別revisionで固定holdoutを定義し、content/hash overlap監査と未知入力評価を行う。監査者は現ZIPを修理しない。
根拠: `source_snapshot.json#/holdout_registry_scope`, `R13#/observations/1`, `R06#/checks`

### F004: UNRESOLVED / blocking_for_generalizability
Stage-2は1固定手続き文のpreviewに限定。実snapshotはreview mapなしでDENIED。構造previewの安全性は確認できても教材の学習効果/転移/production trainingは未検証。

必要な対応/制約: 学習/汎化を主張する場合は人間承認後に別設計・別評価が必要。現時点ではtraining_allowed=falseを維持する。
根拠: `R06#/checks`, `FORMATTER_CONTRACT.md:33-63`

### F005: NEEDS_CLARIFICATION / minor_metadata_contract
fence excerptはgit blobの[14513,15181)と完全一致、first_line388も一致。last_line403は空境界行で、収録最終文字/非空行は402。半開行rangeなら整合するがlast_lineの規約がない。改ざんと断定せず明確化待ちとする。

必要な対応/制約: 新revisionで行番号rangeがinclusiveかhalf-openか明示し、文字spanとの対応を検査する。
根拠: `evidence/fence-source.json:6-11`, `R09#/historical_git`

### F006: LIMITATION / source_authenticity_limit
収録exportは現mutable local DB/git/元probeと一致するが、同一hostに依存するcorroborationであり署名された外部の歴史真正性証明ではない。source lookupは列/ストア限定で世界全体の不存在を証明しない。

必要な対応/制約: 必要な真正性保証のthreat modelを別途定義。現局所照合のscopeを拡大解釈しない。
根拠: `R09#/limitations`, `EVIDENCE_INDEX.json#/scope`

## 旧v1 findingの扱い

v1は履歴データとして最後に照合した。8 blocking findingsのうち7件の実装欠陥は新規実行で解消確認、元source不足1件は未解決のまま。fence本文の過剰断定とcheckerのexternal_verifiedは現文面/実sourceで新規校正確認。formatter構造の追加は実行確認したが汎化の認証ではない。これはv1 PASS継承ではない。

## 独立性・限界・実行上の問題

- 別agent contextによるfrom-zero auditであり、生産者の実装会話やv1 PASSを継承していない。ただしモデル/provider/tool/hostの基盤は共有するため完全に独立した別実験機関ではない。
- 人間承認ではない。human_approval=PENDING、automatic_promotion_allowed=false、STOP_AND_REPORTを維持する。
- 実関数テスト/有限順列は任意入力の数学的証明、モデルのlive instruction-following、汎化、学習効果、自己改善の証明ではない。
- 歴史sourceの照合は現在のlocal DB/git/probeとの限定corroborationであり、署名付き第三者真正性証明ではない。
- source検索は指定4ストアの明示identity列44照会に限定し、別profiles/archiveや全columnの不存在を主張しない。
- ASR歴史runは中断/epoch change/不均衡を含みbetween-condition効果判定不可。checker当時の成果物不存在の同時点独立証跡は不足。
- formatterのreview booleanの本人性は認証せず、未解決sourceでも固定文の構造previewを出し得る。previewは人間承認でも学習許可でもない。
- Codex CLI preseal reviewはconnection refused at 127.0.0.1:17841 / exit1のERRORでありreview PASSではない。providerを修理していない。
- 途中の広すぎるmetadata discovery execute_codeが300秒でtimeout。独立probe subprocess自体は3.094秒/exit0でreceiptを保存済みで、read-backにより62/62を確認した。その後指定DBへのnarrow read-only pathに切替え完了した。

## 非実行・次の許容遷移

学習・weight/LoRA merge・activation・server操作・old/r2 artifact rewrite・memory/revision生成・commit/pushは実施しない。未解決findingを新revisionで解決し、再度from-zero独立監査へ提出する。人間承認は引き続きPENDINGで、自動昇格不可。

## 監査証跡の所在

- JSON: `C:\Users\downl\Documents\New project\hermes-agent\rsi\audits\hakua-epistemic-v0-candidate-r2\audit-v2\independent_artifact_audit_v2.json`
- Markdown: `C:\Users\downl\Documents\New project\hermes-agent\rsi\audits\hakua-epistemic-v0-candidate-r2\audit-v2\independent_artifact_audit_v2.md`
- 隔離probe directory: `C:\Users\downl\Documents\New project\hermes-agent\tmp\probes\r2-auditor\audit-v2-cb8ab69a69564fd8bb99182ae6aeba83`

JSONのevidence_registryに各receipt/scriptの絶対pathとSHA-256、execution_receiptsに正確なargv/cwd/exit/生output/count、個別assertions、24順列、SQLパラメータ、各出典照合結果を保持した。

- R01: `C:\Users\downl\Documents\New project\hermes-agent\tmp\probes\r2-auditor\audit-v2-cb8ab69a69564fd8bb99182ae6aeba83\audit_state.json` / `5e81331cd5ae0a6d6641af166dfbcfdb83a7917d98756990871a76658e25edce`
- R02: `C:\Users\downl\Documents\New project\hermes-agent\tmp\probes\r2-auditor\audit-v2-cb8ab69a69564fd8bb99182ae6aeba83\integrity_receipt.json` / `a99ac980846b156788009cfc8ee2fbc65c8e9a72f70f22a1231ae2dbff4c9b44`
- R03: `C:\Users\downl\Documents\New project\hermes-agent\tmp\probes\r2-auditor\audit-v2-cb8ab69a69564fd8bb99182ae6aeba83\execution_receipts.json` / `89397dbc10a5fcf04abd1c621a6b02820842a0b114fbc74e113a18564124f4be`
- R04: `C:\Users\downl\Documents\New project\hermes-agent\tmp\probes\r2-auditor\audit-v2-cb8ab69a69564fd8bb99182ae6aeba83\independent_probes.py` / `cc4bb17b1c0ca536aabbea0e7d5bd3790805f869b29bff1827d3981d531e4dca`
- R05: `C:\Users\downl\Documents\New project\hermes-agent\tmp\probes\r2-auditor\audit-v2-cb8ab69a69564fd8bb99182ae6aeba83\independent_probe_execution.json` / `712c4d9f1d04df04fa712227b4f86006d682f08c487c9b509f49b9e3b1886bcb`
- R06: `C:\Users\downl\Documents\New project\hermes-agent\tmp\probes\r2-auditor\audit-v2-cb8ab69a69564fd8bb99182ae6aeba83\independent_probe_results.json` / `de9b4b65d0b6efa1463b61f539aaa0b62cc7fd93bea7a2247c3d2b9575928e20`
- R07: `C:\Users\downl\Documents\New project\hermes-agent\tmp\probes\r2-auditor\audit-v2-cb8ab69a69564fd8bb99182ae6aeba83\source_validation.py` / `0db526c6c167baef087f096f7174df7e0b74b471a444559fd6067340609e1388`
- R08: `C:\Users\downl\Documents\New project\hermes-agent\tmp\probes\r2-auditor\audit-v2-cb8ab69a69564fd8bb99182ae6aeba83\source_validation_execution.json` / `79933aecbb7486a87dcf42ecc7d694f1d9ce896e99879dc61ddb039d19f28564`
- R09: `C:\Users\downl\Documents\New project\hermes-agent\tmp\probes\r2-auditor\audit-v2-cb8ab69a69564fd8bb99182ae6aeba83\source_validation_results.json` / `c059e21ca765a6d5d9b4741625dacb44bca0149d74007c23db5ad5e1b3015cbe`
- R10: `C:\Users\downl\Documents\New project\hermes-agent\tmp\probes\r2-auditor\audit-v2-cb8ab69a69564fd8bb99182ae6aeba83\parent_validation_results.json` / `712f1f8ee384cfc141f87cda6508db2356c182137821ac9ec67c5be99f976390`
- R11: `C:\Users\downl\Documents\New project\hermes-agent\tmp\probes\r2-auditor\audit-v2-cb8ab69a69564fd8bb99182ae6aeba83\additional_probes.py` / `bd9a80e780f556b7ba803fac87d3824382ad81ab45ad8bcfcc50f8a52f700d25`
- R12: `C:\Users\downl\Documents\New project\hermes-agent\tmp\probes\r2-auditor\audit-v2-cb8ab69a69564fd8bb99182ae6aeba83\additional_probe_execution.json` / `ed99ac52f132f62708e477f455e3373e764c3972083c13a1f186ae2ee6c21ccc`
- R13: `C:\Users\downl\Documents\New project\hermes-agent\tmp\probes\r2-auditor\audit-v2-cb8ab69a69564fd8bb99182ae6aeba83\additional_probe_results.json` / `5dac8c3fa23e1af1f32f9b3639542251b90da597d033e3231c8e00476224e014`
