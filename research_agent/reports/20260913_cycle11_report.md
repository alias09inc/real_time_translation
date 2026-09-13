# リサーチエージェント サイクル11 レポート (2026-09-13)

## 今回やったこと

サイクル10の`REFLECT`が名指ししていた次の一手（`is_final`/
`UtteranceEnd`イベントのタイミングを直接測る、文献探索不要の$0遡及
分析）に沿って、`SEARCH_PAPERS`を飛ばして`GENERATE_HYPOTHESES`から
着手しました。

1. **GENERATE_HYPOTHESES**: 新規仮説`h-asr-final-emission-latency`を
   追加しました。バックログは5件（上限6件以内）を維持。

2. **HUMAN_APPROVAL**: `check-budget 0.0` → `AUTO_APPROVE`
   （`uses_existing_clips=true`、ライブAPIコール不要）。

3. **RUN_EXPERIMENTS**: 実装に着手した時点で、当初の仮説の前提に
   誤りがあることが判明しました。当初は「`TimedEvent`に`asr_final`
   という区別されたイベント種別と`is_final`フラグが記録されている」
   と想定していましたが、実データを確認すると、ASRイベントは常に
   `kind="asr_interim"`・`is_final=False`で記録されており、
   `translation_partial`/`translation_complete`イベントの
   `is_final`フィールドは「翻訳呼び出しが完了したか」という別の
   意味でした。

   `deepgram_client.py`を読み直し、本当に必要な信号は既存の
   `is_utterance_end`フィールドだと判明しました。これは
   - `True`：Deepgram自身の`is_final`/`UtteranceEnd`による、
     本当の（エンドポインティング設定が支配する）発話終了
   - `False`：連続音声がDeepgram自身の終了判定より先に、固定値
     `deepgram_max_interim_duration`（今回の実験群では2.5秒）の
     タイマーで強制的に打ち切られた「ソフト・ファイナライズ」

   という2種類を既に区別しており、新しいフィールドも新しい録音も
   不要でした。仮説の`description`をこの発見に基づいて訂正した上で、
   `src/real_time_translation/experiments/utterance_end_mix.py`を
   新規実装し、既存47件の実験JSON全件に対して実行しました
   （`experiments/utterance_end_mix.csv`に出力、`ruff check`済み、
   コンソールスクリプト`real-time-translation-exp-utterance-end-mix`
   として`pyproject.toml`に登録）。$0・ライブAPIコールなし。

## 結果まとめ（h-asr-final-emission-latency: 予測どおり確認）

`chunk_latency_sweep`系列（endpointing 300/500/800/1200/1500/2000ms、
2つの独立した掃引ファミリー、計12ファイル）について：

| endpointing | sweep1 soft% | sweep2 soft% |
| --- | --- | --- |
| 300ms | 50.0% | 56.8% |
| 500ms | 52.4% | 64.7% |
| 800ms | 52.6% | 62.9% |
| 1200ms | 55.6% | 62.9% |
| 1500ms | 55.0% | 62.9% |
| 2000ms | 56.2% | 62.9% |

- ソフト・ファイナライズ（固定2.5秒タイマーによる強制打ち切り）の
  割合は、300msから2000msまでの全域でどちらの系列も50〜65%の狭い
  範囲に収まり、**エンドポインティング設定値との明確な単調関係は
  見られませんでした**。
- sweep2のendpointing 800ms以上の4本（800/1200/1500/2000ms）は
  バッチ数35・soft%62.9%・平均時間まで完全に一致するビット単位の
  同一結果でした。これはサイクル10の`h-endpointing-connection-verify`
  が独立に発見していた「500〜2000msの4本が最終ASRテキスト・
  タイムスタンプまでビット一致」という事実と整合します。
- genuine-final（本当のDeepgram終了判定）バッチの平均時間も
  1.6〜3.35秒の範囲でendpointingとの順序関係なく散らばり、
  soft-finalizedバッチの平均時間はどちらの系列でも3.1〜3.9秒の
  狭い帯に収まっていました（サイクル6の`h-utterance-batch-timing`
  が見つけた「初回バッチ持続時間は2.5〜3.5秒付近に集中」という
  結果とも一致します）。

