# WindowsネイティブHermes：新機能導入仕様

作成日：2026-10-28 JST。状態：実装に渡す仕様。コード変更・Windows実機検証は未実施。

## 1. 目的

Windowsネイティブ版Hermesに、利用者の作業を直接改善する上流機能を選択して組み込む。評価単位は利用者が使える機能と、その機能の受け入れ条件とする。上流との差分コミット数、バージョン表記、ファイル構成の一致を達成目標にしない。

対象は `zapabob/hermes-agent-windows`。調査時点の下流は `5531c849b424cdfee17946935eec73363917e5e7`、上流参照は `e5ea5fd9ccdf2913c0b21b24eb3d22b321d2e2a6`。Cursorは実際のcheckoutで再照合する。新たな上流参照点を今回のcampaign manifestに記録し、過去の `.codex/UPSTREAM_SNAPSHOT.json` を書き換えない。

## 2. 利用者の作業と要求

| ID | 利用者ができるようになること | 機能上の受け入れ条件 |
|---|---|---|
| R01 | 長いMCP処理やローカルLLM入力読込みの状態を判断する | 実行中の呼出しに対応した進捗を表示する。不明な割合を推測せず、完了・失敗・取消を正しく反映する |
| R02 | Desktopで子エージェントのモデルと制限を設定する | provider/model/limitsを整合した単位で保存する。反映先・時点を表示し、親所有の制御された推論を上書きしない |
| R03 | 用途別に委譲経路を指定する | 明示した経路のみを使い、実際の経路・fallbackを返す。未導入backend、許可外profile、未解決routeを黙って代替しない |
| R04 | プラグイン更新の有無を知り、安全に更新する | CLI/GUIが同じpin・GitPolicy・更新後検査・capability再同意を通る。自動同意しない |
| R05 | プラグインの外部サービスへサインインする | hostがtokenを保持し、宣言された宛先だけに付与する。profile間、redirect先、ログへ漏らさない |
| R06 | 対話可能なプラグインコマンドで選択肢を選ぶ | 既存clarify UIを使い、cancel/timeout/非対話環境はテキスト案内へ戻る |
| R07 | browser vault鍵をWindows Credential Managerに保管する | opt-in。移行先への保存・読戻し・既存暗号文の復号を確認するまで旧鍵を失わない |
| R08 | Desktopプラグインへ選択したフォルダーの操作を渡す | 通常の `ctx.files` APIはplugin ID別のgrantと保護パスを守る。撤回・不正パス・壊れたgrantを拒否する |
| R09 | 圧縮が確定した後にプラグイン処理を接続する | durable commitが成立した圧縮だけ通知する。準備・失敗・取消には通知せず、hook失敗で圧縮を取り消さない |
| R10 | 長い会話の圧縮待ちを任意に減らす | prepared compactionは既定OFF。現在の履歴と一致する結果だけ採用し、後続メッセージを保持する |
| R11 | モデルの取得を一時停止し再開する | 検証済みの完成ファイルだけ有効化し、通信断・disk-full・再起動で既存モデルを壊さない |
| R12 | 同一Windows PCの推論をスリープ復帰後も継続する | 不具合を実機で確認した場合だけ時計処理を補正する。リモート推論の時間や停止操作を誤って延長しない |
| R13 | 必要時にローカルブラウザーから作業を続ける | 後続の任意段階。既存gateway ownerと認証を使い、既存dashboardとポート競合しない |

既存のキュー編集・Steer Now・park、KV/context見積もり、ローカル前処理のtimeout計上、同じrouteへの復旧、MoA、実装router、memory providerは保持する。これらは新機能として作り直さず、受け入れ条件との差分がある場合だけ補う。

## 3. 状態の所有者

