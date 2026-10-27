# VRChat OSC 連携・発話キュー優先度設計

## 1. OSC アドレス設計
| 機能 | OSC Path | 値 |
|------|----------|----|
| Chatbox 表示 | /chatbox/input | string |
| Chatbox 可視 | /chatbox/visible | bool |
| 口パク | /avatar/parameters/VRC_Speaking | bool |
| 瞬き | /avatar/parameters/VRC_Blink | float 0-1 |
| 首振り | /avatar/parameters/VRC_HeadTilt | float |
| 手振り | /avatar/parameters/VRC_HandWave | bool |

## 2. 優先度クラス
- 0 system_alert : 権限喪失・障害復旧
- 1 user_direct : ボブにゃん直DM
- 2 vrchat_chat : 通常チャット
- 3 avatar_emote : 表情・モーション
- 5 ambient : BGMコメント等
- 9 log : デバッグ

## 3. キューアルゴリズム
1. 入力は `SpeechQueue.enqueue(text, priority, target)`
2. heapq で優先度・タイムスタンプでソート
3. 同一発話 30秒内重複はスキップ
4. TTS 生成 → OSC 同時送信 → 再生 → 削除

## 4. Irodori 連携
- `speak(text, target=vrchat_cable)` で発話イベントを取得
- イベント `started_at, duration, amplitude_envelope`
- envelope を `/avatar/parameters/VRC_Speaking` にマッピング

## 5. 自己修復
- OSC 応答なし 3回連続 → VRChat再接続試行
- キュー滞留 10件超 → 低優先度を破棄
- キャッシュ残留検出 → クリーンアップデーモン起動

## 6. 実装ステップ
1. `vrchat_osc_tts_queue.py` を常駐化
2. `tts_autonomous_avatar.py` から queue に委譲
3. Cron で 1分毎ヘルスチェック
4. ログは `tts_avatar_state.json` だけ保持

これで完全自律AIアバターの発話制御が安定する。
