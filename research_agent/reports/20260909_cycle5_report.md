# リサーチエージェント サイクル5 レポート (2026-09-09)

## 今回やったこと

1. **SEARCH_PAPERS〜READ_PAPERS**: サイクル4の振り返り通り、
   「複数バッチにまたがる再翻訳の安定化」という具体的な観点でWebSearchを
   実施し、新たに4本の論文を発見・抽出・読了しました。
   - `chen2024-revision-controllable-decoding`（Microsoft, ICASSP 2024）:
     ビームサーチの枝刈り自体に「書き換え許容ウィンドウ」を組み込み、
     ちらつきゼロ〜無制限まで連続的に調整できる手法。デコーダ内部の
     ビームサーチにアクセスできないAPIオンリーの本リポジトリでは実装
     不可ですが、「ちらつきをほぼゼロにしても品質低下はわずか」という
     知見は `h-masking-holdback` のマスキング方式の妥当性を裏付けます。
   - `zoom2025-self-speculative-retranslation`（Zoom, arXiv:2509.21740）:
     「display-only masking」という用語を明示的に使っており、
     `h-gemini-only-masking-replay` の発想そのものを裏付ける文献的根拠
     になりました。
   - `cmu-nvidia2026-hierarchical-policy-simulst`（CMU+NVIDIA,
     arXiv:2604.21045, ACL 2026 Oral）: 英→日を含む評価で、マルチターン
     対話としての定式化＋強化学習後学習により継続再翻訳のドリフトを
     大きく改善（+7 COMET等）。学習時アクセスが必要でAPIオンリーの
     本リポジトリには適用できませんが、サイクル4で見つけたバッチ横断
     ドリフト（NE〜1.47）が2026年の最先端研究でも認識・対処されている
     問題であることの裏付けになりました。
   - `papi2026-doa-decoder-only-attention-policy`（FBK,
     arXiv:2605.31432）: AlignAtt系と同様、モデル内部のアテンション
     重みへのホワイトボックスアクセスが必要で、こちらも適用不可。
     `h-localagreement-asr-commit` をプレーンなLocalAgreement-2に
     留める判断が改めて妥当と確認できました。
   - いずれも「既存の3仮説（バックログ）に新しい仮説を追加する必要は
     ない」という結論になり、`GENERATE_HYPOTHESES` は空振り（no-op）
     としました——アイデアが足りないのではなく、既存の仮説を実際に
     実行することが課題だったためです。

2. **環境の再確認とDeepgramブロッカーの精密な原因特定**: `ffmpeg` は
   今回のセッションでも未インストールでしたが、`apt-get install` で
   問題なく解決しました。`python3.13 -m venv` ＋
   `uv pip install -e ".[experiments]"` で仮想環境を構築し
   （`uv run`はzoom/rtms extraの同期で毎回失敗するため、今回も
   本ファイルに記録済みの回避策を使用）、実際に
   `wss://api.deepgram.com/v1/listen` へのWebSocketハンドシェイクを
   Pythonから直接テストしました。その結果、サイクル3で見つかった
   「403エラー」よりもさらに具体的な原因が判明しました:
   - まずTLS証明書検証でエラー（プロキシが注入するCA証明書に
     OpenSSLの厳格な検証が引っかかる、Deepgram側とは無関係の問題）。
   - 検証を一時的に無効化してその先を見ると、Deepgramからは
     **HTTP 400「Connection header did not include 'upgrade'」**が
     返ってきました。つまり、このサンドボックスのネットワーク
     プロキシがHTTPレイヤーでWebSocketアップグレード要求を
     中継・改変してしまい、Deepgramがそれを正規のWebSocket接続と
     認識できていません。これはAPIキーや課金上限の問題ではなく、
     **プロキシがWebSocketアップグレードを正しく通していない**という
     インフラ側の制約です。