**結論**：サイクル9の`h-cla-asr-latency-metric`でCLAレイテンシが
endpointing全域でほぼ一定だった現象、およびサイクル10の
`h-endpointing-connection-verify`が残した説明(a)「このクリップの
音声レンジがエンドポインティングの効果を実質的に試せていない」を、
今回さらに機構的に裏付けることができました。この動画クリップでは
committed batchの約半数〜3分の2が、Deepgram自身のエンドポインティング
判定より先に、endpointing設定と完全に無関係な固定2.5秒タイマーで
打ち切られています。つまり、この音声・このパイプライン設定の組み
合わせでは、endpointing設定を掃引しても、そもそも効果を発揮する
機会がほとんど与えられていなかった、という具体的な説明です。

## バックログの状態（queued/proposedは4件、上限6件以内）

| ID | ステータス | 備考 |
| --- | --- | --- |
| h-flicker-metric | tested | サイクル1で完了 |
| h-cross-utterance-flicker | tested | サイクル4で完了 |
| h-utterance-batch-timing | tested | サイクル6で完了 |
| h-cla-asr-latency-metric | tested | サイクル9で完了 |
| h-endpointing-connection-verify | tested | サイクル10で完了 |
| h-asr-final-emission-latency | tested | **今回完了** |
| h-masking-holdback | queued（ブロック中） | WebSocketアップグレードがプロキシで阻害。コード実装済み・即実行可能 |
| h-localagreement-asr-commit | queued（ブロック中・同じ原因） | 未実装のまま |
| h-gemini-only-masking-replay | queued（ブロック中） | 既存47件のJSONでは再生不可能と再確認済み（サイクル8） |
| h-continuation-context-anchor | queued（ブロック中・同じ原因） | サイクル9で知見追加済み |

## 今回変更・追加したファイル

- `src/real_time_translation/experiments/utterance_end_mix.py`（新規）
- `experiments/utterance_end_mix.csv`（新規、分析結果）
- `pyproject.toml`: コンソールスクリプト
  `real-time-translation-exp-utterance-end-mix`を追加
- `research_agent/state/hypotheses.json`: `h-asr-final-emission-latency`
  を追加・訂正・実行・完了
- `research_agent/state/pipeline_state.json`:
  `GENERATE_HYPOTHESES → HUMAN_APPROVAL → RUN_EXPERIMENTS →
  ANALYZE_RESULTS → WRITE_REPORT`の遷移を記録
- `research_agent/state/budget.json`: $0のコストログを1件追加
- 本レポート

## 人間（rm-2278）へのお願い（環境ブロッカー、変更なし）

サイクル3から変わらず: このサンドボックス環境のネットワークプロキシ
が`wss://api.deepgram.com/v1/listen`へのWebSocketアップグレード要求
を正しく中継できていません（cert検証ありではプロキシCAのkey usage
extension不足、検証なしではHTTP 400「Connection header did not
include 'upgrade'」）。プロキシ設定でこのホストへのWebSocket
アップグレードを許可（または生TCPでパススルー）いただけると、
4件すべての待機中仮説（`h-masking-holdback`はコード実装済みで即
実行可能）が一気に進みます。今サイクルはこの点を再検証する対象の
仮説を選ばなかったため、環境の再チェックは行っていません。

## 次のサイクルでやること

- 環境（特にDeepgram Listen WebSocket）を再確認し、通っていれば
  最優先で`h-masking-holdback`を実クリップで実行する。
- 通らない場合、今回の発見（`deepgram_max_interim_duration`が
  endpointingの効果を構造的に競合・先取りしている）を踏まえ、
  `max_interim_duration`を大きく上げた（あるいは無効化した）新しい
  ライブ実験を提案することが、endpointingの本当の効果を確認する
  ための具体的な次の一手になります（ただしこれもDeepgramアクセス
  復旧が前提）。
- $0で続けられる遡及分析のネタは今サイクルでかなり掘り尽くした
  印象があるため（内部NE・跨バッチNE・タイミング・CLA・配線監査・
  ソフト/ジェニュイン終了ミックス）、次サイクルは文献探索
  （`SEARCH_PAPERS`）に戻ることを検討する価値があります。
- バックログ（queued/proposed）は4件（上限6件）で、まだ2件分の
  余地があります。
