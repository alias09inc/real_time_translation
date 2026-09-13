# リサーチエージェント サイクル8 レポート (2026-09-11)

## 今回やったこと

サイクル7の振り返り（`GENERATE_HYPOTHESES`をスキップして`HUMAN_APPROVAL`
から再開）を受けて、今回は`HUMAN_APPROVAL`から開始しました。

1. **HUMAN_APPROVAL**: `hypotheses.json`を確認したところ、`approval`が
   未設定/`"proposed"`のものはゼロでした。キュー内の4件
   （`h-masking-holdback`, `h-localagreement-asr-commit`,
   `h-gemini-only-masking-replay`, `h-continuation-context-anchor`）は
   すべて前サイクルまでに`auto_approved`/`queued`済みです。
   `check-budget 1.5`・`check-budget 0.3`を再実行して`AUTO_APPROVE`を
   再確認し（本日分の予算は新しい日付にロールオーバー済み、
   $0/$7）、そのまま`RUN_EXPERIMENTS`へ進みました。

2. **RUN_EXPERIMENTS**: 実行前に環境を一から再確認しました。

   - `DEEPGRAM_API_KEY`・`GOOGLE_API_KEY`ともに設定済みで、REST
     エンドポイント（`api.deepgram.com/v1/projects`,
     `generativelanguage.googleapis.com/v1beta/models`）はいずれも
     HTTP 200。
   - `ffmpeg`は今回も未インストールでした。`apt-get install`を試みた
     ところ、`ffmpeg`自体のダウンロードは成功しましたが、無関係な
     パッケージ（`libva2`, `libssh-gcrypt-4`, `libcaca0`）でミラーの
     接続失敗/404が発生しトランザクションが完了せず、
     `apt-get update` + `--fix-missing`での再試行もこのセッション内
     では完了しませんでした。ただし後述の通りDeepgram側がブロック
     されているため、このサイクルの結論には影響しません。
   - `python3.13 -m venv` + `uv pip install -e ".[experiments]"`で
     仮想環境を構築（クリーンに成功）し、
     `wss://api.deepgram.com/v1/listen`への実際のWebSocketハンドシェイクを
     直接テストしました。結果は**サイクル5〜7とまったく同じ症状**です:
     - TLS証明書検証ありでは、プロキシが注入するCA証明書の
       key usage extension不足によるOpenSSLの厳格な検証エラー。
     - 検証を一時的に無効化すると、Deepgram（またはプロキシ）から
       **HTTP 400「Connection header did not include 'upgrade'」**。

   このインフラ制約はサイクル3から4サイクル・4日間変化していません。

   さらに、`h-gemini-only-masking-replay`（Deepgramを使わずに既存の
   実験JSONを"再生"してマスキング効果だけ検証する案）についても、
   サイクル5の結論を独立に再導出して確認しました:

   - 既存の実験JSON（47件、サイクル5時点と同数）はすべて
     `date < 2026-09-08`で、`original_text`フィールド
     （サイクル5でこの目的のために追加）が追加された2026-09-09
     より前のものしかなく、全件で空でした。
   - 代わりに`asr_interim`イベントのタイムスタンプを使って翻訳バッチ
     ごとの元テキストを近似できないか検証しましたが、サンプル1件
     （`20260903_asr_keyterms_off.json`）では翻訳バッチのキー42件中
     14件しか`asr_interim`のキーと厳密一致しませんでした。翻訳バッチの
     キーは「その回の新規フラグメント自身」の時刻（
     `pipeline._stream_batch`の`batch[0].original.start_time`）である
     のに対し、`asr_interim`イベントはDeepgram自身の発話相対時刻を
     持つため、単純結合ができません。近似結合で埋めた"元テキスト"を
     実際のLLMに投げて「本物のGemini出力に対するマスキング効果」と
     称するのは、入力側を事実上捏造することになり、PLAYBOOKの
     「結果を絶対に捏造しない」という原則に反するリスクがあると
     判断し、実装を見送りました。

   以上により、キュー内の4件全てが同じ根本原因（このサンドボックスの
   ネットワークプロキシがDeepgramのWebSocketアップグレードを正しく
   中継できない）でブロックされたままであることを確認しました。
   $0で実行できる遡及分析の新規仮説もキューにありません
   （`h-flicker-metric`/`h-cross-utterance-flicker`/
   `h-utterance-batch-timing`は既に過去サイクルでtested済み）。
   PLAYBOOKの縮退モードの指示に従い、何も捏造せず実験を実行せずに
   `ANALYZE_RESULTS`→`WRITE_REPORT`へ進みました。

