# Luna Max 実装計画 — Windows-native v0.21.4 semantic adoption

作成日: 2026-09-24 JST。対象は `zapabob/hermes-agent-windows` の既存 recovered 統合worktreeだけである。これは実装の作業分解と受入順序であり、上流scope変更、AppContainer profile作成、endpoint公開、課金、配備を承認する文書ではない。実装担当は `gpt-6-luna` / `reasoning_effort=max`、統合担当はGPT-6 Sol Mediumとする。独立レビューは実装担当自身の自己承認で代替しない。

## 0. 入力とこのPCで確認した現在地

| 項目 | 固定値または確認結果 |
| --- | --- |
| 統合worktree | `C:\Users\downl\Documents\New project\hermes-control-mcp-recovered-20260923` |
| 統合branch / 計画開始時HEAD | `feat/hermes-control-mcp-c-20260923-recovered` / `43801a32f9e98ddfcfe74c4be8f693b08dfd97c7`。作業中なので各packet開始時に再取得する |
| 元checkout | `C:\Users\downl\Documents\New project\hermes-agent` の `main=e6070028c9d0d75634ad7661c33fa937b682474a`。変更しない |
| 保全する未追跡物 | 統合worktreeの `.t06-pytest-integrator-safe-20260924-01/` |
| 凍結上流 | B=`b51c055a12220f8c7c18660e8599365012e19532`; R0=`345cd2b057a452236de401d3534b8502a7465e8d`; R1=`d337b736aa1e8ebecfab043842d13e4a2d2f48a3`; U=`b936546561888a54d5bf9cd7eae9629a824eb4f7` |
| 元計画ZIP | `C:\Users\downl\Downloads\hermes-workstation-master-plan-20260924-codegraph.zip`、このPCでSHA-256=`7870af3fa739d541c19b0374f4ac6496e0b561ebf85848f21b5be9a0ad95b738` を再確認 |
| 今回の改訂レビューZIP | `C:\Users\downl\Downloads\hermes-v0214-6lunaMax-review-20260924.zip`、SHA-256=`ff520100492d56bf1db7f37a06f66a2fe98ef83d291c1bbaa0114a6bba4a5795`。内部manifest記載の16 memberは全件ハッシュ一致 |
| 参照仕様 | 改訂ZIP内 `REVISED_REVIEW_PLAN.md`、`FAMILY_EXECUTION_PLAN.json`、`ACCEPTANCE_SUPPLEMENT.json`、`OWNERSHIP_PROPOSAL.json`、`BLOCKERS.json`。これらはレビュー入力であり、現HEADの実測や追加承認そのものではない |

現HEADではT11のprocess-local network budgetと取消し修正を統合済みで、統合HEADの関連63テストが成功した。T11のH: worktreeは全4コミットの同等性、tracked/untracked/ignored、reparse、証拠保全を確認して `git worktree remove` で退役済み。T09は `H:\hermes-worktrees\t09-catalogue-refresh-20260924` で独立レビューのDNS/opt-out/304指摘を修正中（確認時の修正source `ed5b82e655ef1b9d74ae616fea24d4bf5e47a7a9`）。T16は `H:\hermes-worktrees\t16-security-bounded-20260924` で定義内容の同一性、サイズ上限、Windows reparseのREDから修正中。これらのworktreeを再作成しない。T12のreceipt evaluatorは `3bf70a018b` として統合済みで、production producer/callerは未完である。T06の実AppContainer setup承認と有用なWindows正負資格は未完なので、general MCP writeを有効にしない。

添付の `BL01 LOCAL_HEAD_NOT_VERIFIED` はこのPCの現在地確認で解消した。ただし各packet開始時のHEAD/dirty fingerprintは再取得する。`BL11` のhelperには現HEADで `closing(sqlite3.connect(...))` があり、Windowsで `docs/windows/workstation-20260924/tests/test_inventory_commits.py` の11件が成功した。添付の提案selector `tests/test_inventory_commits.py` は現配置と異なる。ほかの提案selectorは未作成・未収集として扱う。所有権提案中の `UPSTREAM_PARALLEL_OWNERSHIP.yaml` と `UPSTREAM_FEATURE_LEDGER.yaml` は実際には `docs/windows/workstation-20260924/` 下にあり、`model_catalog.py` は `hermes_cli/model_catalog.py`、`gateway/host_rendezvous.py` は現HEADに存在しない。存在しないpathを新設する前にownerとcall pathを確定する。

