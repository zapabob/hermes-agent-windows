# DesktopのGit CRUDをAIエージェントから操作する

Hermes Desktopのチャットから、既存の`terminal`ツールを使って、そのセッションの作業リポジトリを操作できます。結果はGitコマンドで検証し、`focus_pane(pane="review")`でDesktopの変更確認画面を開きます。本書は既存ツールの操作手順です。新しいGitツール、Electron IPCの直接呼び出し、dashboardの認証トークン取得は必要ありません。

DesktopのGit画面にはブランチ、タグ、stash、worktree、ステージ、コミット、fetch/pull/pushの操作があります。同じリポジトリをterminalで変更するとGitの状態が更新されます。画面の更新には再読込が必要になる場合があります。terminalの作業先とDesktopで選択中のリポジトリが同一か、最初に確認してください。リモート接続ではterminalもリモートのファイルシステムを操作します。

## エージェントへの依頼例

```text
現在のDesktopセッションのリポジトリを確認し、codex/describe-changeを作成してください。
依頼した変更だけをステージしてコミットし、差分をreview画面に表示してください。
プッシュとブランチ削除はまだ行わないでください。
```

既存の`github-repo-management`スキルを読み、本書を`read_file`で参照できます。実行には`terminal`を使います。`/worktree`はCLI専用なので、Desktopの共通CRUDコマンドとしては扱いません。

## 対象と承認

コミット先は開発元のupstreamに固定されていません。会話追従では選択中の会話が所有する作業ディレクトリ、明示的に選んだ項目ではそのworktreeを使います。会話の作業場所が未確定の間はGit変更を開始しません。タイルの作業場所が不明な場合も、メイン会話のリポジトリへ代替しません。

Desktopのpushは対象リポジトリのGit設定を使います。trackingがある場合は通常のpush、ない場合はそのリポジトリのoriginと現在のブランチへ初回pushします。リポジトリのupstream tracking設定は、Hermes開発元のupstreamリポジトリを意味しません。push先を変更する依頼がなければremote設定を書き換えません。

ユーザーが指定した作業先の絶対パスを使い、Gitの終了コードが非ゼロなら後続の書き込みを止めます。対象が不明な場合は書き込みを進めません。terminalの既存承認機構と現在のmanual/smart/off設定を維持し、承認設定を変更して操作を通しません。push、削除、変更の破棄は依頼された対象と範囲に限定します。APIへのアクセス認証はGit変更の承認を意味しません。

未知の取得済みリポジトリを、安全だと自動判断しないでください。本書のコマンド例はユーザーが操作を認めた作業先向けです。S06のhostile Git対策は別の実装台帳で管理されており、本書の追加によってその完了を宣言するものではありません。

## 最初の参照操作

以下はPowerShellの例です。`$repo`を依頼された絶対パスに置き換えます。変数名に`$HOME`や`$PID`を使いません。

```powershell
$repo = 'C:\Work\Example Repo'
git -C $repo rev-parse --show-toplevel
git -C $repo status --short --branch
git -C $repo diff --no-ext-diff --no-textconv --
git -C $repo diff --cached --no-ext-diff --no-textconv --
git -C $repo log -5 --format='%h %s'
```

別々の`terminal`呼び出しで終了コードを確認します。既存の変更、未追跡ファイル、秘密情報、生成物は依頼した変更と区別します。共有ログにURL内の資格情報やトークンを出さないでください。

## CRUDの対応

| 対象 | 作成 | 参照 | 更新 | 削除 |
| --- | --- | --- | --- | --- |
| ブランチ | `git -C $repo branch codex/example HEAD` | `git -C $repo branch --list` | `git -C $repo branch -m codex/example codex/renamed` | `git -C $repo branch -d codex/renamed` |
| タグ | `git -C $repo tag agent-example HEAD` | `git -C $repo tag --list` | 新名で作成し、旧名の削除は別に承認・実行 | `git -C $repo tag -d agent-example` |
| worktree | `git -C $repo worktree add -b codex/work $worktree HEAD` | `git -C $repo worktree list --porcelain` | 対象worktree内で編集・ステージ・コミット | `git -C $repo worktree remove $worktree` |
| ステージ | `git -C $repo add -- docs/example.md` | `git -C $repo diff --cached --name-status` | 同じ指定ファイルを再度`add --` | `git -C $repo restore --staged -- docs/example.md` |
| stash | `git -C $repo stash push -m agent-example` | `git -C $repo stash list --format='%gd %H %s'` | 検証したSHAを`stash apply` | 再確認したselectorを`stash drop` |

`$worktree = 'C:\Work\Example Worktree'`などの絶対パスを先に指定し、既存ディレクトリへ重ねません。`-f`、`-D`、`reset --hard`、`clean`、force pushを通常手順へ追加しません。

ブランチの切替は`git -C $repo switch codex/example`です。切替前後にstatusを確認し、変更を捨てたり自動退避したりして切替を強行しません。ブランチ削除前には現在のブランチ、マージ済みか、worktreeで使用中か、復元に必要なSHAを確認します。`-d`が拒否した場合はその理由を報告します。

stashの適用は`git -C $repo stash apply <確認したSHA>`とし、適用後にstatusと競合を確認します。失敗や競合があればstashを保持します。削除の直前に`stash list`を再取得してselectorとSHAの一致を確かめます。stashを通常の作業開始時に自動作成しません。

## コミットと公開

対象ファイルを一つずつ指定してステージし、`diff --cached --name-status`と`diff --cached`で公開範囲を確認します。ステージが空ならコミットしません。Desktopのコミット実装には、ステージが空のとき全変更をステージする経路があるため、エージェントは明示的なステージを先に行います。

```powershell
git -C $repo add -- docs/example.md
git -C $repo diff --cached --name-status
git -C $repo diff --cached --no-ext-diff --no-textconv --
git -C $repo commit -m 'docs: explain the requested change'
git -C $repo log -1 --format='%H %s'
git -C $repo status --short --branch
```

pushが依頼に含まれる場合だけ、リモートと対象ブランチを確認して`git -C $repo push origin codex/example`を実行します。終了後に対象remote refのSHAとローカルコミットを照合します。mainへの公開は、mainへの公開がユーザーから認められた場合に限定します。push成功、CI成功、稼働中Desktopへの反映は別々に確認します。

fetchは`git -C $repo fetch origin`、pullは変更が保全されていることを確認して`git -C $repo pull --ff-only`です。失敗時にreset、clean、force指定へ切り替えません。

## Desktopで結果を見る

```text
focus_pane(pane="review")
```

これは画面を開く要求です。Gitの実行成功や画面上の差分内容を証明する応答ではありません。Gitのstatus、ステージ済み差分、コミットSHAを別に確認します。`tour(action="targets", surface="app")`で現在の画面の説明対象を取得し、`tour(action="show", ...)`で操作箇所を案内できます。tourはクリックやGit変更を実行しません。

Desktopの接続がないセッションでは`focus_pane`が利用できません。その場合はterminalの確認結果を返します。Gitボタンと同じIPC/RESTをエージェントへ直接公開する専用bridgeは、本手順には含まれません。

## 実装の参照先

操作承認は`tools/terminal_tool.py`、画面表示は`tools/focus_pane_tool.py`、ガイド表示は`tools/tour_tool.py`が担当します。DesktopのCRUDは`apps/desktop/electron/git-ipc.ts`、local/remoteの選択は`apps/desktop/src/lib/desktop-git.ts`、remote RESTは`hermes_cli/web_routers/git.py`と`hermes_cli/web_git.py`にあります。認証トークンを取得してRESTに直接書き込む手順は案内しません。
