# hakua-epistemic-v0-candidate-r2

自己改善の**監査用候補**を決定的に編成する、Python 3.11+ の独立パッケージです。
Stage-1 の `train.jsonl` は名前を継承した **quoted audit data** であり、assistant の学習ターゲットではありません。
本パッケージは重み更新・モデル起動・外部コマンド実行・自動昇格を実装しません。
独立成果物監査と人間承認は常に別の `PENDING` ゲートです。

## 依存と実行

ランタイム依存は `requirements.txt` の `jsonschema==4.26.0` のみです。
stdlib `unittest` と jsonschema で検証でき、Hermes 本体やリポジトリのテスト設定は不要です。

```sh
python -m pip install -r requirements.txt
python -m unittest -v test_compiler
python compiler.py
python compiler.py --source source_snapshot.json --out dataset --schema candidate.schema.json
```

`uv` を利用する場合、既存の正しい環境を用いるか、独立したコピー先で依存をセットアップしてください。
`python compiler.py` は **compiler.py と同じディレクトリ**の `source_snapshot.json` を読み、同じ場所の `dataset/` へ出力します。
作業ディレクトリが別でも利用できます。snapshot と evidence は親担当者が供給し、compiler は生成しません。
明示オプション `--evidence-root` は相対 evidence path の基点（bundle root）、
`--source-provenance` は resolution JSON のパスです。既定は source の親ディレクトリとその `source_provenance.json` です。

終了コード:
- **0**: 実行した engineering checks が PASS。ただし独立監査・人間承認は未完了。
- **2**: 入力・schema・出典・整合性等で NEEDS_REVISION。出力が生成されても昇格不可。
  missing/broken source の場合は stdout の構造化 ERROR のみになることがあります。
- stdout は JSON 1行です。成功のように見せる固定 PASS や `print()` は使用しません。

生成ファイルは `train.jsonl`, `dataset_manifest.json`, `rejected_examples.json`,
`source_snapshot_manifest.json`, `verification_report.json` です。
既存出力ディレクトリの同名ファイルは上書きするため、新しい `--out` を指定してください。
旧 rsi データ・監査bundle・ZIPを出力先に指定しないでください。

## 入力契約

snapshot は object で、非空 `snapshot_id`、`candidates` list、**必須** `holdout_registry` list を持ちます。
registry の各要素は非空の ID string です。registry 欠落・型不正は ERROR、fail closed です。
空の candidates は全PASSを主張できません。
JSON の duplicate keys、NaN、Infinity は拒否します。

各 candidate は同梱 Draft 2020-12 schema の **22必須フィールド**を持ち、追加フィールドは禁止です。
`candidate_id`, `experience_id`, `source_memory_id`, `snapshot_id` は非空 string。
`source_revision_id` は非空 string または正の integer literal で、整数3と文字列「3」を同一化しません。
bool と integral float は revision ID として拒否します。値の正規化や架空の置換ID生成は行いません。
追加必須フィールドは:
- `holdout_origin`: boolean
- `contradictory_unresolved`: boolean
- `evidence_refs`: 非空・重複なしの relative path string array
- `source_record_status`: `resolved` または `unresolved`

`content_role=quoted_data`, `action_permission=none`, `adapter=hakua-epistemic` を実スキーマ検証します。
`Draft202012Validator.check_schema` と `Draft202012Validator.iter_errors` を実行します。
compiler 内の canonical schema digest と一致する**同梱契約だけ**を受け入れます。
`--schema` は同一契約のコピーに使えますが、unknown schema、required削除、type/const緩和、
additionalProperties緩和、broken schema は受け入れません。schema の変更には新しい明示的revisionが必要です。

## 拒否と決定性

7コードすべてを `fixtures.json` の実行可能な10ケースで検証します。
fixtures は明示的に **synthetic_only** であり、一次記憶・一次出典・学習データではありません。