## 1. Luna Maxへ渡す一件の大きさと必須handoff

一つの実装packetは一つの観測可能な契約と一つの失敗クラスに限る。原則としてcanonical product ownerを一つ、変更する製品ファイルを二つ以下、対応テストと証拠ファイルを持つ。二つ以上の既存owner、共有DTO、registry、`tools/delegate_tool.py`、`agent/subagent_lifecycle.py`、`tools/terminal_tool.py`、MCP service/journal、lock/版ファイルにまたがる場合は、Luna Maxは一方のownerの契約とパッチ候補を提出し、Integratorが共有ファイルを直列に接続する。worktree名が異なってもWindowsの大文字小文字、junction、hardlink、reparseを解決した同一fileなら同時編集しない。初期並行度は既存の二実装writerと一read-only reviewerを上限とし、CodeGraph writerは一件ずつ貸す。

packetを渡す前にIntegratorは、実HEAD、`git status --porcelain=v1 -uall` とignoredの分類、dirty source digest、owner lease、現存する正確なファイル、固定source SHA family、D/R1/UのCodeGraph owner/caller/callee、先行packetの結論を記録する。未知のownerは `UNASSIGNED` のままread-only trace packetから始める。添付の所有権表は候補でありedit leaseではない。

各Luna Max packetの順序は次のとおりとする。`(1)` source familyのmerge parent、fixup/revert、U最終動作と現Dのcall pathを読む。`(2)` `ADOPT / COMPOSE / ALREADY_EQUIVALENT / KEEP_DOWNSTREAM_STRONGER / NOT_APPLICABLE / DEFER / SUPERSEDED_OR_REVERTED` を根拠付きで仮判定する。`(3)` import可能な最小APIを置き、実assertionが落ちるREDを記録する。既存同等ならコード追加を行わず既存contractのGREENとmutantを記録する。`(4)` 最小製品変更でGREEN。`(5)` [LUNA_MAX_RV_BINDINGS.json](LUNA_MAX_RV_BINDINGS.json) の該当RVについて、setup/action/expectedと指定mutantを実APIへbindし、`pytest --collect-only` 等で実node IDを確定する。このbindingは添付 `ACCEPTANCE_SUPPLEMENT.json` の提案値を保存したもので、実行証拠ではない。mutantは隔離した使い捨てsourceで検証し、稼働worktreeやユーザー作業を改変しない。`(6)` 影響テスト、必須Windows native、Ruff/typing、差分、CodeGraph後段を同一source commitへ結び付ける。`(7)` 製品commitと証拠commitを分け、独立reviewへ渡す。reviewがBLOCKなら同じworktreeでRED→修正→再review。`(8)` Integratorが順序付きcherry-pick、統合HEADで再試験、台帳、同等性を確認する。`(9)` そのbranchの全コミット、tracked/untracked/ignored、未保存証拠、絶対pathとreparseを監査してから対象worktreeだけを `git worktree remove` で退役し、登録・path・空き容量を確認する。未統合・未保存・作業中のworktreeは残す。

各handoffは `packet ID / F・T・seed・RV / start HEADとdirty fingerprint / exact upstream SHA set / 現D ownerとcall path / decision / REDの実assertionとコマンド / GREENとskip理由 / required mutantのkilled・survived・invalid・timeout・not-run / Windows実機証拠 / CodeGraph before-after source SHA / product・evidence SHA / reviewer verdict / 未検証 / 次のowner` を埋める。collection/setup/import失敗をbehavioral REDと呼ばない。テスト数を異なるHEADから合算せず、必須native/client skipは未証明とする。元計画A01–A46とCG01–CG08は維持し、RV01–RV44は追加精密化として扱う。

## 2. 依存順序と公開境界

`F00 → T17-R` のread-only family reviewはT06完了を待たず開始する。T17の製品変更はそれぞれの個別依存と所有権が揃ってから行う。T11-core（統合済みのprocess-local slice）→F10aの残るDNS/redirect/cancel契約→T09-live→T10 active admission→F10bの負荷下資格の順に検証する。T11のcross-process host limitやproduction admission callerは未完成のため、T11全体を完了扱いしない。T12 evaluatorは再実装せず、T06制限実行とhost producer、durable fence、別のapply承認を接続する。packet間の機械可読な依存は [LUNA_MAX_PACKET_DAG.json](LUNA_MAX_PACKET_DAG.json) に固定し、free-textの入口だけから実行順を推測しない。

