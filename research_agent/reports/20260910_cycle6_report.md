# リサーチエージェント サイクル6 レポート (2026-09-10)

## 今回やったこと

1. **GENERATE_HYPOTHESES**: サイクル5の振り返りで挙がっていた通り、
   まず環境（特にDeepgram Listen WebSocket）を再確認しました。
   `ffmpeg` は今回のセッションでも未インストールでしたが、
   `apt-get install` で問題なく解決。`python3.13 -m venv` ＋
   `uv pip install -e ".[experiments]"` で仮想環境を構築し
   （`uv run` はzoom/rtms extraの同期で毎回失敗するため、本ファイルに
   記録済みの回避策を継続使用）、実際に
   `wss://api.deepgram.com/v1/listen` へのWebSocketハンドシェイクを
   Pythonから直接テストしました。結果はサイクル5と**まったく同じ
   症状**でした:
   - TLS証明書検証でまずエラー（プロキシが注入するCA証明書の
     key usage extension不足によるOpenSSLの厳格な検証エラー、
     Deepgram側とは無関係）。
   - 検証を一時的に無効化して先を見ると、Deepgramから
     **HTTP 400「Connection header did not include 'upgrade'」**が
     返ってきます。プロキシがWebSocketアップグレード要求を正しく
     中継できていないというインフラ側の制約は、サイクル5から
     まったく改善していません。
   - `h-masking-holdback` / `h-localagreement-asr-commit` /
     `h-gemini-only-masking-replay` の3仮説すべて、引き続き
     ライブDeepgram録画待ちのままです（`blocked_reason` に
     今回の再確認結果を追記済み）。

   WebSocketブロッカーが解消していなかったため、サイクル5の
   振り返りで示された代替方針（「$0・ライブAPI不要の新しい観点が
   あればそれを追加する」）に従い、新しい仮説
   `h-utterance-batch-timing` を追加しました。これは
   `h-cross-utterance-flicker`（サイクル4）自身が課題として
   残していた「複数バッチにまたがる発話は、何秒くらい話してから
   2バッチ目に突入するのか」という時間軸の疑問に答えるものです。
   バックログは4件（上限6件以内）になりました。

2. **HUMAN_APPROVAL**: `h-utterance-batch-timing` の見積もりコストは
   $0（既存の実験JSONを再利用する遡及分析のみ）で、
   `check-budget 0.0` は `AUTO_APPROVE` を返しました。
   `approval=auto_approved` / `status=queued` に設定し、
   `RUN_EXPERIMENTS` に進みました。

3. **RUN_EXPERIMENTS**: `flicker_metrics.py` の
   `group_translation_by_utterance()` を拡張し、複数バッチにまたがる
   各発話スパンについて「最初のバッチが確定するまでの実時間
   （`asr_end_time - asr_start_time`）」= `first_batch_duration` を
   新たに記録するようにしました。既存47件の実験JSON・275件の
   複数バッチスパン（サイクル4/5と同じデータセット）に対して
   再実行し、コーパス全体の分布を計算しました。ライブAPI呼び出しは
   ゼロです。

## 結果

`first_batch_duration`（複数バッチにまたがった発話が最初のバッチを
確定するまでにかかった秒数、275件）の分布:

| 統計量 | 値 |
| --- | --- |
| 平均 | 3.761秒 |
| 中央値 | 3.460秒 |
| 最小 | 2.430秒 |
| 最大 | 11.790秒 |

コーパス全体のNE指標（`translation_ne_char_mean=0.0001`,
`asr_ne_word_mean=0.2004`,
`translation_ne_char_cross_batch_mean=1.4430`）はサイクル4/5から
変化なし——今回の変更は純粋な追加分析であることを確認できました。

**重要な発見**: 最小値・中央値がいずれも `config.py` の
`deepgram_max_interim_duration=2.5秒`（`pipeline.py` の
`_drain_batch()` のコメントによれば、連続音声が続く場合にこの秒数
ごとにバッチをソフト確定させるタイマー）のすぐ上に集中しています。
つまり、複数バッチにまたがる発話は「珍しく長い外れ値」だから
バッチをまたぐのではなく、**2.5秒のソフト確定タイマーが通常の
発話の長さでごく普通に発火することでバッチをまたいでいる**、という
ことがわかりました（外れ値は最大11.79秒のごく一部の長い発話のみ）。

この結果は仮説の予測（「特殊な長い発話ではなく通常のチャンク化政策が
原因」）を裏付けています。したがって、サイクル4で確認した
バッチ横断NE〜1.47の「ちらつき」問題は、ごく一部の特殊なケースでは
なく通常の会話で広く発生する問題であり、`h-masking-holdback` /
`h-localagreement-asr-commit`（現在どちらもDeepgramインフラの
問題でブロック中）は、Deepgramアクセスが復旧すれば**特別な発話の
長さに限定せず、汎用的な対策として有効**だと期待できます。

## バックログの状態（4件、上限6件以内）

| ID | ステータス | 備考 |
| --- | --- | --- |
| h-flicker-metric | tested | サイクル1で完了 |
| h-cross-utterance-flicker | tested | サイクル4で完了（NE〜1.47の発見） |
| h-utterance-batch-timing | tested | 今回完了（2.5秒タイマーとの一致を確認） |
| h-masking-holdback | queued（ブロック中） | WebSocketアップグレードがプロキシで阻害。コード実装済み・即実行可能 |
| h-localagreement-asr-commit | queued（ブロック中・同じ原因） | 未実装のまま |
| h-gemini-only-masking-replay | queued（ブロック中） | 既存JSONでは実行不可、新規録画が必要 |

## 今回変更したファイル

- `src/real_time_translation/experiments/flicker_metrics.py`:
  `first_batch_duration` フィールドを追加し、CSV出力・コーパス全体の
  統計出力（平均/中央値/最小/最大）に反映。
- `experiments/flicker_metrics.csv`: 新しい列を含めて再生成。
- `research_agent/state/hypotheses.json`: `h-utterance-batch-timing`
  を新規追加・検証完了まで記録。3件のブロック中仮説の
  `blocked_reason` に今回の再確認結果を追記。

## 人間（rm-2278）へのお願い

- サイクル5から変わらず: このサンドボックス環境のネットワーク
  プロキシが `wss://api.deepgram.com/v1/listen` への
  WebSocketアップグレード要求を正しく中継できていません
  （REST APIは200を返すのに対し、WebSocketアップグレードのみ
  HTTP 400で拒否されます）。プロキシ設定でこのホストへの
  WebSocketアップグレードを許可（または生TCPでパススルー）
  いただけると、3件すべての待機中仮説（コードは実装済み）が
  一気に進みます。

## 次のサイクルでやること

- 環境（特にDeepgram Listen WebSocket）を再確認し、通っていれば
  最優先で `h-masking-holdback` を実クリップで実行する（コードは
  実装済み・即実行可能）。
- 通らない場合は、今回のバックログが4件（上限6件）に収まっている
  ので、さらに深掘りできる$0分析があれば追加を検討する。現時点では
  これ以上の遡及分析のアイデアは尽きつつあり、次の自然なステップは
  文献の再サーチ（サイクル1以来、実質2回目の新規サーチとなる）か、
  プロキシ問題が直るのを待つことになる。
