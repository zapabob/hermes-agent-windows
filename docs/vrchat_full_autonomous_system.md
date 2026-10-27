# 完全自律 VRChat AI アバター統合システム

## 構成要素
- **TTS**: Irodori 実音声 → キャッシュ → 再生 → 削除
- **OSC**: python-osc で口パク・チャットボックス同期
- **優先度キュー**: 発話優先度管理
- **アバター設定**: config.json 動的読み込み
- **フレームキャプチャ**: ffmpeg 1fps + ハッシュログ
- **資格証明**: MD5 ハッシュログ + Obsidian 同期
- **X 投稿**: cron 自動化 + リトライ
- **Obsidian**: ハッシュログ自動追記 + 双方向同期
- **Ebbinghaus**: 記憶統合
- **ハートビート**: テキストボックス自動送信
- **アバター自律操作**: OSC 経由

## Cron ジョブ
- vrchat-unified-sync: 30分ごと統合処理
- obsidian-hash-append: 1時間ごと Obsidian 追記
- vrchat-x-auto-post: 30分ごと X 投稿

## 次の拡張
- アバター自律操作の具体実装
- ハートビートのテキストボックス送信実装
- X 投稿失敗時の指数バックオフリトライ