T20-liveの入口は、T04 human-once operation承認、T06有用な資格情報遮断、T07 terminal response、T09実catalogue、T10 active admission、T11 network契約、T12 trusted receipt chain、T19 authoritative UI、関連T17 P0とT15/T16 security gate、独立security reviewが同じ統合sourceで成立することを要する。MCP resourceのread権限とwrite権限、server capabilityと実client entitlementは別に判定する。ChatGPT/Codexの実clientがwrite非対応なら `BLOCKED_CLIENT_CAPABILITY` とし、read成功で書込みを代替しない。endpoint、tunnel、AppContainer profile作成、稼働runtimeの再起動、配備は具体的対象への別承認を守る。

## 3. Luna Max実装packet台帳

次表の一行を最大一件のLuna Max assignmentとする。RVは改訂ZIPの `ACCEPTANCE_SUPPLEMENT.json` にある正確なsetup/action/expected/required_mutantへ対応する。表のテストpathは提案であって現HEADの存在証明ではない。開始時に実node IDへbindする。既存同等なら製品変更を省き、mutantを含む同等性receiptだけを提出する。各行の「入口」が満たされないときはread-only調査までとし、実装や公開を進めない。

| packet | F / RV | 単一契約・成果 | 入口・owner |
| --- | --- | --- | --- |
| LM00 | F00 / RV01 | B/R0/R1/Uとlegacy-only objectの完全性、欠落時 `HISTORY_INCOMPLETE` | Integrator inventory owner。現helperへbind |
| LM01 | F00 / RV02 | HEAD/dirty fingerprint移動で古いfamily receiptを拒否 | Integrator ledger owner。現HEAD再取得 |
| LM02 | F00 / RV03 | inventory SQLite接続を成功/例外で閉じtemp dirを残さない | 現HEADは修正済み、11件GREEN。実node/mutantだけ不足分を確認 |
| LM03 | F01 / RV04 | principal/client/profile/resource/args/source/policy/epoch/nonce束縛と偽承認否定 | AUTH。既存 `tools/approval.py` とjournalの境界をtrace |
| LM04 | F01 / RV05 | 二client競合でもoperationのonce consumeは一回 | AUTH→Integrator journal共有接続。LM03後 |
| LM05 | F01 / RV06 | scratch executeとdestination applyの承認を分離 | AUTH契約後、apply ownerはIntegrator。T12と合流 |
| LM06 | F02 / RV07 | 子・補助推論・圧縮でsecret resolver/client/tokenを渡さない | PROVIDER。既存T05を再利用、共有delegate変更はIntegrator |
| LM07 | F02 / RV08 | threadを越すprofile/owner epoch/cancelの同一性 | PROVIDER。LM06後、T11 budgetを接続 |
| LM08 | F03 / RV09 | terminal完了・partial args・tool IDの重複抑制から実dispatchまで | PROVIDER。既存T07を再評価 |
| LM09 | F03 / RV10 | response loss/UNKNOWN後にeffectを自動再実行しない | PROVIDER。LM08後、journalと整合 |
| LM10 | F04 / RV11 | 制限scratchで実編集が成功し、実check失敗も検出 | NATIVE。T06 setup承認後のみnative実行 |
| LM11 | F04 / RV12 | host秘密・親process・共通`.git`への拒否と有用な許可read | NATIVE。LM10と同じWindows境界 |
| LM12 | F04 / RV13 | junction/reparse/hardlink/TOCTOUによるscratch脱出を拒否 | NATIVE。既存canonical path helperを再利用 |
| LM13 | F04 / RV14 | stop/cancelで所有process treeだけ止め、live slotを誤解放しない | NATIVE。Job ObjectとT10 ownerを接続 |
| LM14 | F04 / RV44 | 同containerの他owner・旧jobを残し、停止turnの新jobのみ処理 | 現Dでread-only到達性調査。post-U portは別amendment承認まで禁止 |
| LM15 | F05 / RV15 | Hermes Home別のElectron backend単独所有とgeneration identity | DESKTOP_OWNER。`main.ts`の現owner trace後 |
| LM16 | F05 / RV16 | locked-file updateのsnapshot/switch/recoveryを混在世代なしで実行 | DESKTOP_OWNER。LM15後、updater葉を確定 |
| LM17 | F06 / RV17 | state.db WAL reader/writer/checkpoint/crash整合 | STATE。現SQLite runtimeと実fixtureを固定 |
| LM18 | F06 / RV18 | 実SQLite source-id/backport provenanceとread purity | STATE。missing DBをreadでcreateしない。LM17と独立receipt |
| LM19 | F07 / RV19 | discovery scanで未承認pluginをimport/hookしない | PLUGIN。F01 identity契約後 |
| LM20 | F07 / RV20 | profile切替・再接続・schema更新のregistryを一回・scope内に保つ | PLUGIN。LM19後 |
| LM21 | F08 / RV21 | malicious findingとengine health・enforcement outcomeを別保持 | SECURITY。既存T15を再利用 |
| LM22 | F08 / RV22 | status/readでvault復号・更新・scanを始めない | SECURITY。T16現worktreeのreview後 |
| LM23 | F08 / RV23 | benignとEICARを別々に実scannerで資格、exit2はUNKNOWN | SECURITY。実native detectorが利用可能な時だけclose |
| LM24 | F08 / RV24 | 定義内容/サイズ/reparseとscan revisionを拘束、bounded childを確認 | SECURITY。現在T16 worktreeのRED→修正→独立reviewを継続 |
| LM25 | F09 / RV25 | free/unknown/subscription、価格・資格・送信先・tool能力を区別 | T09既存owner。現在の修正worktreeを再利用 |
| LM26 | F09 / RV26 | 12h/manual/wakeをcoalesceし、opt-out/304/dispatch直前revisionを再確認 | T09既存owner。T11-core統合済み、実接続は後段 |
| LM27 | F10 / RV27 | cross-origin redirectに認証を渡さず拒否または明示再解決 | NETWORK。T11新規shared call siteはIntegratorが接続 |
| LM28a | F10 / RV28 | DNS/slow header/body/取消下でbudget/leaseを有界に保つ | NETWORK。T11-core後、T09-liveより先に確認 |
| LM28b | F10 / RV28 | T10稼働負荷下でもstatus/cancelのcontrol応答を保つ | NETWORK。LM29/LM30後、LM28aと別receipt |
| LM29 | F11 / RV29 | resident/queued/network/scan/embeddingをtree全体で原子的に制限 | Integrator shared admission。T09/T11/T10後 |
| LM30 | F11 / RV30 | account alias/孫/paid fallbackで上限や無料policyを迂回しない | Integrator。LM29後、実providerは別資格 |
| LM31 | F12 / RV31 | host監督のcheckだけをtrusted receipt化、workerのgreen自己申告拒否 | RECEIPTS。T12 evaluatorを再利用、T06後 |
| LM32 | F12 / RV32 | apply直前のsource/destination/check-set/policy/epoch fence | RECEIPTS→Integrator Git authority。LM31と別承認後 |
| LM33 | F12 / RV33 | effect各境界のcrash/replayでUNKNOWNを自動再実行しない | RECEIPTS/Integrator。LM31-32後 |
| LM34 | F13 / RV34 | exact STOP/new epochが古いcapsuleのcontinueに勝つ | MEMORY。active owner/handoffのauthorityを先に固定 |
| LM35 | F13 / RV35 | graph down・16KiB cap下でもcritical exact refsとbounded outboxを保つ | MEMORY。LM34後、既存Ebbinghaus/Graphを利用 |
| LM36a | F14 / RV36 | JSON CLI stdoutはschemaのみ、診断はstderr | CLI。既存同等性を先に確認 |
| LM36b | F14 / RV36 | trusted skill auto-loadはsession内一回、prompt prefix安定 | CLI/PROVIDERを直列。LM36aと独立source/test receipt |
| LM37a | F14 / RV37 | temporal searchはUTC/JST境界とprofile述語を維持 | STATE/CLI境界。OR fallback mutantを必須 |
| LM37b | F14 / RV37 | background結果の安定IDと取消epochで重複/復活を防ぐ | Gateway owner。LM34後、LM37aと別diff |
| LM38 | F15 / RV38 | UIはhost seq/epochのprojectionで、partial/unknownを健康化しない | UI。T19 ownerがAPI DTOをIntegratorと同期 |
| LM39 | F15 / RV39 | 二つの実clientのauth/read/人間承認writeを別証拠にする | T20-live全入口成立後。非対応なら `BLOCKED_CLIENT_CAPABILITY` |
| LM40a | F16 / RV40 | local llama/GGUF/hot-swap/embeddingとGo所有権を保持 | Integrator、影響hunkに限る |
| LM40b | F16 / RV40 | voice/VRChat/Unity/AITuberとMoA/fallback/Switchyardを保持 | 各現ownerに分割。LM40aのgreenを流用しない |
| LM41 | F17 / RV41 | 非空trusted required checksをexact candidate SHAで確認 | Integrator。effective main rules未確認ならmerge禁止 |
| LM42 | F17 / RV42 | 14,048 metadata rows、34 seeds、1,671 historical rowsの証拠欠落を別分母で扱う | Integrator。全row→reviewed family mapping後 |
| LM43 | F17 / RV43 | feature HEAD、merge SHA、postmerge、installed runtimeを別状態にする | Integrator。T24/T25後の配備は別承認 |

