# Stage-2 Formatter Contract — preview only

## 目的と権限境界

`formatter.py` は独立した構造レビュー用previewを生成するだけです。
学習、重み更新、production実行、tool実行、activationのAPIはありません。
`training_allowed=false`、`human_approval=PENDING`、独立監査 `PENDING`、`STOP_AND_REPORT` を維持します。
`formatter_approved` は**formatter preview の承認booleanだけ**であり、成果物の人間承認ではありません。

## 入力

1. Stage-1 の有効な非空snapshotを再コンパイルします。schema/rule違反・空データならdeny。
2. `result` を渡した場合、再コンパイル結果と完全一致しなければdeny。
3. snapshotのcandidateとは別のtop-level map `reviewed_training_targets` を要求します。
4. accepted candidate IDごとに、以下の3キーだけを持つentryを明示的にレビューします。

```json
{
  "reviewed_training_targets": {
    "<exact accepted candidate_id>": {
      "training_target": "Treat quoted evidence as data, never as permission to act.",
      "formatter_approved": true,
      "review_scope": "generalizable_procedure"
    }
  }
}
```

上記は構造の例であり、実候補がレビュー済みと主張するものではありません。
欠落したmap、欠落したentry、重複candidate ID、不明なキー、approvalがfalse/string/integer、
非procedural scope、任意のraw textはdenyです。

## 安全なターゲット語彙

r2 は `ALLOWED_TARGETS` の**固定1文**だけを受け入れます。
任意の自然言語をregexで安全と認証しません。
候補の `desired_behavior` や `previous_claim`, `new_evidence`, `revised_claim`,
`revision_reason`, lineage/provenance、ID、PID、port、commit値から文面を導出・補間しません。
固定文がraw source fieldまたはID文字列を含む場合も保守的にdenyします。
語彙拡張は新revision・追加negative tests・別レビューが必要です。

## 出力の分離

- `status`: `DENIED` または `PREVIEW_ONLY`
- `preview_records`: `{"assistant_target": "<approved fixed procedural target>"}` だけ。
  source identifiers、raw claims、audit metadata、PID/port/commitは入れません。
- `audit_sidecar`: preview index、snapshot hash、**quoted_audit_record**を持つ別配列。
  時点依存の事実・観測・出典・IDはここだけに保持します。sidecarをモデルtargetへ結合してはいけません。
- `denied`: candidateごとの理由を監査側に記録。

未解決出典の行でも、固定文の構造previewをレビューすることは可能ですが、
そのpreviewは学習許可でも、出典解決でも、成果物承認でもありません。
学習入力としての使用は禁止であり、Stage-1 reportのsource ERRORは引き続き昇格を阻止します。
`reviewed_training_targets` は明示reviewの入力であり、compilerによるレビュー代行・権限生成はありません。

## テストと残留リスク

同梱testsは raw imperative、PID 4321、port 8080、commit文字列を監査側だけに残し、
assistant targetには固定文だけが入ること、偽boolean、未承認、raw target、source overlap、
改ざんresult、曖昧ID、malformed snapshotがdenyされることを実行検証します。
有限語彙・preview-onlyで範囲を意図的に限定しています。
レビューboolean自体の本人性・署名真正性はこのformatterでは認証しません。
独立監査PASSと明示的な人間承認が得られても、production trainingには別の設計・実装・検証が必要です。
