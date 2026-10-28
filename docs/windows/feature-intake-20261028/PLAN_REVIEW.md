# 実装計画のレビュー記録

作成日：2026-10-28 JST。対象は計画文書と参照した固定SHAのソースです。実装コードのテスト結果ではありません。

## 実施した設計レビュー

調査をMCP/queue/delegation、plugin/auth/vault/files、local runtime/compressionの3領域へ分担し、主計画完成後に各領域を再レビューしました。root側でも既存規約、test scripts、設定保存・vault・delegation・圧縮予算などを照合しました。

| 発見 | 文書へ反映した修正 |
|---|---|
| queue/prefillの主機能は下流に既存 | 新規作り直しを外し、配送・帰属・ACK・stale responseの差分に限定 |
| 通常delegationとparent-owned delegationは別契約 | controlled routeのoverride拒否を維持し、高度routeを別taskへ |
| 並列数・深さはdynamic schemaにも影響 | runtime-onlyとschema関連を分類し、新sessionへの適用と有効snapshotの一致を要求 |
| CLI/GUIのplugin更新後処理が不一致 | 共通update coreを先に整え、追加権限の自動同意を禁止 |
| plugin OAuthはtokenを返すAPIではない | manifestとhost brokerへ接続し、正規APIの保証とsandbox限界を明記 |
| OAuth宣言変更とrefresh/logout競合 | fingerprint再認証とbarrier試験を追加 |
| vault移行でDACL・clone/rename・跨processが重要 | 既存DACL、random entry ownership、readback/decrypt後の削除、逆移行を明記 |
| ctx.filesはDesktop-localのgrant | profileごとの隔離とは表記せず、通常APIのscopeとraw bridgeの限界を記載 |
| summary予算には8,000-token floorがある | 常に25%以下という表現を外し、全requestのfeasibility testを追加 |
| prepared開始後のinteractive入力が未規定 | 有限時間の取消確認、二重GPU推論なし、ACK喪失時の復旧表示を追加 |
| prepared OFF後の旧workerが残り得る | admission閉鎖・世代更新・pending取消・late結果/再queue拒否を追加 |
| downloadはサイズだけでは同一性が不足 | revision/validator/hash、200への追記拒否、同size別内容fixtureを追加 |
| npm test:e2eへの追加引数は全specも選ぶ | build後に直接Playwrightを呼び、--listで対象scopeを確認する例へ変更 |

## 文書品質の確認

UTF-8/BOM、Markdown fence、内部リンク、T00〜T14とR01〜R13の対応、JSON、必要な成果物の存在を機械的に確認し、全項目PASSでした。配布時にはSHA256SUMSを生成し、ZIPのarchive CRCと原本とのbyte一致も確認します。これらはファイルの整合性検査であり、Hermesの動作検証ではありません。

## 実施していないこと

ユーザーのcheckoutへのCodeGraph実行、ソース変更、Python/TypeScriptのテスト、mutation、Windows資格情報/NTFS/実機E2E、モデル取得、Desktopやllama-serverの再起動、GitHubへの書込みは行っていません。Cursorの実装記録で、対象SHAに対して実際に実行した結果を追加してください。

