# Hermes系 upstream 同期・PR・CI・再起動 引き継ぎ書

作成日: 2026-08-20（JST）  
対象: Hermes fork の公式 upstream 同期、脆弱性修正、独自機能保持、PR取り込み、CI確認、Desktop/llama/Go系再起動  
作成時点の境界: PRのマージ履歴確認までは完了。最終 main のローカル追従、最終SHAに対するCIオールグリーン確認、Desktop/llama/Go系の再起動と実ランタイム証明は未完了。

## 1. 作業場所と保護対象

主チェックアウト:

~~~text
C:\Users\downl\Documents\New project\hermes-agent
~~~

公式同期用の別チェックアウト:

~~~text
C:\Users\downl\Documents\New project\hermes-agent-upstream-sync-20260820
~~~

公式 frozen base:

~~~text
27562ad5f80e90f7d552f92dbd4af7f1f511c3c8
~~~

主チェックアウトで既存のユーザー所有・未追跡ファイルは、内容を確認しても削除、移動、stage、commitしない。

~~~text
mini_llm_planner.py
results/ 以下の7件のJSON
.omo/evidence/ 以下の監査証跡
~~~

PR70のE2E試行に由来する次の作業領域も、容量圧迫があっても即時削除しない。削除が必要な場合は、存在確認、reparse point/junction確認、内容確認、ユーザーの明示許可を先に得る。

~~~text
C:\Users\downl\Documents\New project\hermes-agent-pr70-e2e
H:\HermesBuildTemp\orphan-pr70-e2e-20260820
H:\HermesBuildTemp\orphan-pr70-e2e-files-20260820
~~~

## 2. 取り込み済みPRとコミット履歴

PR番号と実際のコミットSHAを混同しない。確認済みの主要履歴は次のとおり。

| 内容 | PR | マージコミットまたは確認SHA | 状態 |
|---|---:|---|---|
| bot formatter | #69 | fe6acdca3258dc70b5997a4436a0a172e5e86da9 | merged |
| backend skin wallpaper metadata / safe routing | #70 | 22eb18170621b36e5c64f8e9998094e759678cd0 | merged |
| model switch acknowledgement | #71 | e61e7d1909ffdbe242a7e57e4b9b888b54c0d768 | merged |
| wallpaper HTTP/file/UNC and profile scoping hardening | #72 | 97a66d442389144ac87e0e33131ed75e64bfb17f | merged |
| formatter follow-up | #73 | 54ac220eb131b4cabca7d67c14cc39ce5b3b4e26 | merged（GitHub確認済み） |
| docs model selection | #74 | 2f0b2e7f5db4240b2135665cdf793ff6b2add797 | merged |

確認時点の origin/main:

~~~text
54ac220eb131b4cabca7d67c14cc39ce5b3b4e26
~~~

主チェックアウトのローカル main は fe6acdca32... で、origin/main に対して behind 9 の状態だった。再開時は必ず git status と git ls-remote で取り直す。

PR72の個別CI run 32371761137 は、Pythonテストなど一部が成功した一方、apps/desktop / check:test:desktop:platforms と apps/desktop / check:lint が失敗していた。PRは merge queue によって取り込まれたが、このrunをオールグリーンの証明に使ってはいけない。

## 3. 再開時のGit手順

最初に主チェックアウトを読み取り中心で確認する。git clean、広域stash、reset、checkoutによる破棄を実行しない。

~~~powershell
Set-Location -LiteralPath 'C:\Users\downl\Documents\New project\hermes-agent'
git status --short --branch
git log -1 --oneline --decorate
git ls-remote origin refs/heads/main
git branch --show-current
~~~

公式の最新オブジェクトが必要な場合は、保護対象を確認した後にだけfetchする。fetch後に自動mergeしない。

~~~powershell
git fetch --prune origin main
git rev-parse HEAD
git rev-parse origin/main
git merge-base --is-ancestor HEAD origin/main
~~~

HEADがorigin/mainの祖先である場合だけ、ローカル変更と未追跡ファイルを再確認してfast-forwardする。trackedな作業変更が出た場合、または祖先関係が偽の場合は停止し、別ブランチまたは別worktreeで比較する。

~~~powershell
git status --short
git diff --name-only
git diff --cached --name-only
git merge --ff-only origin/main
~~~

最後のmergeコマンドは、直前のstatus確認で安全と判断できた場合だけ実行する。公式機能と独自機能が同等なら公式実装を基礎にし、独自側の利点だけを小さなoverlayとして保持する。API名、IPC channel、profile/connection scope、plugin SDK boundaryは公式側へ追従させる。

## 4. 変更内容を壊さないための不変条件

PR72のDesktop wallpaper経路について、次を維持する。

