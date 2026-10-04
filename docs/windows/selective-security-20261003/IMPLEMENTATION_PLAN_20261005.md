# Windows selective security continuation plan — 2026-10-05

07:48 JST更新：修正をmainへ公開したコミットはfeda2921da95cb5d112e49f84cdb932721be762d。Desktop lintは57から0エラー、updater30 PASS、同じ修正sourceでDesktop71 PASS、native7件すべて終了0、CREATE／EXIT／保持HANDLE1279一致、typecheck0、Graph complete／pending0を確認し、sourceと実証拠の独立レビューはAPPROVEとなった。詳細はS06/ci-repair-acceptance-20261005.json。旧Python866は履歴であり、今回再実行した全Python結果とは扱わない。

canonical CLEANでDesktop pack終了0、install stampもfedaと一致。新しいlaunchと別verifyで同一保持identity、所有backend HTTP200、medium integrity、可視応答windowを確認した。Goは07:06の実admin再起動後検証を保持し、今回のTS修正ではGo製品を変更していない。Goを再起動・再probeせず、観測日時を明示した。llama／embeddingはNO_TOUCH。runtime-closeout-20261005.jsonに新旧のepochを分けて記録した。

exact-SHA CIはci-observation-repair-20261005.jsonの観測時点で実行中・未完了を含み、全required successを確認できていない。後続7 familiesと補助6項目はOPENで、全campaignは未完了。最終closeout docsとcarry metricsは製品変更とは別のcommitで公開し、Desktop stampのbuild SHAと最終docs SHAを区別する。

S05 private RED-v2は12 sourceの変更前後一致、3 semantic FAIL／0 ERROR、product edits 0。未列挙Git checkoutのRust起動意図、checkout venvのPython選択、最終overrideによるoperator Python置換がREDとなった。実LSP／installer起動は遮断しており、GREEN／native／mutants／family受入は未実施。公開要約はS05/red-checkpoint-20261005.json、raw logsは私有保管。

以下の初回公開・build・runtime・旧TS/native記録は78公開epochの履歴であり、最新修正sourceの現在値ではない。

この文書はS06ローカルgateの到達点と未完了familyの実装計画を分けて記録する。受入記録は別receiptへ結び付け、campaign完了を宣言しない。対象11 familyと凍結入力は変更しない。再開時の作業期限は2026-10-05 08:00 JSTで、S01・S02・S03に続き、S06、S05、S08、S07、S04、S09、S10、S11の順に進める。部分的なテスト成功からfamily完了を宣言しない。

R_BEFOREは63279301bcbdc185c1b07b98a9312eb0c862f26d、R_AFTERはd3630f853239e8c41ce7201e09fbdf39bcbc5431、U_TARGETは4ed093cb6be8a2fadb39e770898f6989fc67201d、D_BASEはc20e98f1370c588645d796047788e3b6f9cc749d。凍結snapshotは更新しない。既存の個人設定、認証情報、生成物、無関係なWIPを公開対象へ含めない。

## S06 — Historical publication; CI-repair audit pending

S06の対象は製品36ファイルとtest helper 1ファイルのinventory 37、focused validation tests 49、native fixture／contracts 5の計91 paths。親が取り込んだ74 transfer pathsと既存維持17 pathsはintegrationの91 raw bindingsとPUBで一致し、integration／PUBのtypecheckはともに終了0。共有Python command resolver、Git policy transport、transport assetと既存Python ownerを一体として扱う。Desktop Gitの選択会話repo修正2e68をrenderer側に保全し、policy owner rootを操作対象repoの代わりに使わない。

再利用するOct4 Python回帰は866 PASS、0 FAIL、12 SKIP、明示除外3、45ファイルの重複しない選択。修正前epochの95 source bindingsを当時のbytesへ再照合し、91 public／4 privateに分けて保持した。これは新たな全実行ではない。この91 public proof bindingsとpublication scopeの91 bindingsは、数が同じでも別の集合である。