| 状態・操作 | 所有者 | 境界 |
|---|---|---|
| session・agent・委譲・圧縮確定 | 既存Python backend | rendererは結果を表示する。独立したcommit権限を持たない |
| Desktop backend lifecycle・native picker・ローカルファイル | Electron main | rendererへ狭いtyped IPCを公開する。watchdogを第二ownerにしない |
| フォーカス・入力編集・表示状態 | renderer | profile/connection/sessionの変更で古い応答が上書きしない |
| model/runtime起動 | 既存下流launcher・設定 | downloaderは起動ownerを引き継がない。既存の外部llama-serverを停止しない |
| plugin OAuth token | profileの既存auth store | host brokerだけが参照し、pluginへtokenを返さない |
| browser vault暗号鍵 | 選択されたfile/keychain | Electron safeStorageによる接続秘密の保存設定とは独立 |
| ctx.files grants | Desktop-local、plugin ID別 | backend profile別の権限とは説明しない。remote接続でも対象はDesktopのローカルファイル |

## 4. 契約上の判断

### C01：新旧互換

機能検出で対応可否を判定する。古いbackend/rendererに未対応の設定やIPCを送らず、理由を表示する。ネットワーク障害を「古い版だから」と誤認して別の宛先へ書込みを再試行しない。

### C02：同時実行と識別子

各機能で必要なprofile/home、connection generation、session/runtime identity、request/tool-call identityを既存のenvelopeに付与または保持する。すべての永続キーへ無条件に同じ組を埋める設計にはしない。特にctx.filesはDesktop-local、plugin ID scopeを維持する。非同期応答の採用時に現在のownerとgenerationを再検証する。

### C03：設定変更の反映時点

実行中turnのprovider/model/tools/prefixを差し替えない。設定項目をruntime-onlyとschema/capabilityに影響するものへ分類する。並列数・深さ・orchestratorは既存のdynamic schemaへ影響するため新sessionを標準とし、表示・schema・admissionを同じ有効設定snapshotへ揃える。runtime-onlyと確認できた項目だけ次のchild admissionへ反映する。既存の安全なturn境界での明示適用がある場合のみ、その仕組みへ接続する。設定画面に保存済み・現在有効・次回から有効を区別して出す。

### C04：委譲のauthority

通常の子agent設定と、`ParentInferencePort`で親のprofile/provider/model/routeを固定したcontrolled delegationを区別する。controlled modeのoverride拒否を維持する。cross-profile routingは対象profileのcredential/tool authorityを使うため、既存の許可とcapacity admissionを通す。既定profileの環境変数へfallbackしない。

### C05：prefix・memory・圧縮

無関係な新tool/schema/system promptを全turnへ追加しない。既存memory provider、圧縮transaction、`CompressionCommitFence`、遅延workerの拒否を維持する。prepared summaryは独立に履歴を更新せず、通常の圧縮commit経路から採用する。

### C06：ローカル推論の資源

開始時に実機構成を確認する。想定はWindows 11、RTX 5060 Ti 16GB、RAM 32GB、単一GPU。VRAMを複数GPUの単純合計として扱わない。既存のカスタムllama-server/PQ2_0等の対応を能力確認し、上流の標準binaryで置換しない。prepared compactionは同一GPUのinteractive推論中には既定でdeferする。DFlashは本計画の標準導入対象から外す。

同一GPUのidle中に準備処理を開始した後でinteractive入力が来た場合、既定では準備処理を取消・停止して必要なら最新snapshotで再queueする。停止未確認の間に同じGPUへ別の推論を重ねない。取消済みworkerの遅延結果をgenerationとcommit fenceで破棄する。取消を確実に実装できないruntimeでは同一GPU上の準備処理を有効にしない。

取消確認には有限な上限を設け、停止未確認なら準備を失効させ、先読みの新規admissionを閉じ、foregroundへbusy/復旧が必要な理由を返す。外部serverを勝手にkillせず、未停止のまま同じGPUへ新規推論を重ねない。OFF切替でも世代更新・pending取消・実行中停止要求を行い、旧workerの結果・進捗・再queueを拒否する。

### C07：鍵の移行

既定はfileのまま。明示してkeychainを選んだときの失敗は、理由を表示して元の鍵を保持する。計画の下流判断として、明示keychain要求を黙ってfile方式へ下げない。暗号文がある状態で鍵が見つからないときは復旧エラーにし、新規鍵を生成しない。fileへ戻す往復移行と跨process排他を実装する。