- backend skin metadataは (connectionId, profile) ごとに分離する。非表示接続のgateway.readyが、現在表示中ではない接続の同名skinを上書きしてはならない。
- remote file readには読み取り開始時に捕捉した connectionId と profile を渡す。非同期読み取り中の接続切替で別接続の認証経路へ流さない。
- http/https画像はrendererの直接img読み込みを使わず、Electron側のSSRF安全なURL取得を通す。DNS再解決、private/link-local/metadata宛、redirect、MIME、サイズ、timeoutのガードを落とさない。
- file URLはローカル・authorityなしだけを許可する。Windowsの file:///C:/... を C:\C:\... に二重化しない。
- UNC、network share、 \\server\share、 //server/share、encoded/mixed形式はrendererとElectron/backendの両方で拒否し、拒否前にstat/read I/Oを行わない。
- fork固有のGit IPC、watchdog/prewarm、provider rotation、semantic graph、memory/plugin surface、Go/llama embedding wiringは、公式API変更に合わせつつ失わない。

## 5. ローカル検証の既知結果

PR72変更について完了している検証:

~~~text
apps/desktop media.remote.test.ts + themes/backend-sync.test.ts: 41 passed
tests/hermes_cli/test_web_server_fs.py: 10 passed
変更TSのPrettier: pass
git diff --check: pass
~~~

未完了または失敗を含むため、完了扱いにしてはいけない検証:

~~~text
apps/desktop typecheck: 約90秒無出力のため中断。passではない
PR72 cloud run 32371761137: desktop platforms と desktop lint が失敗
PR72の完全Desktop E2E: 未実行
最終main SHAに対するCI: pending/in_progressを含み未確定
~~~

最終CI確認は、必ず最終 git rev-parse HEAD と一致するSHAで行う。

~~~powershell
$sha = git rev-parse HEAD
gh run list -R zapabob/hermes-agent-windows --workflow fork-cicd.yml --branch main --commit $sha --limit 30 --json databaseId,status,conclusion,headSha,url,workflowName
~~~

runが見つかったら、IDごとに結果とheadShaを照合する。

~~~powershell
gh run view -R zapabob/hermes-agent-windows <run-id> --json status,conclusion,headSha,url,jobs
gh run watch -R zapabob/hermes-agent-windows <run-id> --exit-status
~~~

fork-cicd.ymlはworkflow_dispatchを持つため、改名後の再検証では gh workflow run fork-cicd.yml -R zapabob/hermes-agent-windows --ref main を使える。Windows native、Linux regression、Desktop、security/lockを別々に確認し、単一jobの成功だけでオールグリーンと宣言しない。

## 6. CIの確認時点スナップショット

確認時点の origin/main 54ac220... には次が見えていた。

~~~text
CI review comment 32372964806: pending
CI review comment 32372903998: success
Publish E2E evidence 32372829908: skipped
Docker 32372825140: success
CI 32372825839: pending
auto-fix lint 32372825135: in_progress
Nix 32372825129: in_progress
~~~

この一覧は時間経過で変わる。再開時に最新一覧を取り直し、headShaが最終mainと一致しないrunを除外する。

## 7. 依存関係と脆弱性の状態

最後に確認された依存修正は、pnpm側のtarを7.5.22、uv側のh2を4.4.1に揃えたもの。Dependabot確認では候補SHA a762fef... と後続mainでopen alert 0が確認され、pnpm audit、npm audit、uv lock --checkも通過している。mainが進んでいるため、依存lockを変更する前に現行manifestとlockの整合を再確認する。

~~~powershell
uv lock --check
pnpm install --lockfile-only --frozen-lockfile --ignore-scripts --offline
pnpm why tar -r
pnpm audit --audit-level=low
npm ci --dry-run --ignore-scripts
npm audit --package-lock-only --audit-level=low
~~~

lockfileを再生成する場合は、対象lockとmanifestだけを変更し、git diff --name-onlyで無関係なformatter/generated fileが混ざっていないことを確認する。

## 8. Desktop、llama、Go系の再起動SOP

CIが最終main SHAで必要なチェックを通過してから、次の順序で実施する。実行前に現在のプロセスとlistenerを保存する。既存のllama-serverを一括killしない。

### 8.1 Python import確認とDesktop再ビルド

~~~powershell
Set-Location -LiteralPath 'C:\Users\downl\Documents\New project\hermes-agent'
$py = '.venv\Scripts\python.exe'
& $py -c "import pydantic,pydantic_core,fastapi,uvicorn; print('python imports ok')"
& $py -m hermes_cli.main desktop --build-only --force-build
~~~

最終証明に使うDesktop実体はrepo artifactに限定する。AppDataに残る古いpackaged EXEを証明に使わない。

~~~text
C:\Users\downl\Documents\New project\hermes-agent\apps\desktop\release\win-unpacked\Hermes.exe
~~~

