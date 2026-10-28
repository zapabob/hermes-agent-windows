# 受け入れ条件と検証の対応表

作成日：2026-10-28 JST。**下表は実行計画であり、全行の初期状態はNOT_RUN。** 正確なtest pathとcommandは主計画・T00で確定する。行をPASSにするには実行したcandidate SHA、fixture、command、exit code、証跡を記録する。

## 1. 機能契約

| 検証ID | 要件 / task | 必須の行動 | 意味のあるRED / mutation | Windows確認 |
|---|---|---|---|---|
| BASE-01 | 全体 / T00 | 実HEADとowner、既存実装、CodeGraph impactを照合 | 計画と現checkoutの差分を記録。無理なmutationは不要 | native環境・artifact・空き容量を記録 |
| MCP-01 | R01 / T01 | 同時callと別profileの進捗を混ぜない | call ID/epoch guardを外すと失敗 | stdio fixture 2call＋別profile |
| MCP-02 | R01 / T01 | complete/cancel後にrunningへ戻らない | closed guard削除を検出 | cancel→late progress→reconnect |
| MCP-03 | R01 / T01 | SDK未対応や切断で副作用callを再実行しない | TypeError後の再実行を検出 | fixture側の実行回数をassert |
| MCP-04 | R01 / T01 | total不明・不正値・burstでも正しく表示 | 偽100%やterminal遅延の行動test | 長い履歴で表示・入力応答 |
| QUEUE-01 | 既存維持 / T02 | 別connection/profileとlineageを分離 | scope guard削除を検出 | profile切替＋旧Promise到着 |
| QUEUE-02 | 既存維持 / T02 | 二重click・edit中ACKで別revisionを消さない | accepted前削除・revision比較削除 | Stop→park→Resumeと圧縮を含む |
| QUEUE-03 | 既存維持 / T02 | ACK喪失でpromptを失わず重複受理を防ぐ | 実際にREDならrequest identityを追加 | server受理済み・ACKだけ喪失fixture |
| PREF-01 | R01 / T02 | 要求AにBのslot進捗を表示しない | 先頭active slot採用を検出 | 同じserverでA/B並行 |
| PREF-02 | R01 / T02 | deadline計上と表示を分離、取消後に延長しない | processedの比較、closed fenceを壊す | main/auxiliary両方 |
| SET-01 | R02 / T03 | 完全なdraftを原子的に保存する | validate後saveの順序を壊す | 不正値/save失敗で旧config保持 |
| SET-02 | R02 / T03 | 古いApplyが別profile/draftを上書きしない | epoch比較削除 | local/remote/profile切替 |
| SET-03 | R02 / T03 | runtime-onlyは次child、schema関連は次session。controlled childは親route固定 | schema/prefixの途中変更、override拒否・fallback空配列を壊す | 現sessionのprefix維持、次sessionの表示/schema/admission一致 |
| DEL-01 | R03 / T04 | 未導入backend/許可外profileを明示拒否 | silent default・allowlist削除 | 通常/controlled両経路 |
| DEL-02 | R03 / T04 | sibling独立、明示fallback順序、budget/cleanup保持 | fallback=[]無視、capacity迂回 | native command失敗/cancel |
| UPD-01 | R04 / T05 | CLI/GUIでscan・disable・再同意が一致 | GUIだけ検査を省く変異 | dummy plugin更新の両経路 |
| UPD-02 | R04 / T05 | pin/GitPolicy/stashを保持 | pin無視・stash失敗成功扱い | ローカルtest Git remote |
| OAUTH-01 | R05 / T06 | 正規APIでtokenを返さず宛先・callerを拘束 | origin検査削除・redirect転送 | dummy OAuth serverと2profile |
| OAUTH-02 | R05 / T06 | OAuth宣言変更は再認証 | fingerprint比較削除 | hosts/scopes/token URL変更 |
| OAUTH-03 | R05 / T06 | refreshを直列化しlogout後に復活しない | lock/世代比較削除 | barrierとprocess競合 |
| CHOICE-01 | R06 / T07 | 選択/取消/timeout/非対話を正しく処理 | ContextVar reset削除・未知値の自動選択 | CLI/Desktop、旧connection返信 |
| KEY-01 | R07 / T08 | 検証後にだけ旧鍵を削除する | readback/decrypt省略、早い削除 | native Credential Manager往復 |
| KEY-02 | R07 / T08 | 鍵欠落時に新規鍵を作らない | missing-keyをcreateへ変える | 途中失敗→process再起動 |
| KEY-03 | R07 / T08 | profile clone/renameと跨process競合で他鍵を壊さない | ownership/lock削除 | 2process、同名profile再利用 |
| KEY-04 | R07 / T08 | file rollback時の復号/DACLを保つ | ACL迂回を既存testで検出 | old binaryへ戻す前の逆移行 |
| FILE-01 | R08 / T09 | native pickerとplugin ID別grantのみ許可 | picker迂回・plugin ID比較削除 | native picker cancel/approve/revoke |
| FILE-02 | R08 / T09 | Windows別表記・reparse・protected pathを拒否 | canonical/reparse guard削除 | NTFS junction/hardlink/ADS/device名 |
| FILE-03 | R08 / T09 | root差替え、grant破損、超過、rename衝突を拒否 | stale cache許可・silent truncate | 日本語path、ゴミ箱、root置換 |
| FILE-04 | R08 / T09 | remote接続でもDesktop-localを維持 | backendへ誤routingするfixture | profile切替・実uninstall時だけrevoke |
| HOOK-01 | R09 / T10 | durable commit後に一度だけdispatch | commit前発火・二重dispatch | 通常/rotation/外側DB失敗 |
| HOOK-02 | R09 / T10 | 失敗/cancel/staleは0、hook失敗で履歴を戻さない | closed無視・例外rollback | dummy listener timeoutとStop |
| PREP-01 | R10 / T11 | prefix一致時のみ採用、append tail保持 | fingerprint削除・tail上書き | edit/undo/route変更/圧縮競合 |
| PREP-02 | R10 / T11 | OFFは追加call0、cancel後commit0 | OFF反転・cancel guard削除 | shutdown/Stop/DB rollback |
| PREP-03 | R10 / T11 | 同GPUのinteractive優先と有限時間の取消確認 | admission迂回・無期限待機 | idle開始→新入力→取消完了→interactive、ACK喪失で復旧表示 |
| PREP-04 | R10 / T11 | OFF後に旧workerが採用/再queueされない | 世代更新・pending取消を削除 | OFFとworker完了を競合、停止未確認の二重推論0 |
| DOWN-01 | R11 / T12 | revision/validator/Rangeを照合して再開 | 200追記・ETag無視・同size混合 | 206/200/416・同size別内容 |
| DOWN-02 | R11 / T12 | 検証後だけready、既存モデルを保存 | hash省略・旧モデル削除 | pause→exit→resume、disk-full fixture |
| CLOCK-01 | R12 / T13 | 同一PCのstallだけawake時間を使う | LAN/remoteへ誤適用 | 再現したpower stateのみ |
| CLOCK-02 | R12 / T13 | Stop/deadline/同route復旧を保つ | route/turn/closed比較削除 | sleep→wake、server再起動 |
| WEB-01 | R13 / T14 | local認証/一回token/originを守る | ticket reuse・origin無視 | browser起動と期限切れ |
| WEB-02 | R13 / T14 | dashboardと競合せずowner/sessionを共有 | 二重owner/二重受理fixture | Desktop/browser切替・port使用中 |