修正前epochのTS回帰は、正しい隔離環境のv4からref 23／review 23 PASSを使い、既存のprivate module budget 90秒を復元したv5のworktree全25 PASSと合わせた71件のunion。v4全体は15秒制限によるworktree 4 timeoutのためexit1のまま残す。先行direct v3は66 PASS／5 timeout、isolated v3はNUL config sourceのsetup失敗として保存する。v5成功を使って旧run全体をPASSへ書き換えない。製品probe 2秒、native外側90秒、Job累計256の境界は変更していない。

凍結fixture runnerはf60b75fedfe520bb9543c5531efbd31d012dd9f35d6d257cdc6ed82c4ae28fc4、Python contractsは31a7d2df74cb942fa6f5a3484a9f83d30395fa082e828ca9bc7b98ec228c1803。現行106 pure／9 selfcheck PASS、fixture protocol mutants 22/22 KILL。製品mutantsはM01・M02・M03・M04・M06の5件KILLでbaseline復元済み、M05はUNVERIFIED。fixture mutantsと製品mutantsを混ぜて件数や受入範囲を広げない。

accepted native v3はGit、GH-large、GH-positive、GH-deadline、output、resolver、staticの7 actual Jobsで全件PASS、独立receipt review APPROVE。CREATE合計1279で各Jobは249／215／84／52／239／215／225、各Jobのcleanup前後active0、全保持HANDLEのEXITED、完全identity captureとCREATE／EXIT、前後coverageの一致を確認した。UNKNOWNを成功へ変更せず、同一source、登録完全identity、retired consoleの生成区間・Job所属を保った。GitとGH-deadlineのowned listener閉鎖も確認した。旧native v1／v2の失敗は失敗のまま保持する。v2の製品payload成功・249捕捉は、最終照合33秒で元90秒期限を越えたcontroller exit124の受入拒否を取り消さない。v3へのfixture変更は製品bytesを変更していない。

S06は78d6530fad9b214a5a2e69f73e34eecf7450d4bcとして公開した。PUB Graphは終了0／complete／pending0、独立レビューもAPPROVE。canonical buildは同SHAで終了0・dirty=false、Desktopの可視応答／所有backend HTTP200とGoの実管理者restart／同一保持identity／owned healthを確認した。exact-SHA CIのTier-1 failureとMain pendingは未達として残る。詳細はHANDOFF_20261005.md、runtime-closeout-20261005.json、ci-observation-s06-20261005.jsonを参照する。composition base a3f8の同時作業を保全した。

## S05 — LSP workspace authority

S05 private RED-v2は12 sourceの変更前後一致、3 semantic FAIL／0 ERROR、product edits 0。未列挙Git checkoutのRust起動意図、checkout venvのPython選択、最終overrideによるoperator Python置換がREDとなった。実LSP／installer起動は遮断しており、GREEN／native／mutants／family受入は未実施。公開要約はS05/red-checkpoint-20261005.json、raw logsは私有保管。

既存Git検出が自動的に全checkoutを信頼する状態を改める。trust入力はHermes launch workspaceとoperatorが明示するlsp.trusted_workspacesとし、モデルによるcd、cron、Kanban等の移動を区別する。nested repositoryへ自動的に信頼を伝播させない。近傍Git boundary、nested checkout、後から追加された.git、Windows realpath・junction・caseを検証する。既存のlexical LSP identityを維持する。

profile/callerのauthority snapshotとpolicy generationをclient cache、起動待ちfuture、builder、installer、startまで通す。信頼失効時に既存clientと未公開futureを再確認し、他profileやprocess-wide trust unionへ流用しない。拒否を恒久的な故障cacheへ変換しない。

非信頼checkoutのproject venv、PATH、SDK、Rust build/proc-macro、Vue/Svelte等のproject code実行を起動前に拒否する。operator VIRTUAL_ENVが非信頼checkoutを指す場合も検査する。正当なinstalled SDKと信頼済みprojectの正例を残す。user overrideの適用後にもinitialize payloadの安全条件を確定する。

tools/file_operations.pyの_check_lintは、LSP無効・不在・拒否時も実行cwdを検査する。npx TypeScriptやrustfmt fallbackから境界を迂回させず、in-process構文検査とread/write/patch/V4Aを維持する。malformed config、readonly共有設定、profile変更、warm cache/future、junctionをREDとnativeの両方で検証する。既存のS05 implementation-plan-20261004.mdと再開時のsourceレビューを同じbytesで照合してから実装する。

