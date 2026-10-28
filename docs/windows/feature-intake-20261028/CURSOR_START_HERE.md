# Cursorでの開始方法

この一式は、Windowsネイティブ版Hermesへ上流機能を選択導入するための仕様と実装計画です。既存コードの調査に基づきますが、コード変更・CodeGraph・テスト・実機検証は未実施です。

## 1. 配置

ZIPを展開し、対象checkoutの `docs/windows/feature-intake-20261028/` へこのフォルダー内のファイルを置きます。配置先が既にある場合は上書き前に内容を比較します。Cursorで実際のHermes repository rootを開いてください。

主計画は `CURSOR_WINDOWS_NATIVE_FEATURE_PLAN_20261028.md`、規範となる機能仕様は `SPEC_WINDOWS_NATIVE_20261028.md`、検証の対応表は `ACCEPTANCE_MATRIX.md`、調査固定点は `SOURCE_EVIDENCE.json` です。

## 2. 最初に貼る指示

以下をCursor Agentへ貼ってください。これはM1の開発実装用の指示です。M2/M3を着手するときは、その後に対象タスクを追加指定します。

```text
このrepositoryのWindowsネイティブHermesに、新機能を実装してください。

docs/windows/feature-intake-20261028/ の以下を読んで作業してください。
- CURSOR_WINDOWS_NATIVE_FEATURE_PLAN_20261028.md
- SPEC_WINDOWS_NATIVE_20261028.md
- ACCEPTANCE_MATRIX.md
- SOURCE_EVIDENCE.json

対象は主計画のT00を完了し、M1に含まれるT01、T02、T03、T05、T06、T07、T08、T09、T10を、依存順に実装・検証することです。既に受け入れ条件を満たす機能はEXISTS_EQUIVALENTとして扱い、作り直さないでください。T04、T11以降、DFlash、上流PM移行は今回の既定scopeに追加しません。

最初に実HEAD・dirty worktree・AGENTS.md・DOWNSTREAM_POLICY.md・Desktop規約を確認し、CodeGraphのstatus/sync/query/impactでownerと呼出し元を確認してください。古いUPSTREAM_SNAPSHOT.jsonは変更せず、今回のsource-lockとgap表を別に記録してください。GitHub main全体のmergeやバージョン数値だけの更新はしません。

各タスクは、行動テストを先に追加し、意味のあるREDを確認してから最小実装します。既存テストがGREENなら無理にREDを作りません。GREEN後は対象回帰、型/lint、必要な意味論mutation、native Windows E2E、rollback、reviewまで完了してください。実行していないものはNOT_RUN、環境上の阻害はBLOCKEDと書いてください。

守る境界は、controlled delegationの親route、profile/connection/session/requestの分離、既存圧縮commit fence、Electron mainのbackend owner、カスタムllama-server/PQ2_0等の互換、ユーザーの既存データとdirty変更です。plugin OAuthのbrokerやctx.filesを敵対的pluginの完全なsandboxとは表現しないでください。

MCPはSDK callbackだけで終わらずgatewayの一般tool.progress bridgeまで、子agent設定はGUIだけで終わらず原子的validation/saveまで実装してください。plugin更新はCLI/GUIのscan・再同意を共通化してからUXを追加してください。

新設ファイル名やAPIは主計画で提案扱いです。現HEADに適切な既存ownerがあればそこを使い、変更した理由をsource-lock/作業記録に残してください。同じ共通ファイルを複数workerで同時編集しないでください。

作業結果はoutput/reports/feature-intake-20261028/へ記録し、要件ID、実SHA、実行command、RED/GREEN、mutation、Windows結果、rollback、次のtaskをまとめてください。要約やTODO列挙だけで止まらず、開発環境で実行できる実装・検証まで進めてください。

この指示でmainへのpush、release公開、本番Desktop/llama-serverの停止・再起動、実vaultの移行、実plugin更新は行いません。test用profile・dummy credential・isolated Windows fixtureで具体的な結果を作ってください。
```

## 3. 長い作業の再開用

新しいCursor sessionでは、次を貼ります。taskとreport pathを直前の記録に置換します。

```text
前回の実装を継続してください。
主計画とoutput/reports/feature-intake-20261028/の最新記録を読み、現在のgit diff/HEADを照合してください。
完了したtaskと既存の受け入れ条件を再実装せず、次の未完了M1 taskから続けてください。
前回のPASSはSHA・artifact・fixtureが今回と対応する範囲だけ再利用し、変更の影響がある試験だけを再実行してください。
未実施Windows試験をPASSに変更せず、阻害理由と実行可能な次の手順を残してください。
```

## 4. M2を追加する場合

M1が安定した後、`T04`（高度な委譲）、`T11`（prepared compaction）、`T12`（download）、`T13`（再現時のsleep対策）から必要な対象を指定します。同時に全部を有効にする必要はありません。T11は既定OFFと同一GPUの取消契約を維持し、T13は再現しなければ実装を増やしません。T14のWebappは別の任意段階です。