既存のprotected DACLを保持し、fileへ戻した鍵にも適用する。keychain entryはprofile名の再利用と衝突しないランダム識別子を持ち、clone/rename後に他vault所有のentryを上書き・削除しない。

### C08：プラグインの境界

OAuthはmanifest `oauth:` とhostの `credentialed_provider_request` を基本にする。tokenを返す `ctx.oauth` APIを新設しない。`ctx.files`は通常APIのgrant制約であり、同一renderer内で任意コードを動かす敵対的pluginの完全なsandboxではない。login backend pluginの信頼要件は別の設計決定とし、この作業で緩和しない。

OAuthの秘密保持は正規API経路の契約である。任意コードを実行できる同一process・同一OS userのpluginに対する秘密情報隔離は、このbrokerだけでは保証しない。保存したgrantは同意時のOAuth宣言fingerprintに拘束する。authorize/token URL、hosts、scopes、client変数名等の変更で再認証し、並行refresh/logoutでlogout済みgrantを復活させない。

### C09：変更の戻し方

設定・コード・ユーザーデータの復旧を分ける。原則として機能の入口を閉じてもデータを保存する。keychain-only vaultを旧バイナリへ戻すときは、対応版でfileへの検証済み移行を先に行う。download停止で正常な既存モデルを削除しない。

モデル取得manifestでrevisionまたは不変のcontent identityを固定する。再開時にRange応答・ETag等のvalidator・期待サイズを照合し、HTTP 200、validator不一致、サイズ変更では部分ファイルへ追記しない。同サイズでも別内容を混合しない。完全性の検証後にだけatomicに完成ファイルへ昇格する。

### C10：検証の誠実さ

本書のテスト名、閾値、完了条件は計画であり、合格実績ではない。CodeGraphは実機checkoutで実行する。Linux上のテストや `sys.platform` のmockをWindows実機合格として扱わない。実行していない試験はNOT_RUN、原因のある未実施はBLOCKEDと記録する。

## 5. 出荷区分

| 区分 | 対象 | 終了条件 |
|---|---|---|
| M1：操作と拡張基盤 | R01、R02、R04、R05、R06、R07、R08、R09 | 各行の機能試験・対象回帰・必要なmutation・Windows検証が完了。既存機能の回帰なし |
| M2：選択的な高度機能 | R03、R10、R11、再現時のR12 | 機能ごとに追加cost・資源・復旧を検証。未完了機能は露出させない |
| M3：任意拡張 | R13、診断plugin、対応providerのusage表示等 | 個別の受け入れ条件を満たす。M1/M2の出荷条件へ無条件に含めない |

出荷・公開・本番再起動はこの計画書作成依頼の実行範囲に含まない。Cursorへ実装を指示する際も、開発環境の変更と本番への適用を区別する。

## 6. 参照

完全な参照一覧、固定SHA、観測の範囲は `SOURCE_EVIDENCE.json`。実装手順は `CURSOR_WINDOWS_NATIVE_FEATURE_PLAN_20261028.md`、検証対応表は `ACCEPTANCE_MATRIX.md`。

- [下流README](https://github.com/zapabob/hermes-agent-windows/blob/5531c849b424cdfee17946935eec73363917e5e7/README.md)
- [下流Desktop開発規約](https://github.com/zapabob/hermes-agent-windows/blob/5531c849b424cdfee17946935eec73363917e5e7/apps/desktop/AGENTS.md)
- [下流controlled delegation](https://github.com/zapabob/hermes-agent-windows/blob/5531c849b424cdfee17946935eec73363917e5e7/tools/delegate_tool.py)
- [上流v0.22.5](https://github.com/NousResearch/hermes-agent/releases/tag/v0.22.5)
- [上流prepared compaction PR #144684](https://github.com/NousResearch/hermes-agent/pull/144684)
- [上流vault keychain PR #144246](https://github.com/NousResearch/hermes-agent/pull/144246)
- [上流Desktop files PR #143688](https://github.com/NousResearch/hermes-agent/pull/143688)

