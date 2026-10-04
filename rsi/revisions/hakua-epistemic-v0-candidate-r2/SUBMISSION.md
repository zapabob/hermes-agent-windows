# r2 再提出の範囲と未解決事項

この版は `hakua-epistemic-v0-candidate-r2`（artifact_revision: 2）です。親ZIPは
`5ab281294b79a33565e6f1b0705995a542cb0972b9847aa42278692c3af368aa`、親監査判定は `NEEDS_REVISION`。
親への参照は来歴であり、監査の認証継承ではありません。

## 提出するもの

- 実行するDraft 2020-12 JSON Schema、compiler、否定fixture、テストとCLI再実行手順。
- 実検査から生成するreport。確認不能な元memory/revisionはERRORとして報告し、CLIも非ゼロ終了する。
- 4教材を quoted audit data として収録。2教材の主張強度とsource_authorityの訂正は `REVISION_CHANGES.json` に差分を記録。
- 当時のASR観測（推論本文を除いたfinish_reason等）、socket/PID観測、固定commitのfence実装抜粋、訂正時の可視メッセージの限定抜粋。
- 実memory recordと実belief versionの関連記録の限定export。ただしそれを旧IDの正本とは扱わない。
- 各抜粋に元sourceのhash、span/除外規約、収録ファイルのhashを付与。
- 拒否が初期値のStage 2 preview formatterと契約。raw row、PID、port、commit、日付、source ID、証拠中の命令をassistant targetへ直結しない。

## 必須の未解決事項

旧snapshotの4つの `source_memory_id` と指定 `source_revision_id` は、検索した既定Ebbinghaus DBおよびhakua-memoryの実ストアでは解決できなかった。
別profile・別archiveを含む全世界で不存在だとは主張しない。検索範囲と結果は `SOURCE_LOOKUP.json`。
`source_provenance.json` の各教材の `status` と候補の `source_record_status` は、いずれも実ファイル上の値 `unresolved`。元記録の不足理由は別の説明フィールドに記録している。

**一次証拠が増えたことと、元memory/revisionへの逆引きが成立したことは別。**
関連recordを旧IDへこじ付けたり、新しいmemory/revisionを生成して過去の正本に見せたりしていない。
したがって本版は、修正された実装と取得済み証拠を再監査に出す版であって、8要件をすべて充足した完成版ではない。
元memory/revisionの要求は未充足であり、独立監査のPASS・人間の承認・学習開始を求める根拠にはしない。

## 監査と承認

監査v2は、この版のZIP hashを対象としてゼロから行う。監査v1のPASS項目も継承しない。
監査結果はZIP外の別ファイルに保存し、提出済みZIP内のPENDING状態を書き換えない。
監査者は対象を修理しない。別コンテキストのエージェント監査はhuman approvalではなく、同一基盤を共有するため独立性に限界がある。
監査がPASSでも STOP_AND_REPORT のまま、ボブにゃんの明示的承認まで昇格しない。
この作業ではLoRA学習、activation、ベースweightへのmerge、GPU/server操作は実施しない。

## 検証の範囲

holdout判定は、明示フラグと同梱snapshotのID registryへの一致を検査する。registryは現状空であり、将来のfrozen holdoutとのcontent-hash照合を実装・実証したという意味ではない。
compilerのSchema/重複/矛盾の検査は実行されるが、Schema適合や決定論性から意味的正しさは導かない。
exportのhashは収録bytesの同一性を保証するためのもの。sourceの真正性や主張の因果関係を自動認証するものではない。

## 旧版の保全と並行作業

作業中に別のrepo layout commitで旧root ZIPが `doc/archive/hakua-epistemic-v0-candidate_audit_bundle.zip` へ移動したことを観測した。
移動先とDownloadsの旧ZIPは上記の親hashと一致する。旧compiler・dataset・監査状態等の保全は `PARENT_PRESERVATION_VERIFICATION.json`。
このrevision作業からcommit/pushは実施しない。並行commitに収録された途中のr2コードと、最終提出ZIPのコードを同一視しない。