## 2. 既存機能の回帰

| 契約 | 既存test / 観測点 | 変更が触れるtask |
|---|---|---|
| parent-owned delegation | `tests/tools/test_parent_owned_delegation.py` | T03、T04 |
| fallback順序とpin | `tests/tools/test_delegate_fallback_matrix.py` | T03、T04 |
| local進捗の信用・attempt deadline | `tests/agent/test_aux_local_prompt_progress.py`、`test_native_aux_prompt_progress.py` | T02、T11、T13 |
| 圧縮ownership/tail/durable commit | `tests/agent/test_compression_attempt_ownership.py`、`test_compression_adoption_preserves_live_tail.py` | T10、T11 |
| 要約modelの予算 | `tests/agent/test_compression_local_endpoint_budgets.py` | T10、T11 |
| native runtime選択・KV | `tests/hermes_cli/test_llama_fallback_runtime.py`、`Get-LlamaContextBudget.ps1` | T12、T13 |
| vault DACL/origin/model-blind API | `tests/test_browser_vault.py` | T08 |
| plugin Git/権限 | `tests/hermes_cli/test_plugin_update_git_boundary.py`、`test_plugin_capabilities.py` | T05、T06、T09 |
| queue/Stop/圧縮lineage | Desktop queue unitと既存3種E2E | T02、T14 |
| Desktop owner | `test:backend-stop-ownership` と必要時のnative lifecycle script | T14などownerに触る変更 |

## 3. 結果の記入方法

各検証IDの実行結果は、初期の本表を上書きする代わりに `output/reports/feature-intake-20261028/` のcandidateごとの記録へ残す。

| 項目 | 必須内容 |
|---|---|
| identity | 検証ID、task、baseline SHA、candidate SHA、artifact SHA-256 |
| execution | 正確なcommand、Windows build、fixture、exit code、所要時間 |
| result | PASS / FAIL / NOT_RUN / BLOCKED / NOT_APPLICABLE と根拠 |
| mutation | KILLED / SURVIVED / INVALID / EQUIVALENT。assertion失敗を確認 |
| regression | 関連testと結果。無関係な既存失敗を隠さない |
| rollback | 実施した復旧とデータの一致確認 |
| remaining | 未実施の理由、出荷への影響、次の具体的作業 |

スクリーンショットだけ、source文字列だけ、GUIでsuccess toastが出ただけではPASSにしない。ファイル・保存済み履歴・fixture側の受理/実行回数・実route等のauthoritativeな結果を確認する。

