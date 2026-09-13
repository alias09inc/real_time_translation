# リサーチエージェント サイクル7 レポート (2026-09-10)

## 今回やったこと

1. **SEARCH_PAPERS**: サイクル6の振り返りで指摘されていた通り
   （既存47件の実験コーパスに対する$0の遡及分析はほぼ出尽くした
   ため、文献の再サーチの方が価値が高い）、サイクル5以来2回目の
   新規WebSearchを実施しました。「複数バッチ・継続発話の
   再翻訳安定化ポリシー」「LLMベースの翻訳プロンプト手法」
   「ASRベンダーの最新レイテンシ数値」を軸に検索し、3件の新しい
   候補論文を`papers.json`に`found`として追加しました。

2. **EXTRACT_PAPERS / READ_PAPERS**: WebFetchは今回も`arxiv.org`に
   対して`EGRESS_BLOCKED`（サイクル2〜5と同じ）だったため、
   WebSearchのスニペットから要約・key findingsを作成しました。
   最大の収穫は、2件の論文が独立に同じ方向を指し示していたことです:

   - **hoang2026-dynamic-lagging**（Microsoft、arXiv 2609.05799）:
     デコーダのみのLLM（Qwen3-8B）をファインチューニングし、
     「これまでにコミットした訳文をforce-decodeで引き継ぎながら
     継続部分を翻訳する」ことで、後付けのマスキングではなく
     **構造的にちらつきが出ない**翻訳を実現。EN→JA/DE/ZHで評価
     されており、EN→JAはまさに本リポジトリのユースケース。
   - **koshkin2024-tollmatch-zeroshot-context-aware**（NAIST、
     EMNLP 2024、arXiv 2406.13476）: ファインチューニング**なし**
     のゼロショットLLMでも、プロンプトに文脈情報を注入するだけで
     既存手法に匹敵・上回る同時翻訳品質が得られると報告。
     本リポジトリのAPIベース（Gemini/OpenAI）翻訳者と
     アーキテクチャ的に最も近い先行研究でした。

   この2件を本リポジトリの`pipeline.py`と突き合わせたところ、
   実際に**未対応のギャップ**を発見しました:
   `_stream_batch()`のdocstringが明言している通り、進行中の発話の
   継続バッチ（`live=False`）は**毎回ゼロから再翻訳**しており、
   `commit_context()`（翻訳者のローリング文脈バッファ）は発話全体が
   終わったとき（`is_utterance_end`）にしか呼ばれません。つまり、
   継続バッチはその発話自身がすでに画面に出している訳文について
   一切の手がかりを与えられていません。これはサイクル4で確認した
   バッチ横断NE〜1.47（バッチ内〜0.0001とは桁違い）の「ちらつき」の
   根本原因と正確に一致します。

   3件目の**mllp-vrain-iwslt2026-simulst**（IWSLT 2026、
   arXiv 2606.17255）は、内部の注意重みを必要としない
   「ブラックボックス」な読み書きポリシーと、「破滅的な失敗を
   検知したときだけ直近2トークンの書き換えを許す」という
   境界付き書き換え方式を報告しており、既存の`h-localagreement-asr-commit`
   と`h-masking-holdback`それぞれへの追加の裏付けとして記録しました。

3. **GENERATE_HYPOTHESES**: 上記の発見を新しい仮説
   `h-continuation-context-anchor`として追加しました。継続バッチに
   限り、その発話がこれまでに出力した訳文を`<prior_translation>`
   ブロックとしてプロンプトに追加し、「ゼロから訳し直すのではなく
   維持・延長する」よう指示する案です。バックログは4件
   （上限6件以内）になりました。

4. **HUMAN_APPROVAL**: `h-continuation-context-anchor`の見積もり
   コストは$1.5（既存キャッシュ済みクリップを再利用、新規ダウンロード
   なし）。`check-budget 1.5`は`AUTO_APPROVE`（本日の使用額
   $0/$7）。`approval=auto_approved` / `status=queued`に設定。

