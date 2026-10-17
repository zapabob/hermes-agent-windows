# v0.22.2 選択実装の保存点 — 2026-10-17

ユーザーの区切り指示により、製品の採用境界を
`23effd145acf06693cf786e6212e76d0a9c8e893` として保存する。
これは対象試験を終えた実装の保存点であり、全計画完了、完全な上流互換性、
Windows 安定版リリース、全 CI 成功を意味しない。
この記録以降の運用結果は `CHECKPOINT_RUNTIME_20261017.md` に記載する。

## 入力と権限

入力 ZIP、実装計画書、START_PROMPT の固定 SHA と source object は
`SELECTIVE_20261017.md` / `.json` に記録済み。添付文書内の実行指示は、
公開や OS 設定変更の独立した許可としては扱っていない。

今回、人間から main への commit/push、ファイルを削除しない整理、
残作業・棚卸・実装ログの保存、Hermes 系再起動を直接指示された。
追加回答で通常版 Desktop による hermes:// 関連付け登録も明示的に許可された。
これは通常版の運用再起動の許可であり、native E2E の無条件再開ではない。
8 時間の実モデル連続試験と実 sleep/resume 3 回は、人間の指定どおり NOT_RUN。
利用者の PC をそれらの代替試験環境にしない。

## 実装・棚卸の現在地

| 対象 | 採用した実装・証拠 | 未完了の境界 |
| --- | --- | --- |
| F01 favorites / F02 custom endpoint | provider/model ごとのお気に入り、保存済み未掲載モデルの経路を対象試験で確認 | 新しい packaged Desktop での一連の操作、実モデルを用いた確認は未完了。未採用 native テストは WIP 保存 |
| F03 status / B01 cron / B02 TTS / B03 support redaction / B04 PTY | 軽量 summary、未知 baseline の拒否、既存音声の復元、共有出力の秘匿、同一キーの PTY 置換保護 | 初期選択証拠は Python 655 passed / 5 skipped、UI 15 passed。全運用経路の合格ではない |
| F04 Gateway busy policy | 会話単位 queue/steer/interrupt と保存・停止時の順序を実装。対象 218 件、7 fault 検出 | 実チャネルと実モデルでの acceptance は未完了 |
| F06 classic CLI | 実 CLI queue の対象 69 件、2 fault 検出 | 他の CLI/TUI 操作全体の acceptance へ拡張しない |
| FX-A04 profiles | 選択中の raw model/endpoint/credential とプロファイル作成先の所有権を修正。対象 154 passed / 3 skipped、5 fault 検出 | 除外した backend-stop、全 public profile journey と実機確認は未完了 |
| FX-A02 core / classic CLI steer | 停止した guidance の復活防止、遅延入力の FIFO、実 tool/file/SQLite 経路。対象 185 passed、5 fault 検出 | 全 public new/resume/profile、他の UI・Gateway 経路は未完了 |
| FX-A02 Gateway / API stream | 旧世代 entry・cache・follow-up・outbound の抑止、API terminal/drain/constructor cancellation。対象 96 passed、9 fault sets 検出 | 下記 3 P2、全 public session transitions、実 transport / process kill は未完了 |
| C01 Security Center | verdict / engine health / execution decision を分離し、接続変更後の古い結果を排除 | quarantine/restore/watch/update/approval の実効果確認は未完了 |
| MCP / Windows / history | 固定上流 snapshot と既存の preserve 判断・除外規則を保持 | Control/外向き MCP の lifecycle、vendor runtime 独立性、U01–U18、履歴全件分類は未完了 |

各行は別の対象選択・時点の証拠であり、合計して一つの全体合格件数にしない。
正確な node 選択、除外、代替 leaf、試験・fault・source binding は companion JSON を参照する。

## 優先して再開する残作業

1. Gateway の native image / model note / skill note を、現在の run generation と同じ
   lock 契約で取得する。古い producer の await 後の publish、境界 cleanup も含めて保護する。
   次の turn 用 note を通常の generation 更新で失わないこと。
