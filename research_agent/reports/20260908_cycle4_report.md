# リサーチエージェント サイクル4 レポート (2026-09-08)

## 今回やったこと

1. **HUMAN_APPROVAL**: サイクル3の振り返りで予告されていた通り、
   `GENERATE_HYPOTHESES` で追加した新仮説 `h-cross-utterance-flicker`
   （$0の再解析のみ、既存クリップ利用）に対して
   `check-budget 0.0` → `AUTO_APPROVE` を確認し、`approval: auto_approved`
   / `status: queued` に設定しました。バックログは5件（上限6件以内）。

2. **環境の再確認**: `DEEPGRAM_API_KEY` / `GOOGLE_API_KEY` はともに設定済み、
   REST疎通も両方200でした（`api.deepgram.com/v1/projects`,
   `generativelanguage.googleapis.com`）。ただし `ffmpeg` は今回のセッション
   でも未インストールで、今回は意図的に `apt-get install` を試みませんでした
   ——`h-cross-utterance-flicker` は既存の実験JSONを再解析するだけの
   処理で、音声処理（ffmpeg）もライブAPI呼び出しも一切不要なため、
   環境ブロッカーの有無に関わらず実行できる仮説だったからです。
   （Deepgram Listen WebSocketの403が今回も残っているかどうかは、
   本サイクルでは未確認のままです — 次回ライブ実験を選ぶ際に再確認が必要）

3. **`h-cross-utterance-flicker` を実装・実行（$0、新規API呼び出しなし）**:
   `flicker_metrics.py` に `group_translation_by_utterance()` を追加しました。
   既存の `group_translation()` はバッチ単位（`(asr_start_time, asr_end_time)`）
   でしかグルーピングしておらず、サイクル3で見つかった通り「発話が複数
   バッチにまたがった場合の書き換え」を測れていませんでした。新関数は
   `is_utterance_end` フラグを使って発話単位（複数バッチにまたがる区間）を
   逐次的に再構成し（イベントスキーマに真の `utterance_id` は存在しない
   ため、あくまで発話境界のヒューリスティックです)、各バッチの最終テキスト
   の並びに対して既存のNE（正規化消去率）計算を再利用しました。
   47件すべての実験JSONに対して再実行し、`experiments/flicker_metrics.csv`
   を更新しています。

## 結果（予想以上に大きな発見）

- 全4471発話区間のうち、**6.2%（275件）が2回以上のバッチにまたがって**
  いました（＝発話がある程度長く、ストリーミング翻訳が確定するまでに
  複数回の「ゼロからの再翻訳」が発生するケース）。
- その275件について、バッチをまたいだ翻訳NE（文字レベル、
  `h-flicker-metric` と同じ計算式）の**平均は約1.47**（中央値約1.28、
  範囲0.68〜3.94）でした。これに対し、`h-flicker-metric`（サイクル1）
  が測定した「1バッチ内」の翻訳NEは約0.0001とほぼゼロでした。
- NEが1.0を超えるということは、後続バッチの再翻訳による書き換え量の
  累積が、最終的な訳文の長さそのものを上回っている、つまり
  **画面に一度表示された日本語字幕が、ほぼ丸ごと別の文章に置き換わって
  いる**ことを意味します。実際に `experiments/20260903_smoketest.json`
  の生イベントを目視確認したところ、同じ発話の1バッチ目が
  「そして、私たちの主な仕事は、どのように読み解くかを理解することに
  あり、」、2バッチ目が「その根底にある行列をどう読み解くかについて
  ですが、ここでは詳しく触れずに、」——共通の接頭辞すらなく、
  文字通り別の翻訳文になっていました。
- **結論**: `h-flicker-metric` の「翻訳レベルのちらつきはほぼ無い」
  という結論は、1バッチで完結する約94%の発話については正しいですが、
  複数バッチにまたがる残り約6%については誤りで、実際には視聴者に見える
  形での大規模な字幕書き換えが起きています。これは `h-masking-holdback`
  / `h-localagreement-asr-commit`（いずれもDeepgramインフラ待ちで
  ブロック中）が本来狙っている問題そのものであり、両仮説の優先度を
  上げる根拠になります。また、Deepgramの疎通を待たずにできる安価な
  緩和策（例: 継続バッチの `full_target_text` が安定するまで画面表示の
  更新を保留する）も次サイクルで検討する価値があります。
- 留意点: 発話区間の境界は `is_utterance_end` を使った逐次ヒューリスティック
  であり、真の発話ID結合ではありません。また「何秒くらい話し続けると
  2バッチ目に突入するのか」という時間軸での分析はまだ行っていません
  （次サイクル候補）。

## バックログの状態（5件、上限6件以内）

| ID | ステータス | 備考 |
| --- | --- | --- |
| h-flicker-metric | tested | サイクル1で完了 |
| h-cross-utterance-flicker | **tested（今回完了）** | バッチ横断NE ~1.47、大きな発見 |
| h-masking-holdback | queued（ブロック中） | Deepgram Listen WebSocketの403、優先度が上がった |
| h-localagreement-asr-commit | queued（ブロック中・同じ原因） | 未実装のまま |
| h-gemini-only-masking-replay | queued（実装保留） | 今回の新指標を使って設計し直す必要あり |

## 今回変更したファイル

- `src/real_time_translation/experiments/flicker_metrics.py`:
  `group_translation_by_utterance()` を追加。`FlickerReport` / CSV出力に
  `num_translation_utterance_spans` / `translation_ne_char_cross_batch_mean`
  列を追加。
- `experiments/flicker_metrics.csv`: 上記を含めて47件を再解析した結果で
  更新。
- `research_agent/state/hypotheses.json`: `h-cross-utterance-flicker` を
  `auto_approved` → `testing` → `tested` に進め、詳細な `result_summary`
  を記録。
- `research_agent/state/budget.json`: `log-cost 0.0` を記録（新規API呼び出し
  なし）。

## 人間（rm-2278）へのお願い

- 今回の発見（バッチ横断の翻訳ちらつきが大きい）を踏まえると、
  `h-masking-holdback` / `h-localagreement-asr-commit` の優先度は
  上がりました。前回セッションから持ち越しのお願いですが、
  `api.deepgram.com` への**Listen WebSocketアップグレードを含めた**恒久的な
  プロキシ許可を設定いただけると、これらのライブ実験を実際に回せます
  （本サイクルでは未実装のffmpegも含め、環境状態は未再確認です）。
- 上記が難しい場合でも、`h-gemini-only-masking-replay`
  （Deepgramを使わない代替検証）は、今回追加したバッチ横断NE指標を
  使って設計し直せば、次サイクルで進められる見込みです。

## 次のサイクルでやること

- `GENERATE_HYPOTHESES`: バッチ横断が起きるまでの時間（秒数）と発話長の
  関係を見る追加分析（$0）、または `h-masking-holdback` /
  `h-localagreement-asr-commit` のバッチ横断NEでの再評価を仮説に組み込む
  ことを検討する。
- 環境（Deepgram Listen WebSocket, ffmpeg）を再確認し、通っていれば
  ブロック中の3仮説のいずれかを実クリップで実行する。
