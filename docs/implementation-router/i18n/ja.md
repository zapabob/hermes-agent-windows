# Hermesの工程別実装

計画・実装・ホスト側検証を順番に進める機能です。MoAやプロバイダーのフォールバックではありません。
`implementation_router`プラグインを有効にし、既存の補助モデルピッカーで `engineering_planner`・`engineering_worker`・`engineering_reviewer`を選択します。既存プロバイダーが対応する任意のモデルを使用でき、利用不可なら停止します。
プラグイン設定で、秘密情報を含まない `source_paths`、変更禁止の受入試験 `protected_paths`、事前準備したイメージのダイジェスト、固定した検証コマンド `checks`を指定します。実行例は `/engineer {"workspace":"sample","task":"必要な変更をTDDで実装する"}` です。
認証情報と推論クライアントは親のHermesに残ります。子孫プロセスは、ホストの認証ファイル・環境変数・ネットワークを引き継がない新しいDocker環境で動きます。WindowsでもLinux Dockerエンジンが必要です。通常のローカルシェルには切り替えません。
成功時は検証済みの作業コピーを返し、元のチェックアウトを直接変更したりPRを自動マージしたりしません。合格判定には最終SHAのCIと実環境試験を使い、模擬推論の試験を実アカウントの利用確認とは扱いません。
空の環境変数だけではOS隔離になりません。ホスト、Dockerデーモン、イメージ、信頼済みプラグインは信頼境界の内側です。ソースに秘密が埋め込まれていないことを確認してください。残存するleaseは調査後に操作者が復旧し、完了不明の処理を自動再実行しません。

<!-- routing-not-moa -->
<!-- credentials-host-only -->
<!-- native-adapter-requirements -->
<!-- not-os-sandbox -->

[Agent protocol](../AGENT_PROTOCOL.md)

工程ごとの推論量は役割の設定として固定し、Medium／Medium／Highが親の送信リクエストへ届くことを検証します。画面表示だけで有効とは判定しません。停止したrunには秘密情報を含まない固定の診断コードが付く場合があります。leaseとjournalを保持し、診断を根拠に自動再実行しないでください。
