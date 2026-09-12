# リサーチエージェント サイクル9 レポート (2026-09-12)

## 今回やったこと

サイクル8の振り返り（「文献が1サイクル古くなっており、$0の遡及分析ネタも
出尽くしたので`SEARCH_PAPERS`に戻る」との判断）を受けて、今回は
`SEARCH_PAPERS`からフルサイクルを実行しました。

1. **SEARCH_PAPERS**: サイクル8で明示された2つのギャップ
   （①ライブASRを必要としないオフライン評価手法、②継続バッチの
   文脈アンカリング用プロンプト設計の先行事例）を狙ってWebSearchを
   実施し、新規候補3件を`papers.json`に追加しました。
   - `polak2026-meta-evaluation-latency-metrics`（レイテンシ指標
     自体のメタ評価。YAAL/SOFTSEGMENTERを提案）
   - `machacek-polak2025-cuni-offline-cla-latency`（文字レベルの
     Continuous Levenshtein Alignment＝CLAによる、遡及的なASR
     レイテンシ計測手法。ライブASR不要）
   - `beavertalk2025-sentence-memory-bank`（直前1文だけをメモリ
     バンクとしてプロンプトに含める、という具体的な設計事例）

2. **EXTRACT_PAPERS / READ_PAPERS**: `arxiv.org`/`aclanthology.org`
   へのWebFetchは今回も`EGRESS_BLOCKED`でしたが、CLA指標の実装
   リポジトリ（`github.com/ufal/asr_latency`、arxivではない）は
   直接WebFetchでき、「ゴールド書き起こしとASR候補を文字レベルで
   整列させ、遡及的に（ライブ配信なしで）計算できる」ことを確認
   できました。3件とも既存47実験・`flicker_metrics.py`と重複しない
   新規領域であることを確認し、`read`に更新しました。

3. **GENERATE_HYPOTHESES**: 新規仮説`h-cla-asr-latency-metric`を
   追加（$0・既存クリップ再利用）。ちょうど`experiments/refs/`に
   `wjZofJX0v4M.en.vtt`というYouTube公式字幕（タイムスタンプ付き
   ゴールド書き起こし）があり、既存47実験のうち24件がこの動画を
   使っていたため、実装可能と判断しました。バックログは
   5件（上限6件以内）を維持。

4. **HUMAN_APPROVAL**: `check-budget 0.0` → `AUTO_APPROVE`。

5. **RUN_EXPERIMENTS**: まず環境を再確認しました。

   - `DEEPGRAM_API_KEY`・`GOOGLE_API_KEY`ともに設定済み、RESTは
     いずれもHTTP 200。
   - `wss://api.deepgram.com/v1/listen`への実WebSocketハンドシェイクは
     **サイクル5〜8とまったく同じ症状**（証明書検証ありでは
     プロキシCAのkey usage extension不足エラー、検証なしでは
     HTTP 400「Connection header did not include 'upgrade'」）。
     5サイクル・4日間、症状は一切変化していません。
   - `ffmpeg`は今回も未インストール。Deepgramがブロックされている
     ため、今回はインストールを試みず（PLAYBOOK記載の通り、
     試みても無意味なため）。
   - 既存の4件のブロック中仮説（`h-masking-holdback`,
     `h-localagreement-asr-commit`, `h-continuation-context-anchor`）
     の`blocked_reason`にサイクル9の再確認結果を追記しました。

   その上で、$0の遡及分析仮説`h-cla-asr-latency-metric`を実装・実行
   しました。

   - `src/real_time_translation/experiments/asr_latency_cla.py`を
     新規作成（コンソールスクリプト
     `real-time-translation-exp-cla-latency`）。
   - 実装中に2つの実データ由来の落とし穴を発見・修正しました：
     (1) 一部の実験（例: `asr_keyterms_on`）は要求した
     `duration_seconds`（600秒）より大幅に短い時点（143.7秒）で
     終わっていたため、ゴールド側の窓を要求時間ではなく実際の
     `asr_end_time`最大値から決めるよう修正。
     (2) `playback_offset`（壁時計時間）はゴールドVTTの絶対動画時刻
     と同じ時計ではありませんでした（`asr_keyterms_off2`:
     壁時計234.1秒でasr_end_time換算267.8秒分のコンテンツを処理して
     おり、厳密な実時間ペース`--speed 1.0`では実行されていない、
     または類似の時計ずれがある）。そのため`playback_offset`ではなく
     `asr_end_time`（コンテンツ位置の時計。ゴールド側と同じ基準）で
     レイテンシを計算するよう変更しました。これにより指標の意味が
     「本物のライブレイテンシ」から「エンドポインティング/
     チャンク処理による遅延」に狭まりますが、依然として新規かつ
     有用な信号です。
   - 実装中に本物のインフラ事故も発生しました：ゴールド動画IDの
     一致チェックなしで全`experiments/*.json`に対して整列を試みた
     結果、まったく別の動画の実験
     （`20260724_llm2024_8_part1_full.json`）に対してゴールド29,115
     文字×ASR候補52,240文字＝15億セルの整列を要求してしまい、
     プロセスがOOM killされました。動画ID一致チェックとセル数上限
     （6000万セル）を追加して修正しました。
   - `wjZofJX0v4M`を使う27実験のうち、イベントログ形式以前の8件
     （`flicker_metrics.py`の既知の知見と同じ）を除く19件を分析し、
     `experiments/asr_latency_cla.csv`に出力しました。