LM28/LM36/LM37/LM40は添付の一つのRVが複数の段階またはowner/契約を含むため分割した。各分割packetは元RVの必要assertionとmutantを失わず、最後に元RV全体を統合HEADで再実行する。ほかのpacketも実CodeGraphで複数ownerに分かれると判明したら、同じ規則で `a/b` suffixへ分割してからleaseを発行する。44件のRVを全部 `DONE` にしても、元A/CG、未列挙metadataのP0、実client/native、最終HEAD gateが残れば完成ではない。

### 最初のdispatch cardと着手判定

`LM25/LM26 (T09)` は既存の `H:\hermes-worktrees\t09-catalogue-refresh-20260924` を再利用する。製品ownerは `downstream/delegation/free_routes.py` と `hermes_cli/model_catalog.py`、接続点は `gateway/run.py` と `hermes_cli/web_server.py` であり、これ以上共有接続点をLuna Maxへ並行貸与しない。現在の修正製品SHAは `ed5b82e655ef1b9d74ae616fea24d4bf5e47a7a9`、証拠SHAは `213a4dd74d08480ea824228f65fa0b2c54a94ba4`。44 focused test、Ruff、差分検査、固定CodeGraph after-indexを提出済みだが、独立再レビューと統合HEAD再試験前なので `REVIEW_PENDING` である。DNSのOS resolver自体は中断できないという残差をレビューで評価し、process-wide一枠、profile lock解放、後続fail-closed、shutdown境界の挙動を別々に記録する。T09-liveの実provider/native資格はLM27/LM28a後に閉じる。