| Code | 条件 |
|---|---|
| REJECT_MISSING_PROVENANCE | experience/memory/revision ID の欠落・null・空白のみ |
| REJECT_PERMISSION_CLAIM | action permission または content role の逸脱 |
| REJECT_HOLDOUT_ORIGIN | 自己申告、experience ID または memory ID のregistry所属 |
| REJECT_SUPERSEDED_UNSTABLE | claim_strength_after が unverified |
| REJECT_DUPLICATE | 同一 memory ID / typed revision ID の非衝突重複 |
| REJECT_CONTRADICTORY_UNRESOLVED | 未解決フラグ、同一keyで異なる revised_claim |
| REJECT_SCHEMA_VIOLATION | その他schema/type違反、candidateがobjectでない |

衝突の検出は**重複代表の選択前**です。衝突keyの全候補を排除し、
出典の強さを理由に対立信念の片方だけを採用しません。schema-invalid な対立候補も衝突検出から隠しません。
非衝突重複は r1 の authority 順（external_verified > internal_inspection > self_reported）、
`claim_strength_after` の文字列順、最後に canonical UTF-8 bytes で代表を選択します。
これは出典ラベルの真実性を保証するものではなく、source provenance が別途必要です。
output key の整列も typed canonical bytes を使い、integer/string混在で破綻しません。
canonical JSON は UTF-8、sort_keys、compact separators、ensure_ascii=False、allow_nan=False。
各JSONL行はLF終端です。

report は同じ snapshot を **実際に2回再コンパイル**し、本文・再計算hash・accepted/rejectedを比較します。
compile 単独では決定性の検証を済ませたことになりません。
同梱テストは有限入力の全順列（代表例24通り、型混在例6通り等）を試しますが、一般的な数学的証明ではありません。

## レポートと改ざん検出

17 required checks を `PASS/FAIL/SKIP/ERROR` と根拠付きで網羅します。
missing/malformed check は ERROR として補い、coverageもERRORにします。
input filtering の成功と accepted-output schema validation を区別します。
report は accepted を再検証し、本文を accepted から再構築し、dataset hash と manifest body hash を再計算し、
再コンパイル結果と比較します。accepted・body・hash・manifest の事後変更は FAIL です。
`schema_result`, `holdout_contamination`, `duplicate_conflict_check` は実checkから導出し、未実施・不可用なら null。
source provenance が ERROR/FAIL なら全体は NEEDS_REVISION。空datasetもNEEDS_REVISIONです。
これらはローカルengineering checkであり、独立監査 PASS ではありません。

metadata は `artifact=hakua-epistemic-v0-candidate-r2`, `artifact_revision=2`,
`parent_artifact_sha256=5ab281294b79a33565e6f1b0705995a542cb0972b9847aa42278692c3af368aa`,
`parent_audit_verdict=NEEDS_REVISION` を保持します。
`independent_artifact_audit=PENDING`, `human_approval=PENDING`,
`activation_status=STOP_AND_REPORT`, `training_status=NOT_STARTED` を変更しません。

## 一次出典と未解決状態

legacy pseudo ID `a2a:conf1:*` / `rsi:stage0:*` の実メモリへの解決をcompilerは推定しません。
関連メモリは元pseudo IDまたは主張されたrevisionの証明ではありません。
親供給の実行対象候補は `source_record_status=unresolved` のまま監査データとして編成できますが、
`source_provenance_result=ERROR` とCLI終了コード2で昇格をブロックします。

`source_provenance_check` の resolved branch は**限定されたローカルexport linkageとfile digest検証**です。
独立した出典真正性・因果監査ではなく、同梱テストでは合成fixtureによってのみ肯定ケースを検証しています。
現実のDB exportを candidate の文面に合わせて加工・捏造してこのbranchを通してはいけません。
実exportが以下の型と一致せず、実際のID/claim linkageも解決していないなら、unresolved を保持してください。

resolved branch の明示契約（実対象の解決を主張するための雛形ではありません）:
`source_provenance.json` の `records` list に、candidate の3 provenance IDsと一致する唯一のentryが必要。
entryは `status=resolved`, `evidence_refs`, `memory_record_ref`, `revision_record_ref`, `file_sha256` を持ちます。
`file_sha256` は evidence refs と2 primary refsそれぞれのrelative path→SHA256 map。
memory JSONには一致する `experience_id`, `source_memory_id`, `previous_claim`、revision JSONには
`source_memory_id`, `source_revision_id`, `new_evidence`, `revised_claim` が必要です。
不足・欠落・unsafe path・未解決は ERROR、hash/contentの不一致は FAIL。
URL fetchは行わず、bundle外参照、absolute path、traversal、symlink escapeを拒否します。