3. **ANALYZE_RESULTS**: 数値的に分析する新規結果はありません
   （実験を実行しなかったため）。今回の実質的な成果は
   「`h-gemini-only-masking-replay`の代替再生アプローチも、結局は
   同じDeepgramブロッカーに帰着する」という結論を、サイクル5の記録に
   頼らず自分で再確認できたことです。

## 結果

今回もライブ実験は実行できませんでした（環境ブロッカーのため）。
サイクル7からの差分は次の2点です:

1. 環境ブロッカー（Deepgram Listen WebSocketのプロキシ問題）が
   4サイクル連続で同一の症状のまま変化していないことを再確認。
2. `h-gemini-only-masking-replay`が「Deepgram不要の$0代替案」では
   もはやなく、実質的に他の3件と同じ根本原因待ちであることを、
   具体的なデータ（既存47件のJSONの日付、`asr_interim`との結合率
   14/42）で再確認。この仮説はDeepgramアクセスが復旧した際に、
   通常の`h-masking-holdback`実行のついでに`original_text`付きの
   新しい記録が1本取れれば自動的に解消される見込みです。

## バックログの状態（4件、上限6件以内）

| ID | ステータス | 備考 |
| --- | --- | --- |
| h-flicker-metric | tested | サイクル1で完了 |
| h-cross-utterance-flicker | tested | サイクル4で完了（NE〜1.47の発見） |
| h-utterance-batch-timing | tested | サイクル6で完了 |
| h-masking-holdback | queued（ブロック中） | WebSocketアップグレードがプロキシで阻害。コード実装済み・即実行可能 |
| h-localagreement-asr-commit | queued（ブロック中・同じ原因） | 未実装のまま |
| h-gemini-only-masking-replay | queued（ブロック中） | 既存47件のJSONでは再生不可能と再確認。Deepgram復旧が唯一の解消策 |
| h-continuation-context-anchor | queued（ブロック中・同じ原因） | 未実装。通ってから実装しても即座に実行可能な設計 |

## 今回変更したファイル

- `research_agent/state/hypotheses.json`: 4件すべての`blocked_reason`に
  サイクル8の再確認結果を追記。
- `research_agent/state/pipeline_state.json`: 状態遷移の記録
  （`HUMAN_APPROVAL` → `RUN_EXPERIMENTS` → `ANALYZE_RESULTS` →
  `WRITE_REPORT`）。
- `research_agent/state/budget.json`: 日付ロールオーバー
  （2026-09-10 → 2026-09-11、使用額$0のまま）。

## 人間（rm-2278）へのお願い

- サイクル3から変わらず: このサンドボックス環境のネットワーク
  プロキシが`wss://api.deepgram.com/v1/listen`へのWebSocket
  アップグレード要求を正しく中継できていません（REST APIは200を
  返すのに対し、WebSocketアップグレードのみHTTP 400で拒否されます）。
  プロキシ設定でこのホストへのWebSocketアップグレードを許可
  （または生TCPでパススルー）いただけると、4件すべての待機中仮説
  （うち`h-masking-holdback`はコード実装済み・即実行可能）が
  一気に進みます。
- 上記が直せない場合でも、もし人間の方の環境（プロキシ制約のない
  マシン）で`h-masking-holdback`を1回だけ実クリップで実行して
  JSONを`experiments/`に追加していただければ、それ一本で
  `h-gemini-only-masking-replay`も同時に検証可能になります
  （`original_text`フィールドは既にコードに実装済みです）。

## 次のサイクルでやること

- 環境（特にDeepgram Listen WebSocket）を再確認し、通っていれば
  最優先で`h-masking-holdback`を実クリップで実行する（コードは
  実装済み・即実行可能）。
- 通らない場合は、バックログが4件（上限6件）に収まっているので、
  もう一段掘り下げた文献サーチ（継続バッチ文脈のプロンプト設計や、
  代理指標としてASRの部分列だけでも近似できる評価方法など）を
  検討する余地がある。$0の遡及分析のネタは出尽くしているため、
  次にSEARCH_PAPERSに戻るべきタイミングかどうかをREFLECTで判断する。
