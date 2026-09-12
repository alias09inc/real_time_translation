# リサーチエージェント サイクル10 レポート (2026-09-12)

## 今回やったこと

サイクル9のレポート末尾で「人間へのお願い」として明示した宿題
（`deepgram_endpointing`設定がDeepgram接続まで正しく届いているかの
コードレビュー）を、サイクル9自身の`REFLECT`でも次の一手として
名指ししていたため、今回は`SEARCH_PAPERS`を飛ばして
`GENERATE_HYPOTHESES`から着手しました。

1. **GENERATE_HYPOTHESES**: 新規仮説`h-endpointing-connection-verify`
   を追加しました（$0・ライブAPIコール一切不要な静的コード監査）。
   サイクル9の`h-cla-asr-latency-metric`が残した未検証の分岐
   ---「(a) このクリップの音声がエンドポインティングの閾値レンジを
   実質的に試せていないだけなのか」「(b) `deepgram_endpointing`の
   設定値がそもそもDeepgram接続まで届いていない実装バグなのか」---
   のうち(b)を直接検証する仮説です。バックログは5件（上限6件以内）
   を維持。

2. **HUMAN_APPROVAL**: `check-budget 0.0` → `AUTO_APPROVE`。
   `uses_existing_clips=true`（実際には既存クリップすら使わない、
   コードだけを読む監査のため、新規ダウンロード等の懸念は一切
   ありません）。

3. **RUN_EXPERIMENTS**: 環境を確認したところ
   `DEEPGRAM_API_KEY`/`GOOGLE_API_KEY`は設定済みでしたが、`ffmpeg`は
   今回も未インストールでした。ただし今回選んだ仮説はライブ音声も
   API呼び出しも一切必要としないため、この環境ギャップは無関係
   （moot）です。

   実際に行ったのは次のコード追跡です（すべて静的読解、実行なし）：

   1. `config.py:33,228` --- `Config.deepgram_endpointing`は
      デフォルト300、`DEEPGRAM_ENDPOINTING`環境変数で上書き可能。
   2. `youtube_segment.py:224-230`・`video_segment.py:216-222` ---
      実験ランナーの`--endpointing`CLI引数が渡されると
      `config.deepgram_endpointing`を上書きしてから
      `TranslationPipeline`を構築（＝エンドポインティング掃引実験群は
      本当に別々の値を使っていたことを再確認）。
   3. `pipeline.py:184` --- `TranslationPipeline`が
      `endpointing=config.deepgram_endpointing`を
      `DeepgramTranscriber`のコンストラクタへ渡す。
   4. `deepgram_client.py:91,143-144` --- `self._endpointing`として
      保持され、`_build_options()`が`None`でなければ
      `options['endpointing'] = str(self._endpointing)`をセット。
   5. `deepgram_client.py:165-167` --- `connect()`が
      `self._client.listen.v1.connect(**_build_options(...))`を呼び
      出し、`endpointing`を含むオプション一式をキーワード引数として
      渡す。

   ここで「SDK側が未知のキーワード引数を黙って無視していないか」を
   確認するため、本リポジトリの`pyproject.toml`が固定している
   `deepgram-sdk<6.0.0`と同じメジャーバージョン（実際に解決された
   のは5.3.4）のwheelをPyPIから直接ダウンロードして展開し、SDKの
   ソースコードを直接確認しました（`api.deepgram.com`はこの
   サンドボックスでブロックされていますが、PyPIは別ホストなので
   無関係に取得できました）。`deepgram/listen/v1/raw_client.py`の
   `connect()`を読んだ結果、`endpointing`は`**kwargs`に埋もれる
   任意引数ではなく明示的な名前付き引数として定義されており、
   関数内部で`None`でなければ
   `query_params.add('endpointing', endpointing)`として実際の
   WebSocket接続URLのクエリ文字列に無条件で追加されることを確認
   しました。

## 結果まとめ

- **結論：バグは見つからず、配線は正しいことを確認しました。**
  `config.deepgram_endpointing`は、設定ファイル・CLIオーバーライド・
  パイプライン構築・Deepgramクライアント・SDK自体のURL構築まで、
  途切れることなく正しく伝播しています。
