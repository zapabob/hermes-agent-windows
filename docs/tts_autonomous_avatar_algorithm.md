# 自律AIアバター TTS キャッシュ・発言アルゴリズム設計書

## 目的
VRChat上の完全自律AIアバターが TTS 発言を「一時キャッシュ→再生→即時削除」で実行し、ディスク残留ゼロ・連続運用可能な状態を維持する。

## 1. ディレクトリ構成
```
C:/Users/downl/.hermes/
  tts_cache/            # 一時書き出し先
  tts_avatar_state.json # 直近発言メタ
  scripts/
    tts_speak_cache.py  # 単発発話API
    tts_autonomous_avatar.py  # 常時ループ
    tts_cleanup_daemon.py # ゴミ掃除
```

## 2. ライフサイクル
1. **キュー受信**
   - 内部発話キュー or OSC `/chatbox` 入力
   - 重複抑制: 直前30秒以内の同一テキストはスキップ

2. **生成**
   - `text_to_speech` または `irodori_tts_synthesize` を使用
   - 出力先: `tts_cache/tts_<epoch>_<uuid>.wav`
   - 命名規則で衝突回避

3. **再生**
   - Windows: `Media.SoundPlayer.PlaySync()` または `ffplay -nodisp -autoexit`
   - VRChat OSC 同期: `/avatar/parameters` で口パクトリガー

4. **状態記録**
   - `tts_avatar_state.json` に text / path / timestamp / provider を書く
   - 次発話の重複判定に使用

5. **削除**
   - 再生完了後 2秒遅延で `unlink`
   - 例外時は `tts_cleanup_daemon` が 5分毎に古いファイルを削除

## 3. 自律アルゴリズム
```
loop forever:
  utterance = fetch_next()
  if empty -> sleep 1s, continue
  if same_as_last_30s -> skip
  path = generate_tts(utterance)
  play(path)
  update_state(utterance, path)
  schedule_delete(path, delay=2s)
  log_event()
```

## 4. 完全自動化要素
- **起動自動化**: `hermes cron` で `tts_autonomous_avatar.py` を 毎分起動 or常駐化
- **自己修復**: `tts_cache` が 500MB 超えたら古いファイル一括削除
- **ヘルスチェック**: 10分間発話なし → ダミーハートビート発話
- **OSC連携**: VRChat OSCブリッジ経由で口パク/目線同期
- **ログ最小化**: 発話ログは `last N=100` だけ保持、元音声は残さない

## 5. セキュリティ・プライバシー
- キャッシュフォルダはアプリ専用、他プロセスから参照不可を推奨
- 発話内容はメモリ上のみ保持、ディスクにテキスト落とさない
- 削除は `os.unlink` 後 `shutil.disk_usage` で空き確認

## 6. 実装案
- `tts_speak_cache.py speak(text)` で外部から呼び出し可能
- `tts_autonomous_avatar.py` を常駐デーモン化
- Cron: `*/5 * * * *` で `tts_cleanup_daemon.py` 実行
- VRChat連携は `python-osc` で `/chatbox/input` と `/avatar/parameters`

## 7. 検証項目
- [ ] 生成→再生→削除までの時間 < 3秒
- [ ] 連続100発話でキャッシュ残0
- [ ] プロセス停止時の残骸クリーンアップ
- [ ] VRChat OSC同期で音ズレなし

これで自律AIアバターは完全自動で発話し続けられる。