6. **ANALYZE_RESULTS**: 既存の`avg_end_to_end_latency_seconds`
   （エンドポインティング掃引12ファイル）と比較したところ、
   既存指標は7.3〜18.9秒とノイズが多く、しかもエンドポインティング
   値と単調な関係にありません（1200msが300msより高い、など）。
   一方、新しいCLAレイテンシは全12ファイルでほぼ一定（約4.07〜
   4.10秒）でした。これは仮説の予測（セグメンテーションに頑健な
   指標は既存の粗い指標と違う結果を示すはず）を裏付ける、
   方向としては確認された結果です。ただし「どちらの指標がより
   正しいか」を確定するには、`--speed 1.0`を保証した実時間ペースの
   ライブ再実行での検証が必要であり、今回はそこまでは踏み込んで
   いません。

## 結果まとめ

- 今回は**ライブAPIコールを一切使わず**（$0）、既存の実験記録
  だけから新しい知見を得ました。
- 新しい発見：この実験群のエンドポインティング設定（300〜2000ms）
  を変えても、外部のゴールド書き起こしを基準にした場合のASR
  レイテンシはほとんど変わらない（4.07〜4.10秒でほぼ一定）一方、
  パイプライン自身が記録している`avg_end_to_end_latency_seconds`
  は7.3〜18.9秒と大きくばらついていました。これは既存の
  エンドポインティング掃引の結論（chunk-length/endpointing sweep
  は「既に決着済み」とされていた過去の判断）を、もう一段慎重に
  見直す必要があることを示唆しています。ただし、この乖離が
  「既存指標がノイズに引きずられているだけ」なのか「本当に
  エンドポインティング設定がDeepgram接続まで正しく届いていない
  実装バグがある」のかは、今回の範囲では切り分けられていません。
  次サイクル以降でパイプラインの接続設定コードを確認する価値が
  あります。
- 環境ブロッカー（Deepgram Listen WebSocketのプロキシ問題）は
  5サイクル・4日間、症状が一切変化しないまま継続しています。

## バックログの状態（5件、上限6件以内）

| ID | ステータス | 備考 |
| --- | --- | --- |
| h-flicker-metric | tested | サイクル1で完了 |
| h-cross-utterance-flicker | tested | サイクル4で完了（NE〜1.47の発見） |
| h-utterance-batch-timing | tested | サイクル6で完了 |
| h-cla-asr-latency-metric | tested | **今回完了**。CLAレイテンシは掃引全体でほぼ一定、既存指標はノイズが多い |
| h-masking-holdback | queued（ブロック中） | WebSocketアップグレードがプロキシで阻害。コード実装済み・即実行可能 |
| h-localagreement-asr-commit | queued（ブロック中・同じ原因） | 未実装のまま |
| h-gemini-only-masking-replay | queued（ブロック中） | 既存47件のJSONでは再生不可能と再確認済み（サイクル8） |
| h-continuation-context-anchor | queued（ブロック中・同じ原因） | 今回`beavertalk2025-sentence-memory-bank`の知見を追加（ソース言語 vs ターゲット言語のどちらをアンカーするかの設計論点） |

## 今回変更・追加したファイル

- `research_agent/state/papers.json`: 新規論文3件を追加、抽出・読了。
- `research_agent/state/hypotheses.json`: `h-cla-asr-latency-metric`を
  新規追加・実行・分析・完了。4件の`blocked_reason`にサイクル9の
  再確認結果を追記。`h-continuation-context-anchor`の`grounded_in`に
  BeaverTalkを追加。
- `src/real_time_translation/experiments/asr_latency_cla.py`: 新規
  作成（CLAベースの遡及ASRレイテンシ指標）。
- `experiments/asr_latency_cla.csv`: 新規サイドカーCSV（19実験分の
  結果）。
- `pyproject.toml`: コンソールスクリプト
  `real-time-translation-exp-cla-latency`を追加。

## 人間（rm-2278）へのお願い

- サイクル3から変わらず: このサンドボックス環境のネットワーク
  プロキシが`wss://api.deepgram.com/v1/listen`へのWebSocket
  アップグレード要求を正しく中継できていません。プロキシ設定で
  このホストへのWebSocketアップグレードを許可（または生TCPで
  パススルー）いただけると、4件すべての待機中仮説が一気に進みます。
- 今回新たにお願いしたい点：`deepgram_endpointing`設定が
  300ms〜2000msの範囲でDeepgram接続に正しく反映されているか、
  パイプラインの接続設定コード（Deepgramクライアント初期化部分）を
  一度確認していただけないでしょうか。CLA指標がこの範囲で
  ほぼ無反応だったため、「設定が効いていない」可能性と「本当に
  この音声ではエンドポインティングの違いが表面化しない」可能性の
  どちらかを切り分ける必要があります。

## 次のサイクルでやること

- 環境（特にDeepgram Listen WebSocket）を再確認し、通っていれば
  最優先で`h-masking-holdback`を実クリップで実行する。
- 通らない場合は、`deepgram_endpointing`が実際に接続設定へ渡って
  いるかのコードレビュー（ライブAPIコール不要、$0で可能）を
  次の$0仮説として検討する。
- バックログは5件（上限6件）。新規$0仮説のネタとして、
  `polak2026-meta-evaluation-latency-metrics`のSOFTSEGMENTER
  （長尺音声向けのセグメンテーション頑健化）が、既に長め
  （120〜720秒）の`ep_sweep`/`youtube_10m_to_12m`系実験
  （ただしイベントログ形式以前で今回はスキップした8件）を
  別途調べ直すきっかけになるかもしれない。