## S08 — Backup and restore integrity

ordinary ZIP memberの失敗をskipして正常なcanonical backupへ公開しない。全member失敗時も空の正常backupを残さない。既存のatomic output、SQLite backup API、WAL/SHM、holder検査、permissions、secret path除外を維持して最小COMPOSEする。

importはmember数・サイズ・圧縮率の既存上限を残し、対象memberすべてのEOF、CRC、展開可能性を最初のlive writeより前に確認する。後半member破損で前半のconfigやDBが書かれないREDを作る。SQLite restoreはsourceの検証をdest接続・checkpoint・writeとfallbackより前に行い、破損sourceでlive DBを変えない。

実検証はtest-owned home/SQLite/archiveに限定する。profile wrapperやgateway serviceの起動はその境界だけ隔離し、archive/SQLite owner本体をmockしない。upstreamの世代管理・PM等の新subsystemを一括移植しない。incomplete publish、後置SQLite検査、途中write、CRC skip-successの元mutantsと正例を検証する。

## S07 — Corrupt cron store

nonrepairing peekのNoneを空storeや保存許可と扱わない。pre-stageとverify-after-stageの両方でunknown baselineを拒否し、stampにより省略したre-peekと実際の読込失敗を区別する。既存profile lock、concurrent merge、removed_ids、ownership、atomic replaceを残す。明示的replace=Trueの災害復旧正例だけは維持する。

初期破損とstaging中の破損で通常create/update/saveを拒否し、元bytesのhashを保つ。missing-store作成、正常保存、明示修復、並行追加・削除・stamp正例を検証する。live cronやschedulerには接続しない。

## S04 — Outbound URL credential redaction

agent/redact.pyを既存policy ownerとして、debug share、Gateway /debug、Desktop diagnostics、system dump、Nous圧縮uploadの実際の送信表現へstrict URL passを適用する。global redaction disabledや送信redact=Falseでも外部へcredentialを残さない。local raw表示、通常OAuth link、presigned transport URLの機能を維持する。

userinfo全体、query/fragment、AWS/Google/Azure SAS等の署名値を消し、scheme・host・path・parameter名・公開値と既存Windows privacy removalを残す。synthetic値を使ったowned loopback receiverでpaste POST、multipart、gzipの実bodyを確認する。source stringやAPIだけをDesktop UI実行証拠としない。

## S09 — Approval profile scope

表示中profile Bのmanual/smart/off read/writeがBだけを読む・変更するよう、既存cache keyに加えてconfig.get/config.setのbackend requestにもauthorityを明示する。launch profile Aとdefault/blank profileの既存precedenceを保つ。三modeのdownstream意味論は変更しない。

現在のsourceレビューでは、profile Bを読むContextVar経路に対して_save_cfgがlaunch profile Aの保存先を使う組合せが残る。cache／request parameterだけのADOPTでは閉じず、既存backend config.get/setと_save_cfgのownerを最小COMPOSEする。manual／smart／off、blank profileとdefaultのprecedence、既存deny／承認意味論を変えない。A=manual／B=smartからB=offへ変更し、reload／restart後もAが不変であるRED・実検証・mutantsをsource-boundで揃える。現時点では未実装・未受入。

test-owned profile A=manual/B=smartから、Bをoffへ変更してrestart/reload後もA=manual/B=offとなる実検証を行う。profile parameter欠落、blankを誤ってdefault文字列として送信、cacheだけprofile分離のmutantsを拒否する。

## S10 — Spaced Windows command paths

windows-child-optionsの既存ownerに最小helperを置き、現行の同期version/serve-help probe、primary/pool backend spawnとrelaunchへ適用する。upstreamの非同期probe・spawn coordinatorは一括移植しない。hidden child options、probe予算、profile routingと保持したbackend ownershipを残す。

U_TARGETのhelperはexecutableだけをquoteする。原指示書のM02はspaceを含むargument pathも要求するため、実cmd経路から取得したargvでそのままでは十分かを検証する。shell=false、非Windows、既quote・空commandの正例を保持する。test-owned Hermes Test Workspaceからversion、help、primary、pool、relaunchを別々に実行し、実際のユーザーbackendをfixtureとして起動しない。