3. **`h-gemini-only-masking-replay`（Deepgram不要のはずの仮説）を
   実装しようとして、構造的なブロッカーを発見**: マスキング
   ホールドバックは「発話が複数バッチにまたがる継続バッチ」でしか
   効果を持ちません（1バッチで完結する発話では常にno-op）。しかし
   既存の実験JSON（`results.events`、`TimedEvent`）には継続バッチの
   **英語ソーステキスト**が一切記録されておらず、翻訳後の日本語テキスト
   しか残っていないことが判明しました。つまり「既存の実験JSONをリプレイ
   するだけで新規Deepgram呼び出し不要」というこの仮説の前提そのものが、
   現状のデータでは成立しません。
   - 今後の記録のために、`video_segment.py` の `TimedEvent` に
     `original_text` フィールドを追加し（3箇所のイベント生成部分すべてに
     反映）、`ruff check` と既存47件の実験JSON全件に対する
     `flicker_metrics.py` の再実行で問題ないことを確認しました
     （数値は変化なし: `asr_ne_word_mean=0.2004`,
     `translation_ne_char_mean=0.0001`,
     `translation_ne_char_cross_batch_mean=1.4430`、サイクル4の
     結果と一致）。
   - ただしこの修正は**今後の新規録画にのみ有効**で、既存47件の
     JSONを遡って直すことはできません。結果として
     `h-gemini-only-masking-replay` も実質的に「Deepgramをバイパス
     できる」仮説ではなくなり、他の2仮説と同じくプロキシのWebSocket
     問題が直るまで新規ライブ録画が必要、という結論になりました。

## 結果

- 3件の待機中仮説（`h-masking-holdback`, `h-localagreement-asr-commit`,
  `h-gemini-only-masking-replay`）はいずれも今回もライブ実験を実行
  できず、新規API呼び出しは0件・支出は$0でした。何も捏造していません。
- 一方で、「なぜ動かないのか」をこれまでで最も具体的に特定できた
  サイクルでもあります（プロキシのWebSocketアップグレード処理の問題）。
  また、`h-gemini-only-masking-replay` については設計上の思い込みの
  誤りに気づき、今後の記録形式を修正しました。

## バックログの状態（5件、上限6件以内、変化なし）

| ID | ステータス | 備考 |
| --- | --- | --- |
| h-flicker-metric | tested | サイクル1で完了 |
| h-cross-utterance-flicker | tested | サイクル4で完了（NE〜1.47の発見） |
| h-masking-holdback | queued（ブロック中） | WebSocketアップグレードがプロキシで阻害 |
| h-localagreement-asr-commit | queued（ブロック中・同じ原因） | 未実装のまま |
| h-gemini-only-masking-replay | queued（ブロック中に格上げ/格下げ） | 既存JSONでは実行不可と判明、新規録画が必要に |

## 今回変更したファイル

- `research_agent/state/papers.json`: 新規4論文の抽出・読了（status:
  extracted → read）。
- `research_agent/state/hypotheses.json`: 3件の `blocked_reason` に
  今回の精密な原因調査結果を追記。
- `src/real_time_translation/experiments/video_segment.py`:
  `TimedEvent.original_text` フィールドを追加（今後の録画から
  マスキングホールドバック検証に必要なソーステキストを記録できるように）。

## 人間（rm-2278）へのお願い

- **今回最も具体的になったお願い**: このサンドボックス環境の
  ネットワークプロキシが `wss://api.deepgram.com/v1/listen` への
  WebSocketアップグレード要求（`Connection: Upgrade` ヘッダーを含む
  HTTPハンドシェイク）を正しく中継できていません。REST API
  （`/v1/projects` など）は問題なく200を返すので、プロキシ側で
  このホストへのWebSocketアップグレードだけが特別な扱いを受けている
  可能性があります。プロキシ設定でこのパスを許可（または生TCPで
  パススルー）いただけると、3件すべての待機中仮説が一気に進みます。
- それが難しい場合でも、影響は限定的です——今回の`TimedEvent`修正に
  より、次に何らかの理由でライブ録画が1回でも成功すれば、
  `h-gemini-only-masking-replay` を含めすべての仮説を検証できる
  データが揃います。

## 次のサイクルでやること

- 環境（特にDeepgram Listen WebSocket）を再確認し、通っていれば
  最優先で `h-masking-holdback` を実クリップで実行する（コードは
  実装済み・即実行可能）。
- 通らない場合は `GENERATE_HYPOTHESES` で、ライブAPIを使わない
  新しい$0仮説（例: バッチ横断ドリフトが発生するまでの発話継続時間の
  分布分析など、サイクル4の振り返りで触れた時間軸分析）を検討する。