`LM21–LM24 (T16)` は `H:\hermes-worktrees\t16-security-bounded-20260924` の同一branchで継続する。定義inventory error時のstale CLEAN、managed DB fallback、同サイズ/mtime復元rewrite、per-file/aggregate cap、Windows reparseを別assertionとして追う。現修正製品SHAは `6cad4f1c279b9d7643e6321c1e961d1e83b77915` で、126 passed、1 skipped、実ClamAV資格1 deselectedという報告を受けた段階である。固定CodeGraph after-index、証拠commit、独立再レビューを経るまでは `REVIEW_PENDING` とし、実scannerのbenign/EICAR双方が揃うまでLM23を `NATIVE_UNQUALIFIED` に保つ。文書のscanner選択と実装の一致もreview対象にする。

`LM00→LM01/LM02 (F00)` は次の新規read-only入口とする。Integratorが現HEADを固定し、`docs/windows/workstation-20260924/tools/inventory_commits.py`、同階層 `tests/test_inventory_commits.py`、`freeze.json` の実pathを提示する。Luna Maxはまず `pytest --collect-only -q docs/windows/workstation-20260924/tests/test_inventory_commits.py` でRV01–03にbindするnode IDを記録し、R0/R1/UのGit object到達性、legacy-only row、HEAD/dirty移動、connection closeを一件ずつ再現する。RV03は現行11件GREENのため、接続closeを外す使い捨てmutantが実テストに捕捉されるか確認し、不足すれば一件の意味のあるassertionをRED→GREENにする。成果は修正製品SHAまたは `ALREADY_EQUIVALENT` receipt、exact node IDs、mutant結果、T17-R family card入口であり、単なる件数再掲では完了しない。

