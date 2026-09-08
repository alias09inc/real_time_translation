# リサーチエージェント サイクル3 レポート (2026-09-08)

## 今回やったこと

1. **GENERATE_HYPOTHESES（ノーオペ確認）**: サイクル2の振り返りで決めた通り、
   新しい仮説は追加せず、バックログ4件（上限6件以内）を再確認しただけで
   `HUMAN_APPROVAL` に進みました。すべて既に `auto_approved` / `queued` で、
   予算チェック（`check-budget 1.5` → `AUTO_APPROVE`、当日消費 $0/$7）も
   問題ありませんでした。

2. **環境の再確認 — 前回のブロッカーは"部分的に"解消していた**:
   - `ffmpeg`: 今回のセッションでも未インストールでしたが、
     `apt-get install ffmpeg` で問題なく導入できました。
   - `api.deepgram.com`（REST）: 前回セッションでは疎通不可
     （プロキシに `connect_rejected` される）でしたが、今回は
     `curl -H "Authorization: Token $DEEPGRAM_API_KEY" https://api.deepgram.com/v1/projects`
     が **200** を返しました。同じ日でもセッションによってネットワーク許可
     状態が変わることが分かりました。
   - この時点で「前回のブロッカーは解消した」と判断し、既に実装済みの
     `h-masking-holdback` をキャッシュ済みクリップ（`wjZofJX0v4M` 5:00〜6:30、
     `chunk_latency_sweep2_300ms` ベースラインと同一条件）で実際に
     ライブ実行することにしました（コストが最安の `h-gemini-only-masking-replay`
     をあえて後回しにした理由は下記）。

3. **新しい、より具体的なブロッカーを発見**: REST は通っても、実験ランナーが
   実際に使う **Deepgram のリスニング用WebSocket**（`wss://api.deepgram.com/v1/listen`）
   の接続確立は今回も **HTTP 403**（`Unexpected error when initializing
   websocket connection`）で失敗しました。SDK が keyterm 数を自動的に
   27→13→6→3→1→0 と減らしながらリトライするロジックがありますが、
   keyterm 0件でも失敗したため、keyterm 起因ではありません。
   - 課金対象のAPI呼び出しは一切発生していません（音声データが送られる
     前に接続自体が失敗するため）。`log-cost` は該当なし（$0）。
   - **「RESTが通る＝ストリーミングも通る」ではない**ことが今回の重要な
     発見です。プロキシがプロトコル単位（HTTPS通常リクエスト vs
     WebSocketアップグレード）で許可・拒否を分けている可能性、あるいは
     Deepgram側でREST権限とストリーミング権限が別スコープになっている
     可能性のどちらかですが、このセッションからはインフラ側の詳細までは
     切り分けられませんでした。
   - `PLAYBOOK.md` の環境チェック手順に、実際の Listen WebSocket への
     接続テスト（Python + `websockets` ライブラリでの直接確認コード）を
     追加し、次回セッションが同じ落とし穴に、コードを書いてから気づく
     のではなく、最初の状況確認の時点で気づけるようにしました。

4. **`h-gemini-only-masking-replay` の実装に着手する前に、設計上の
   見落としを発見**: リプレイハーネッシュを書き始める前に `pipeline.py`
   を読み直したところ、既存の `flicker_metrics.py` の
   `group_translation()` は翻訳イベントを **1回のバッチ呼び出し単位**
   （`(asr_start_time, asr_end_time)`）でグルーピングしていることが
   分かりました。ところが `_stream_batch()` のドキュメントによれば、
   同じ発話の続きが来るたびに **`full_target_text` をゼロから再翻訳**
   しています。つまり `h-masking-holdback` が本来狙っている「発話が
   進むにつれて訳文の前半が書き換わってしまう」ちらつきは、
   **1回のバッチをまたいだ現象**であり、現状の `group_translation()`
   はバッチ内（トークンがストリーミングで追記されるだけの区間）しか
   見ていないため、**そもそも測れていません**。
   - これは `h-flicker-metric`（サイクル1）の「翻訳レベルのNEはほぼ0」
     という結論自体は事実ですが、「バッチをまたいだ書き換えは無い」と
     まで主張できるものではなかった、ということを意味します。
   - このままリプレイハーネッシュを実装すると、正しくない指標で
     「効果あり/なし」を判定してしまうリスクがあったため、**今回は
     実装を急がず、この設計課題を記録するだけに留めました**。
     結果を捏造しない・誤った測定で誤った結論を出さない、という
     プレイブックの方針を優先しました。

## バックログの状態（4件、上限6件以内・変更なし）

| ID | ステータス | 備考 |
| --- | --- | --- |
| h-flicker-metric | tested | サイクル1で完了 |
| h-masking-holdback | queued（ブロック中・原因を再切り分け） | REST疎通OK、Listen WebSocketが403 |
| h-localagreement-asr-commit | queued（ブロック中・同じ原因） | 未実装のまま |
| h-gemini-only-masking-replay | queued（実装保留） | バッチ横断のNE測定を設計してから着手する必要あり |

## 今回変更したファイル

- `research_agent/state/hypotheses.json`: `h-masking-holdback` /
  `h-localagreement-asr-commit` の `blocked_reason` を更新、
  `h-gemini-only-masking-replay` に設計課題のメモを追加。
- `research_agent/PLAYBOOK.md`: 環境チェックに Listen WebSocket の
  直接テストを追加。`uv sync`/`uv run` が `zoom` extra（testpypi 上の
  `rtms`）の解決に失敗する問題への回避策
  （`uv pip install -e ".[experiments]"` を使う）も記録。

## 人間（rm-2278）へのお願い

- サンドボックスのネットワーク許可状態はセッションごとに変わるようです
  （今回はDeepgramのRESTは通ったが、WebSocketは依然拒否）。可能であれば、
  `api.deepgram.com` への **WebSocketアップグレードを含めた**恒久的な
  許可をプロキシ側で設定していただけると、ライブ実験が安定して回せます。
- 上記が難しい場合は、次サイクルで `h-gemini-only-masking-replay`
  （Deepgramを使わない代替検証）を、バッチ横断のちらつき測定を
  正しく設計した上で実装します。

## 次のサイクルでやること

- `GENERATE_HYPOTHESES` で、バッチ横断（発話単位）の翻訳ちらつきを
  正しく測る新しい分析仮説（例: 各発話の連続する `full_target_text`
  再翻訳結果を直接diffする）の追加を検討する。
- それを踏まえて `h-gemini-only-masking-replay` を実装・実行するか、
  Deepgramの WebSocket 疎通が回復していれば `h-masking-holdback` /
  `h-localagreement-asr-commit` を実クリップでA/Bテストする。
