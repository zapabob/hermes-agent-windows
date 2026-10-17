# 保存点の公開・運用記録 — 2026-10-17

製品採用境界は `23effd145acf06693cf786e6212e76d0a9c8e893`。棚卸・残作業・実装ログを含む `8fd4a69ff88fbf691ec047e5fa4f752259c32d99` を main に fast-forward し origin/main へ push した。本記録の commit は文書のみ。製品 version は既存の 0.21.5 を維持し、全計画完了・安定版 release・全 CI 成功は宣言していない。

## 保全

作業用 checkout の `tmp/selective-20261017/checkpoint-wip-20261017/` に未採用 WIP 7 ファイル、完全コピー、SHA-256、tracked patch、未追跡の元ファイルを保存した。primary の以前からのローカル11ファイルは `tmp/checkpoint-preserved-20261017/` にコピーと元ファイルを残し、hash を照合した。私的診断ファイルの内容は公開していない。ignored 証拠・旧環境・ログも保持し、reset / clean / stash は使っていない。

初回 fast-forward は既存 index.lock で失敗した。Git process 不在、空ファイル、時刻不変を確認後、lock 自体も保存先へ移動して再実行した。削除は行っていない。fast-forward / push 成功時点で main と作業用 checkout は Git clean。

## Desktop の生成と配置

固定済み依存のある作業用 checkout で Node24.19.0 により build。依存 install / lock 更新は行っていない。旧 dist を保存し、prebuild clean を省いて build script を実行、assert-dist-built を明示的に確認した。Vite、main/preload bundle、native addon stage、assert は成功。Electron41.10.7 の package を新しい固有 output に生成した。旧 win-unpacked 全体を保存し、新 package の461ファイルをSHA-256で照合して primary に配置した。

install-stamp の commit は8fd4a69ff88、dirty=false。build branch 名は作業 branch だが同SHAの main と同一ソース。成果物と旧 package はローカル保管。署名・版上げ・release 操作は行っていない。

## 再起動後の確認

| 対象 | 結果 |
| --- | --- |
| Desktop / backend | 旧PID20244と専用backendを識別して停止。新Desktop PID33992、primary通常版exe、title Hermes、HWND非ゼロ、Responding=True。backend PID35256、port60758、`/api/health` HTTP200 |
| Go watchdog | operator launcherを昇格しStop/Start。旧1748から新38720。9920 NORMAL、desktop up、backend up、backendHealth healthy、consecutiveBackendFails0、recoveryEvents0 |
| llama | 旧3980を同一実体・creation timeで識別して停止。既存Ensure-HermesGeneration.ps1で新33376。Hikari-LoRA-fixed-scale-PQ2_0.gguf、context131072、1slot。最終`/completion`で1token実生成を確認。モデル品質・長時間試験の証明ではない |
| Gateway / harness / dashboard | default Gatewayの既存Windows restartを使用。gateway_state PID33996、code_sha=8fd4a69ff88、version0.21.5。harness旧4620から新16932、18794 health ok。dashboard旧3464から新2668、9120 HTTP200 |
| embedding / 独立サービス | embeddingはdisabled・8082無待受を維持。A2A/WebUI/memory graph/tunnelsの既存processは維持し、再起動・全体合格は主張しない。8646の旧独立listener PID24816を新Gatewayの証明に流用しない |

人間は通常版Desktopの起動時URL登録を追加許可した。再起動後のHKCU hermes URL commandはprimary通常版Hermes.exeと`%1`を指す。native E2E全体の再開・合格ではない。

## 失敗と復旧

llama初回は呼出元のLLAMA_ARG_CACHE_TYPE_V=turbo3混入で失敗した。引数の保持だけでは環境を保持できていなかった。不要なLLAMA_ARG/TURBOQUANTを除く既存専用launcherで現在のGGUF/q4_0/ngram-simple/contextを保持して復旧した。既存generation stdout/stderrは事前コピー・hash照合済み。最初の推論probeは他の処理中に60秒でtimeout、最終1token probeは応答した。

harness初回はprimary Pythonのpythonosc不足で失敗。依存追加をせず、既存scripts/.venvのimportを確認して復旧した。Desktop配置の初回censusは終了直後のprocessと競合し拒否した。package移動前だったため旧packageは保持され、fresh censusで不在確認後に再実行した。backend初回`/health`は404、正しい`/api/health`で200。失敗証拠も保存している。

## Cloud CI と次回

8fd4a69ff88のDocker/Nixはsuccess。[Windows Workstation Tier-1 CI](https://github.com/zapabob/hermes-agent-windows/actions/runs/39026733035)はfailure。carry metricsがstale、Desktop fixture単体試験が未ビルドのdist/electron-main.mjsを要求する。native Python/watchdog Go/upstream API/security-lockfiles/regression/frozen pilotは同workflow内でsuccess。一般CI、Windows downstream release、auto-fixは記録時点で進行中。CI all-green・安定版認定はしていない。

次回はcarry metrics契約と差分の確認、fixture単体試験のdist依存修正を行う。CIのために本番Electronを起動しない。その後、CHECKPOINT_20261017.mdのGateway shared-input、approval/clarify、API process ownership、full public journey、Security/MCP、履歴母集団へ進む。8h実モデルsoakと実sleep/resume3回はNOT_RUN。

運用証拠は作業用checkoutの `tmp/selective-20261017/checkpoint-runtime-20261017/runtime-final.json`。build/package/deploy hash、所有者確認、各失敗ログも同directoryに保持する。今回は継続実装を区切り、未完了を完了へ変更しない。