2. Gateway approval / clarify の登録、待機、send、finally cleanup を実行所有者へ結び付ける。
   古い実行の cleanup が新しい callback・queue・回答を取り消さないこと。
   真の session boundary の全取消と、実行終了の限定取消を区別する。
3. API のプロセス回収を実行所有者ごとにする。task/baseline/epoch の別々の読み取り、
   worker clear 後の権限消失、同一会話の先行・後発 run、sandbox key、handoff を扱う。
   下記 WIP は未採用であり、そのまま再適用・公開しない。
4. F01/F02 と full FX-A02 の packaged/public journey、F09 の実 incremental recognizer と assets、
   Security Center と MCP の実効果、cold vendor runtime 独立性、U01–U18 を対象ごとに閉じる。
5. 履歴の母集団 22,565 commits / 23,218 parent edges を分類する。
   既存の 20 review rows は全母集団の代わりにならない。

## 未採用 WIP とファイル保全

作業用 checkout 内の `tmp/selective-20261017/checkpoint-wip-20261017/` に、
7 ファイルの完全コピー、SHA-256 manifest、tracked.patch、未追跡の元ファイルを保存した。
全コピーをバイト比較した後で、4 tracked ファイルを採用済み Git blob へ戻した。
3 untracked ファイルは同じ checkout の保存先へ移動した。ファイル削除、reset、clean、stash は行っていない。
試験ログ、失敗証拠、graph、harness、旧作業ツリーも残している。

WIP の製品ファイルは `gateway/platforms/api_server.py` と `tools/process_registry.py`。
専用 API / registry テスト、既存 API / stream テスト変更、未採用 favorites native テストを含む。
API 22 件、registry 19 件が通った時点はあるが、その後追加した実 handoff / kill-outcome
テストは未実行。6 fault の helper は作成のみで、適用・検出確認は未完了。
これらを採用済み試験件数に含めない。

未採用 WIP の独立レビューでは、Windows Popen の taskkill、環境 backend の戻り値、
POSIX PTY の terminate、systemd scope stop の失敗を killed と確定しない契約が必要と分かった。
cleanup 完了と raw fallback を省く権限を分離し、所有者変更後の直接 kill を防ぐ必要もある。
POSIX Popen は親 PID だけでなく列挙した子の終了確認・確認不能も扱う。
全子孫停止の証明には containment の限界を明記する。

再開時は manifest を照合し、採用境界から別 branch に限定して適用する。
新しい strict-result 試験を先に実行して RED を確認し、修正、GREEN、fault 検出、
独立レビュー、正確な試験済み blob binding の順で受け入れる。

## 検証・運用の限界

採用境界の Gateway/API proof にある 8 Python ファイルは、保存後の現在ファイルと
試験時 SHA-256 が一致することを再確認する。新たな製品コードは追加していない。
ドキュメントのみの保存 commit はこの境界の子とする。
Git hook の lefthook は利用不能だったため、hook 合格とは記録しない。
CI は push 後の実結果を別記し、pending / absent を success と扱わない。

CodeGraph 1.6.0 の選択 graph と public SDK extraction は prior receipt の範囲に限定する。
今回の WIP 用 `index .` は既存の親 project を選び、9,247 files / 200,095 nodes /
633,942 edges を root index に記録した。意図した 15-file projection ではないため除外する。
status は complete / pending modified 1 を示したが、これを最終採用ソースの全 owner 証明、
1 MiB 超の gateway/run.py の resolved index 証明とは扱わない。DB や証拠は削除していない。

再起動は現在のモデル選択と設定を保持し、Desktop、Go watchdog、backend、llama、
embedding、Gateway、harness、A2A を分けて確認する。
開始時点の embedding は disabled、8082 は未待受だったため、再起動だけを理由に有効化しない。
通常版の URL 登録許可は native test isolation や物理 sleep 試験の合格を意味しない。

## 再開入口

採用境界、WIP manifest、companion receipt、最新運用ログの順に確認し、
最初は上記 API strict cleanup か Gateway shared-input の一方だけを選択する。
main へ反映した保存点の履歴を維持し、上流を再取得する前に固定 SHA を確認する。
利用者 PC の休止・再起動、未承認の自動化やリリース、証拠削除を再開の前提にしない。