## S11 — Dead PTY child with held endpoint

reap_idleの既存ownerへbridge/process livenessをcomposeし、foreground child死亡後にgrandchildがslaveを保持してEOFが来ない場合もregistry slotとresourceを解放する。既存TTL、race fix、capacity semanticsを保ち、live childを誤reapしない。

Windowsではtest-owned ConPTY/bridgeで実際の保持endpointを作り、childの死亡、grandchildの残留、liveness false、registry除去とowned resource cleanupを確認する。非Windows実装の一括copyやproduction PTYへの接続を避ける。liveness削除、EOFだけへの後退、live childの誤判定のmutantsを検証する。

## Publication and runtime closeout

Honcho session naming、OpenManus revision、SillyTavern status、Tookie status、Akari submodule status、Neuro vendor revisionの6 auxiliary metadata callerも未受入として残す。各ownerと実際のGit authority、bounded refusal時のunknown/empty正例を独立して確認し、主familyや866件の回帰結果から完了を推定しない。

受入済み範囲だけを明示stageしてmainへ公開し、remote refとlocal treeを照合する。06:37時点のprimary dirtyはscripts/standalone/sync_memory.pyのみだった。その後、別作業の8-path commitがS06と重複せず取り込まれ、公開・ビルド前後のprimaryはCLEAN、公開baseはa3f8となった。旧dirty記録は履歴として保全し、現在のdirtyや旧10 WIPと混同しない。並行変更と未追跡metadataを一括stage／reset／cleanしない。S06以降の未受入bytesとprivate raw receiptを一括公開しない。全11 familyの完了、local test、exact-SHA CI、Desktop build/restart、Go owned healthは別の証拠で判断する。

Desktopの再ビルドはcanonical checkoutで行い、exact packaged exeとPID/birth/保持handleを使って停止・起動・可視応答・所有backend HTTPを確認する。Goは実operator guardとlock/exe/birth/同一handleの検査を保ち、今回の起動ではembedding supervisionを付けない。llama/embeddingのprobe、設定変更、起動・停止・再起動は行わない。新receiptを作り、過去PIDや期限切れreceiptを再利用しない。

期限時に残る作業はdelivery ledgerとhandoffへ失敗epoch、source binding、次のRED・受入条件・rollback位置とともに残す。main b5be59dbcbf816a20f6b0d79495b0091afe02577のCI run37209696594は、2026-10-05 05:36:57 JSTの[ci-observation-20261005.json](ci-observation-20261005.json)でcompleted/failureを確認した。旧Oct4 closeoutのin_progressはその時点の履歴であり、終端状態の根拠に使わない。新しい公開SHAのCIは改めて照合し、pendingやskipを成功としない。

## Oct5 closeout and next implementation

残る7 familiesはS05、S08、S07、S04、S09、S10、S11で、上記scoped planをOPENとして維持する。Honcho、OpenManus、SillyTavern、Tookie、Akari、Neuroの6 auxiliary metadataも全件OPEN。S06の結果から検証を省略しない。

初回S06 family commitは78d6530fad9b214a5a2e69f73e34eecf7450d4bc。当時の公開・Graph・build・Desktop／Goの実機closeoutを履歴として保全し、そのepochのCI failure／pendingも残した。最新修正の監査・公開・CI・Desktop restartは親の更新待ち。次の実装はS05のlaunch/profile authority REDとWindowsの信頼済み正例から始める。各familyを別commitにし、source、RED／GREEN、native、regression、mutants、fresh Graph、独立レビューが揃った範囲のみ公開する。未受入bytesを実際のruntimeへ混ぜない。

rollbackはgit revertでS06 family commitだけを対象にする。whole-tree reset／clean、並行変更、2e68、S01／S02／S03を巻き戻さない。Desktop packageの旧unpacked backupはbuild ownerが保持しており、rollbackは次の明示された保守時に行う。llama／embeddingは今回NO_TOUCHのまま。実装計画、台帳、handoffの記録は次回もsource SHAと現在の状態へ照合する。