build後、 $env:USERPROFILE\.hermes\desktop-build-stamp.json の時刻とartifactの時刻が今回buildに対応していることを確認する。

### 8.2 Go watchdog build/test

~~~powershell
Push-Location 'C:\Users\downl\Documents\New project\hermes-agent\scripts\windows\watchdog-go'
go test ./... -count=1
Pop-Location
& .\scripts\windows\Build-HermesGoWatchdog.ps1 -SkipTest
~~~

現行defaultはGo系9119。既存scheduled taskの一部は旧checkout hermes-agent-hakua-productionと9118を参照するため、admin権限で再登録するまで次回bootの永続性は未証明。current-session起動とscheduled-task修正を混同しない。

### 8.3 llama hot-swap

runtime presetは次の意図であることを確認する。

~~~text
section: qwen3.8-27b-abliterated-mtp
load-on-startup=true
models-max=1
primary GGUF: C:\Users\downl\Desktop\SO8T\gguf_models\soyaakinohara\qwen3.8-27b-abliterated-3.69bpw-12GB-MTP.gguf\qwen3.8-27b-abliterated-3.69bpw-12GB-MTP.gguf
~~~

~~~powershell
& .\scripts\windows\start-llama-hotswap.ps1 -RuntimePresetPath "$env:USERPROFILE\.hermes\llama\models-hotswap-primary-secondary.ini" -ModelsMax 1 -ForceRestart -WarmSecondary -WaitSeconds 300
~~~

### 8.4 Hermes stack

hot-swapでwarmした :8080 routerを再初期化しないよう、次の起動では -StartLlamaを付けない。

~~~powershell
& .\scripts\windows\restart-hermes-stack.ps1 -SkipTunnels -StartGoWatchdog -WaitModelsSeconds 300
~~~

embeddingを本当に再起動する場合は、netstat -anoで:8082の単一PIDを特定し、設定済みWinGet llama-serverの実行ファイルパスと一致することを確認してから、そのPIDだけを停止する。Go watchdogが別PIDで再起動したことを待って確認する。Qwen standalone scriptや全llama-server一括停止は行わない。

## 9. ランタイム完了証明

再起動後は、プロセス名だけでなく、endpoint、PID、実ファイルパス、応答内容を記録する。

~~~powershell
& .\scripts\windows\check-local-llm.ps1 -BaseUrl http://127.0.0.1:8080 -MinContext 64000
& $py scripts\standalone\qwen38_toolcall_probe.py
Invoke-RestMethod http://127.0.0.1:8080/v1/models
Invoke-RestMethod http://127.0.0.1:9920/health
Invoke-RestMethod http://127.0.0.1:9920/api/status
Invoke-RestMethod http://127.0.0.1:9119/api/status
Invoke-WebRequest http://127.0.0.1:9120/
Invoke-WebRequest http://127.0.0.1:8787/health
netstat -ano
~~~

合格条件は、Qwen qwen3.8-27b-abliterated-mtpがloaded、Huihuiがunloaded、models-max=1でloadedが一つだけ、生成子プロセスのcontextが64000以上であること。:8082/v1/embeddingsへ2入力を送り、2ベクトル、各dim 1024、有限値、ゼロベクトルでないことも確認する。:9920のdesktop/backend/embeddingがup、packagedExeがrepo artifact、DesktopのMainWindowHandleが非ゼロであることを確認する。

さらに、gatewayのstatusと:8646、harnessのstatusと:18794/health、Go watchdog :9119、dashboard :9120、health :8787のlistener/PIDを同じ記録へ残す。endpointが200でもPIDが別checkoutを指していれば合格にしない。

## 10. 停止条件と引き継ぎ時点

次のいずれかに該当したら、変更を追加せず状態を記録して停止する。

- origin/mainとローカルHEADの関係が想定外、または未コミットtracked変更が見つかった。
- 公式CIの必須jobがpending/in_progress、失敗、skippedのままで、最終SHAに対する再実行結果がない。
- Desktop typecheck、platform test、lint、Publish/E2E、Nix、Dockerの必要条件が未確認。
- wallpaperのprofile/connection scope、HTTP SSRF guard、UNC/file URL拒否のどれかが失われた。
- runtime presetのprimary GGUF、Go port、Desktop artifactが別checkoutを指す。
- scheduled taskを修正するためにadmin権限が必要だが、承認がない。
- untracked user files、証跡、model、release、junction/reparse pointを削除または上書きしそうになった。

この文書作成時点の完了判定は、PR #69〜#74のマージ履歴確認とPR72 hardeningの対象テスト確認まで。最終mainへのfast-forward、最終SHAのCICDオールグリーン、Desktop再ビルド後の可視起動、llama primary loaded、embedding 2-vector、Go/gateway/harnessの全endpoint証明は、次の作業者がこのSOPに沿って実施する。