5. **RUN_EXPERIMENTS**: 実行前に環境を再確認しました。`ffmpeg`は
   今回のセッションでも未インストールでしたが`apt-get install`で
   問題なく解決。`python3.13 -m venv` + `uv pip install -e
   ".[experiments]"`で仮想環境を構築し、`wss://api.deepgram.com/v1/listen`
   への実際のWebSocketハンドシェイクを直接テストしました。結果は
   サイクル5・6と**まったく同じ症状**でした:
   - TLS証明書検証でまずエラー（プロキシが注入するCA証明書の
     key usage extension不足によるOpenSSLの厳格な検証エラー）。
   - 検証を一時的に無効化すると、Deepgramから
     **HTTP 400「Connection header did not include 'upgrade'」**。

   このインフラ側の制約はサイクル3から一貫して改善していません。
   `h-masking-holdback` / `h-localagreement-asr-commit` /
   `h-gemini-only-masking-replay` に加えて、今回新規追加した
   `h-continuation-context-anchor`もライブASR駆動の継続バッチが
   必要なため、同じ理由でブロックされます（実装前にこの点を
   確認したため、まだコードは書いていません — 通ってから書いても
   コスト的に問題ないため）。4件すべて`blocked_reason`に今回の
   再確認結果を追記しました。

   $0/ライブAPI不要の新しい仮説は今回キューにないため（遡及分析は
   サイクル6までにほぼ出尽くし）、PLAYBOOKの縮退モードの指示に
   従い、実験を実行せず（何も捏造せず）WRITE_REPORTに進みました。

## 結果

今回はライブ実験は実行できませんでした（環境ブロッカーのため）。
新規に得られた成果は次の2点です:

1. 文献ベースの裏付けを伴う、新しい・具体的で実装コストの低い
   仮説（`h-continuation-context-anchor`）の追加。
2. その仮説の設計中に、`pipeline.py`のコードレベルで
   「継続バッチが自分自身の既出訳文の文脈を一切受け取っていない」
   という、これまで文書化されていなかったギャップを直接確認できた
   こと。これは推測ではなくコードのdocstring・実装から確認した
   事実です。

## バックログの状態（4件、上限6件以内）

| ID | ステータス | 備考 |
| --- | --- | --- |
| h-flicker-metric | tested | サイクル1で完了 |
| h-cross-utterance-flicker | tested | サイクル4で完了（NE〜1.47の発見） |
| h-utterance-batch-timing | tested | サイクル6で完了 |
| h-masking-holdback | queued（ブロック中） | WebSocketアップグレードがプロキシで阻害。コード実装済み・即実行可能 |
| h-localagreement-asr-commit | queued（ブロック中・同じ原因） | 未実装のまま |
| h-gemini-only-masking-replay | queued（ブロック中） | 既存JSONでは実行不可、新規録画が必要 |
| h-continuation-context-anchor | queued（ブロック中・同じ原因、新規） | 未実装。通ってから実装しても即座に実行可能な設計 |

## 今回変更したファイル

- `research_agent/state/papers.json`: 新規3件の論文を追加・要約・
  `relevant_to`を記入。
- `research_agent/state/hypotheses.json`: `h-continuation-context-anchor`
  を新規追加、承認、4件すべての`blocked_reason`に今回の再確認結果を
  追記。
- `research_agent/state/pipeline_state.json`: 状態遷移の記録。

## 人間（rm-2278）へのお願い

- サイクル3から変わらず: このサンドボックス環境のネットワーク
  プロキシが`wss://api.deepgram.com/v1/listen`へのWebSocket
  アップグレード要求を正しく中継できていません（REST APIは200を
  返すのに対し、WebSocketアップグレードのみHTTP 400で拒否されます）。
  プロキシ設定でこのホストへのWebSocketアップグレードを許可
  （または生TCPでパススルー）いただけると、4件すべての待機中仮説
  （うち`h-masking-holdback`はコード実装済み・即実行可能）が
  一気に進みます。

## 次のサイクルでやること

- 環境（特にDeepgram Listen WebSocket）を再確認し、通っていれば
  最優先で`h-masking-holdback`を実クリップで実行する（コードは
  実装済み・即実行可能）。次点で`h-continuation-context-anchor`の
  実装（`llm_translator.py`のプロンプト拡張＋`pipeline.py`の
  継続バッチ文脈受け渡し）に着手する。
- 通らない場合は、バックログが4件（上限6件）に収まっているので、
  さらに$0の遡及分析やもう1件程度の新規仮説を検討する余地はあるが、
  サイクル6の振り返り通り遡及分析のネタは出尽くしつつある。次の
  自然な一手はプロキシ問題の解消を待つか、もう一段掘り下げた
  文献サーチ（例えば継続バッチ文脈の具体的なプロンプト設計例を
  探す）になる。
