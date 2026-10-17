# Codex 実装保存ログ — 2026-10-17

人間の区切り指示を受け、採用済み製品境界 `23effd145acf06693cf786e6212e76d0a9c8e893`
を main へ保存する。全計画完了や stable release の宣言ではない。

固定入力・実装の棚卸・残作業・再開手順は
`docs/windows/v0222-release-baseline-20261015/CHECKPOINT_20261017.md` に保存した。
詳細試験記録は同じ directory の `SELECTIVE_20261017.json`、
以前のローカル実装記録は `_docs/2026-10-17_v0222_selective_implementation_Codex.md` に残る。

採用済み 27 commits は保護していた downstream `abad98beee2b74a135ce7e0e9310910c756514b4`
の子孫。origin/main を取得し、同じ downstream SHA のままであることを確認した。
main への統合は fast-forward を使い、force push はしない。

現在の API process ownership 製品 2 ファイル・専用/既存テスト 4 ファイルと未採用 native
テスト 1 ファイルを、ignored task evidence 内に完全コピーと hash、patch 付きで保全した。
コピーを照合してから tracked ファイルを採用済み bytes へ戻し、untracked 元ファイルを
同じ保存 directory へ移動した。削除・reset・clean・stash は行っていない。

WIP の停止結果検証と再レビューは未完了。Windows taskkill / env / PTY / systemd の失敗を
完了扱いしないこと、所有者変更後の raw fallback を防ぐことを残作業として記録した。
新しい実 handoff / kill-outcome テストは未実行。未適用の6 fault helper も保存した。
対象が通った途中の結果だけで WIP を main へ採用しない。

Gateway shared input、approval/clarify 所有権、全 public journey、Security Center/MCP 実効果、
full history、vendor runtime 独立性は未完了。8h 実モデル soak と実 sleep/resume 3 回は NOT_RUN。
旧 native hold は通常版再起動と URL 登録の範囲だけ人間が明示的に解除した。

main / origin の最終 SHA、ファイル保全の結果、再起動・health の実結果、cloud CI 状態は
`CHECKPOINT_RUNTIME_20261017.md` と運用 receipt へ追記する。

運用追記: 保存点8fd4a69ff88をmain/originへ反映。新Desktopをbuild/packageし、旧package保存、461ファイル照合後に配置した。Desktop/backend/Go/Hikari/default Gateway/harness/dashboardを再起動し、個別healthとHikari 1token実生成を確認。embedding disabledと独立A2A/WebUI/memory graph/tunnelsは維持した。通常版URL登録は追加許可範囲で実行した。

Windows Tier-1 CIはcarry metrics staleとfixtureのdist依存でfailure。全CI成功・stable releaseは未認定。途中の失敗・復旧はCHECKPOINT_RUNTIME_20261017.mdに記録。WIP・元ファイル・旧package・旧ログ・証拠は保存済み。最後の文書commit後に両checkoutのGit cleanとremote equalityを確認する。