- これによりサイクル9の分岐のうち**(b)「設定が届いていない」は
  否定されました**。サイクル9でCLAレイテンシがエンドポインティング
  300〜2000msの全域でほぼ一定（4.07〜4.10秒）だった現象は、
  **(a)「このクリップの音声がこのレンジで実質的な差を生まない」
  か、あるいは「CLA指標は確定済みASRテキストの安定性を測るもので、
  発話区切り（is_final/UtteranceEnd）のタイミングそのものは
  別軸である可能性」が引き続き有力な説明として残ります。
- 今回は**ライブAPIコールを一切使わず**（$0）、コード監査のみで
  完結しました。
- 環境ブロッカー（Deepgram Listen WebSocketのプロキシ問題）は
  今回のRUN_EXPERIMENTSの対象外だったため再確認していませんが、
  6サイクル・4日間、少なくともサイクル9時点までは症状が変化して
  いません。次に環境を再確認するのは、ライブ実験が必要な仮説を
  選ぶ次のサイクルになります。

## バックログの状態（5件、上限6件以内）

| ID | ステータス | 備考 |
| --- | --- | --- |
| h-flicker-metric | tested | サイクル1で完了 |
| h-cross-utterance-flicker | tested | サイクル4で完了（NE〜1.47の発見） |
| h-utterance-batch-timing | tested | サイクル6で完了 |
| h-cla-asr-latency-metric | tested | サイクル9で完了 |
| h-endpointing-connection-verify | tested | **今回完了**。配線は正しいと確認、バグなし |
| h-masking-holdback | queued（ブロック中） | WebSocketアップグレードがプロキシで阻害。コード実装済み・即実行可能 |
| h-localagreement-asr-commit | queued（ブロック中・同じ原因） | 未実装のまま |
| h-gemini-only-masking-replay | queued（ブロック中） | 既存47件のJSONでは再生不可能と再確認済み（サイクル8） |
| h-continuation-context-anchor | queued（ブロック中・同じ原因） | サイクル9で`beavertalk2025-sentence-memory-bank`の知見を追加済み |

## 今回変更・追加したファイル

- `research_agent/state/hypotheses.json`: `h-endpointing-connection-verify`
  を新規追加・実行（コード監査）・完了。
- `research_agent/state/pipeline_state.json`:
  `GENERATE_HYPOTHESES → HUMAN_APPROVAL → RUN_EXPERIMENTS →
  ANALYZE_RESULTS → WRITE_REPORT`の遷移を記録。
- `research_agent/state/budget.json`: $0のコストログを1件追加
  （実質支出なし）。
- 本レポート。

コード監査のためにダウンロードしたdeepgram-sdkのwheelファイルは
`/tmp`配下の一時ディレクトリのみに展開し、リポジトリには一切
コミットしていません。

## 人間（rm-2278）へのお願い

- サイクル3から変わらず: このサンドボックス環境のネットワーク
  プロキシが`wss://api.deepgram.com/v1/listen`へのWebSocket
  アップグレード要求を正しく中継できていません（cert検証ありでは
  プロキシCAのkey usage extension不足、検証なしではHTTP 400
  「Connection header did not include 'upgrade'」）。プロキシ設定で
  このホストへのWebSocketアップグレードを許可（または生TCPで
  パススルー）いただけると、4件すべての待機中仮説が一気に進みます。
- 今回の結論として：`deepgram_endpointing`の設定バグの可能性は
  排除できました。もしこの設定がこのクリップで本当に効いているか
  引き続き気になる場合は、より長い無音区間を含む別のクリップでの
  実験、または`is_final`/`UtteranceEnd`イベントのタイムスタンプを
  直接見る追加分析（いずれもDeepgramアクセスが復旧してから、または
  既存イベントログに十分な変化があれば$0で）が次の手になります。

## 次のサイクルでやること

- 環境（特にDeepgram Listen WebSocket）を再確認し、通っていれば
  最優先で`h-masking-holdback`を実クリップで実行する。
- 通らない場合、$0の遡及分析ネタとしては、サイクル9で触れた
  `polak2026-meta-evaluation-latency-metrics`のSOFTSEGMENTER
  （長尺音声向けのセグメンテーション頑健化）や、
  `is_final`/`UtteranceEnd`タイミングを直接測る新しい遡及分析
  （h-endpointing-connection-verifyが残した(a)の切り分けに使える）
  が候補です。
- バックログは5件（上限6件）で、まだ余地があります。
