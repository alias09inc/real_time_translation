# リサーチエージェント サイクル2 レポート (2026-09-08)

## 今回やったこと

1. **環境の復旧**: 前回サイクル終了時点では `DEEPGRAM_API_KEY` / `GOOGLE_API_KEY`
   が未設定・`ffmpeg` 未インストールという想定でしたが、今回のセッションでは
   両方の API キーが最初から設定されていました。`ffmpeg` のみ未インストール
   だったため `apt-get install ffmpeg` で導入し、実験実行の前提条件が
   揃いました（後述の通り、別のブロッカーが新たに見つかりました）。

2. **文献の抽出・読了**（前回 `found` のまま止まっていた3件）:
   - **AlignAtt4LLM**（IWSLT2026, arXiv:2606.03967）: Qwen3-ASR（強制アラインメント付き）
     と Gemma-4 E4B-it をカスケードし、**LLM自身のアテンション重み**を見て
     「どこまでソースを見れば安全に訳出できるか」を判断する手法でした。
     これは前回の想定（最長共通接頭辞での確定＝LocalAgreement系）とは
     **根本的に異なる**もので、しかも訳出モデルの内部アテンションへの
     white-box アクセスが前提です。本リポジトリは Gemini/OpenAI を
     API経由でしか使っておらず内部アテンションは取得できないため、
     **AlignAtt4LLM の手法そのものは本リポジトリには適用できない**と
     判断しました。`h-localagreement-asr-commit` は素の LocalAgreement-2
     （テキストレベルの最長共通接頭辞一致）のみを対象とするよう、仮説の
     記述を明確化しました。
   - **Google Research のライブ字幕安定性ブログ**: 実体は2023年 CHI 論文の
     紹介記事でした。画像処理（輝度コントラスト＋フーリエ変換）で
     「実際に画面でどれだけちらついて見えるか」を測る指標で、視聴者の
     体感（クラウドソース調査 N=123）との相関はあるものの中程度（|r|≈0.3）
     でした。テキストベースの NE がちらつきの完全な代理指標ではない、
     という留保として記録しました。実装コストが高いため今回は着手せず、
     将来の仮説候補として保留します。
   - **NVIDIA NeMo の IWSLT2026 提出システム**: ASR モデル自体を訓練段階で
     安定するように作り込むアプローチで、こちらも Deepgram をそのまま使う
     本リポジトリには転用できません。ただし「2026年のSOTAシステムは
     安定性を第一級の評価軸として扱っている」という傾向は改めて確認できました。
   - 注記: この環境では `WebFetch` が `arxiv.org` / `research.google` /
     `aclanthology.org` へのアクセスをすべてブロックされていました
     （egress proxy による `EGRESS_BLOCKED`）。`WebSearch` は問題なく
     動作したため、そちら経由でのスニペットベースの抽出になっています。
     数値の厳密な確認は、`WebFetch` が使える環境で改めて行うことを
     推奨します。

3. **実験の実装**: `h-masking-holdback`（訳出前に末尾N単語を保留する
   マスキング）を実装しました。
   - `MASKING_HOLDBACK_WORDS` 環境変数（デフォルト0＝無効）を追加
   - 発話が確定していない（続きが来る可能性がある）バッチでのみ、
     翻訳に送るテキストの末尾N単語を一時的に保留。保留した単語は
     消えるわけではなく、次の継続バッチ（または発話の本当の終わり）で
     必ず含まれます。
   - デフォルト無効なので、既存の本番動作には一切影響しません。

4. **実験の実行を試みたが、新たな環境ブロッカーを発見**:
   `wjZofJX0v4M` のキャッシュ済みクリップに対して baseline
   （`MASKING_HOLDBACK_WORDS=0`）を実行しようとしたところ、Deepgram の
   WebSocket 接続が **HTTP 403** で失敗しました。原因を切り分けたところ:
   - `curl` で直接 `api.deepgram.com` に接続 → **プロキシに拒否**
     （`connect_rejected`、組織ポリシーによる遮断と表示）
   - 同様に `generativelanguage.googleapis.com`（Gemini）に接続 →
     **200 OK、問題なし**
   - つまり **API キー自体は有効**で、**Gemini 側は疎通しているが、
     Deepgram 側だけがこのサンドボックスのネットワーク許可リストから
     漏れている**ことが分かりました。コードは実装・コミット済みなので、
     `api.deepgram.com` へのアクセスが許可され次第、そのまま実行できます。
   - 結果は一切捏造せず、`hypotheses.json` の該当仮説に
     `blocked_reason` として記録し、ステータスは `queued` のまま
     変更していません。

5. **回避策の仮説を追加**: Deepgram だけがブロックされ Gemini は
   使えるという発見を活かし、新しい $0.3 の仮説
   `h-gemini-only-masking-replay` を追加しました。既存の実験JSON
   （47ファイル）にはASRのイベントストリーム（`asr_interim` /
   `translation_partial` など）が既に丸ごと記録されているので、これを
   「あたかも今 Deepgram から届いたかのように」リプレイし、
   マスキングロジックを通して実際の Gemini 呼び出しだけで
   `h-masking-holdback` を検証する、という設計です。次サイクル以降で
   実装予定です（予算チェック済み・自動承認: $0.3）。

## バックログの状態（4件、上限6件以内）

| ID | ステータス | 備考 |
| --- | --- | --- |
| h-flicker-metric | tested | サイクル1で完了 |
| h-masking-holdback | queued（ブロック中） | コード実装済み、Deepgram遮断待ち |
| h-localagreement-asr-commit | queued（ブロック中） | 設計を素のLocalAgreement-2に明確化済み |
| h-gemini-only-masking-replay | queued（新規） | Deepgramを迂回する$0.3の代替実験。次サイクルで実装予定 |

## 人間（rm-2278）へのお願い

- このクラウド実行環境（サンドボックス）のネットワーク egress プロキシで
  `api.deepgram.com` への接続が組織ポリシーにより拒否されています。
  ライブASR実験をこの環境で継続的に回したい場合、プロキシの許可リストに
  `api.deepgram.com` を追加していただく必要があります（`generativelanguage.googleapis.com`
  は既に疎通しています）。
- それまでの間は `h-gemini-only-masking-replay`（Deepgramを使わない
  代替検証）で研究を継続します。

## 次のサイクルでやること

- `h-gemini-only-masking-replay` を実装・実行し、`h-masking-holdback` の
  効果を Deepgram なしで検証する。
- `api.deepgram.com` への疎通が回復していれば、`h-masking-holdback` と
  `h-localagreement-asr-commit` を実際にキャッシュ済みクリップ上で
  A/Bテストする。