## 公開API

- `compile_dataset(snapshot, schema_path=None) -> dict`: accepted/rejected、入力/schema error、train_body、hash、manifest。
- `verification_report(snapshot, result, schema_path=None, evidence_root=None, source_provenance_path=None) -> dict`
- `load_snapshot(path=同梱source_snapshot.json)`: duplicate-key/nonfinite拒否JSON reader。
- `write(out_dir, result, report)`: Stage-1 audit artifactsのみ。
- `complete_checks(checks)`: required-check coverageのfail-closed集計。
- `formatter.format_preview(snapshot, result=None, schema_path=None)`: deny-default target-only preview。

formatter の信頼境界・固定語彙・formatter専用承認は `FORMATTER_CONTRACT.md` を参照してください。

## 実装・検証トレーサビリティ

変更範囲は新規r2の指定8ファイルのみ。旧rsi、旧dataset、旧監査bundle、ZIP、Git履歴は変更しません。
実装中、schema受理、拒否カテゴリ、malformed input/schema、holdout、矛盾、重複、fixtures、report coverage、
実再コンパイル/改ざん、出典resolution、独立CLI/strict JSON、literal integer/provenance gate、
deny-default formatter、reviewed preview、整数literal、legacy代表順序について、
テストを先に追加して実際のREDを観測し、実装後GREENを確認しました。

PC common/Python/implementation gate/security SOPを参照しました。
書込を8ファイルに限定する個別指示のため、別の `_docs` 実装ログは作成せず、この節をパッケージ内の記録とします。
TDD実行は指定された既存 `.venv/Scripts/python.exe` を subprocess から使用しました。
Windows terminal/file tools の長さ制限を回避するためpathlib/subprocessとUTF-8を使用しています。
blackとflake8はuv toolの一時環境を使用し、パッケージruntime依存へ追加していません。
正式なMILSPEC適合、全文因果監査、独立成果物監査、production安全性、学習効果を主張しません。
rollbackは新r2を採用しないことです。元artifactは修正しません。


### 最終実行証跡

最終 `black==25.1.0 --line-length 119` 整形後:
- originalおよび指定8ファイルだけをコピーした独立temp bundleで `python -B -m unittest -v test_compiler`: **27 tests, OK, exit 0**。
- repository pytest設定を読まないtemp bundleで pytest: **27 passed, 45 subtests passed, exit 0**。
- black `--check --line-length 119`: 3 files unchanged, exit 0。
- flake8 7.3.0 `--max-line-length=119 --extend-ignore=E203,W503`: exit 0。
- Python3ファイルのsyntax compileとAST検査: `print` call 0、関数引数/戻り値の型注釈欠落0。
  外部static type checker (mypy) は未実施で、型注釈の存在確認を完全な型検査と同一視しません。
- 8ファイルすべてUTF-8 without BOM。実行環境 jsonschema 4.26.0。
- 親供給の実snapshot/evidenceをtempへコピーしたdefault CLI: **exit 2**、4 accepted、0 rejected。
  schema/determinism/output integrity/required coverage PASS、source provenance ERROR、全体NEEDS_REVISION。
  accepted revision valuesは integerのまま `[2, 3, 1, 1]`（output key順）でした。
- 最終compiler SHA256: `44e874c25e72f53b5d1f77403d1f4062d890c3206bf2b91216f1e17c8dc46f68`。
  temp生成manifestのcompiler digestと最終ファイルbytesの一致を再検証しました。
- 実snapshotのdataset SHA256: `8d9fb634b5892b39834b5ed86b8f3aa1f142b650f8a85a626e9ac327c16eff72`。

上記tempの生成物はテスト終了時に削除されます。親担当者は最終compiler bytesで成果物を再編成し、
lineage/ZIP/独立監査を別途封印してください。Git commit/push/history変更は本実装担当では行っていません。