F00の最初のread-only収集（統合SHA `fab4a999d1097949b287595636d7d4bc809891aa`）で、上記実pathの11 nodeはすべて収集・成功した。RV01に最も近い実nodeは `docs/windows/workstation-20260924/tests/test_inventory_commits.py::TestFrozenInventory::test_missing_legacy_commit_object_refuses_complete_inventory` だが、人工的な欠落objectだけを扱うため、`inventory_commits.py:216-217` の成功応答からlegacy SHAが欠けるmutantを捕捉する保証はない。LM00の最初の変更は、その欠落応答を実fixtureで再現する一件のassertionとする。RV02の提案nodeは現存せず、既存 `test_unknown_and_mismatched_integration_heads_refuse_output` は与えたHEADの一致だけを検査する。family receiptとdirty fingerprintのvalidator ownerは `UNASSIGNED` のため、LM01はowner設計を先に確定する。RV03も提案nodeは現存せず、`generate` は `TemporaryDirectory` と `closing(sqlite3.connect(...))` を使うがcloseの直接assertionがない。LM02は成功と例外の両方で接続closeとtemp削除を検査してから `closing` 除去mutantを試す。実行コマンドは `& '.\.venv\Scripts\python.exe' -m pytest --collect-only -q -p no:cacheprovider docs/windows/workstation-20260924/tests/test_inventory_commits.py`、確認結果は11 collected / 11 passedである。

各packetのdispatch直前にこのカードのSHA/statusを再観測し、`LUNA_MAX_PACKET_DAG.json` の `after` は製品変更の前提、`closure_gates` は完了資格として扱う。進行中のT09/T16をF00が完了するまで差し戻す意味ではない。両者の既存実装は凍結済み入力に基づいて継続し、統合時にF00の再確認へ照合する。

## 4. 母集団のsemantic reviewとpost-Uの扱い

T01の三固定窓は報告値2,777 / 5,173 / 993、unique commits 8,943、historical ledger 5,105、metadata rows 14,048、seed 34（P0 16）、critical historical current receipt欠落1,671である。これらは実装数でもparity率でもない。F00でSHA集合の重複、merge/resolution、legacy-only blob、seed対全row mappingを再計算する。T17-RのLuna Max packetは一つのsemantic familyと一つの現D ownerに限り、source family最終状態、Windows適用可能性、existing-equivalence、code/test/mutant、著者、残るrowをcardへ記録する。未監査P0を `DEFER` で帳消しにしない。`NOT_APPLICABLE` は現在の到達不能性と再訪条件を必要とする。

観測された `upstream/main=94119759c69bdbef43efe229d079ecebedf69106` はUより先で、read-only compareはUから727コミット先行を示した。添付レビューのowner-scoped process cleanup候補4 SHA（`fc3533d1237cce0175c35364155bfc779f639723`、`9fea861eeb7c521d9ac7b3b44f79ec7824902bfc`、`529d683d6a3ccde9a12303d84f268da0734afefb`、`b7cfba18e101ce8b06eb51d7dc3ff53a586208a9`）は別のread-only LM14調査対象である。現DでRV44の到達性と未修正を実証し、同等実装がない場合に限り、exact SHA allowlist・依存・著者・Windows回帰・rollbackを持つ別amendmentを具体化する。Uそのものを変更せず、承認前にpost-Uコードを移植しない。727件全体を採用する指示とも解釈しない。

## 5. T24/T25の資格と完了判定

全family cardとrow mapping、P0未監査/未証明ゼロ、元A/CGとRV全件、必須mutant、native Windows、二実client、独立security reviewが揃って初めてT24を始める。最終feature HEADを一つ固定し、そのSHAでrepositoryの実コマンドによりPython/parity、Ruff/設定済みtyping、Desktop JS/TS/lint/i18n、Windows/Go、security、dependency lock/build整合性を取得する。ひとつでもsource commitが増えたら該当gateを再実行する。`pyproject.toml`、`hermes_cli/__init__.py`、`apps/desktop/package.json`、`downstream/distribution.json` とlock/build metadataを同時点で評価し、上流R1/Uの意味論的対応と下流公開版を別に記録して0.21.4 patch版が適切か決める。版名だけ先に上げない。

T25は実効main保護・非空のtrusted required contexts・通常PR・独立reviewを確認してから行う。direct main push、force push、admin bypass、guard削除、無断 `ci-reviewed` はしない。merge後のmain SHAとCI、実際のinstalled binary/source/generation、ChatGPT/Codex各clientのauth/read/approved-writeは別々の証拠であり、配備を伴う操作は別承認である。安全判断、必要権限、実client制限だけが残るときは具体的なblockerで止め、完了と記さない。
