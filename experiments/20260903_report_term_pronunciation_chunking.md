# 翻訳精度改善レポート: 専門用語・発音変換・チャンク長

作成日: 2026-09-03(更新版)
対象: 「専門用語に弱い」「発音の変換に失敗」「チャンクが短すぎて翻訳に失敗」の3課題に対する調査

## 更新に関する注記

本レポートの初版は `.env` のAPIキーがプレースホルダーのままの環境で作成しており、新規実験がすべて未実行だった。その後キーが設定され、さらに `git pull`(`feat/rm2278/async-containers`、`166ca22..9f9d0be`)により、**2026-07-22〜08-06にかけて既に実施されていた大規模な実機実験一式**(75分フル動画での辞書比較、5モデル比較、ASR ground truth比較、チャンク長関連のバグ修正など)を取り込んだ。これらは私が初版で計画していた実験のほぼ全てを、より大きなスケールと厳密な方法論で先取りしていたため、本レポートはそれらを一次情報として整理し直した。さらに、そこで見つかった2つのギャップ(§2.2, §3.3)について、鍵が使えるようになった環境で実際に追加実験を実施し、結果を反映済み(第3版)。

## 0. サマリー

| 課題 | 状態 | 参照すべき一次資料 |
| --- | --- | --- |
| 1. 専門用語に弱い | **既存の実装+定量実験で解決策あり**。事前抽出の仕組みは既に実装・運用実績あり | `src/real_time_translation/preload/`, `dictionaries/`, `experiments/20260724_dictionary_comparison_report.json` |
| 2. 発音の変換に失敗 | 既存のground truthベンチマークで詳細分析済み。追加実験(keyterm ON/OFF)は**null結果**(§2.2) | `experiments/clips/hardest_5min_BENCHMARK_README.md`、`experiments/20260903_asr_keyterms_on3/off3.json` |
| 3. チャンクが短すぎて翻訳に失敗 | セグメント重複の重大バグを発見・修正済み。修正後の正式なsweepを実施した結果、**endpointing自体の効果は小さく**、`deepgram_max_interim_duration`の方が支配的である可能性が判明(§3.3) | `experiments/results.csv`、`experiments/20260903_chunk_latency_sweep2_*ms.json` |

---

## 1. 専門用語に弱い問題

### 1.1 「事前に専門用語辞書を抽出する」仕組みは既に実装されている

前回の質問への回答: **記録があった。** `src/real_time_translation/preload/` 配下に、セッション開始前に資料から専門用語を自動抽出する一式が実装済み。

| モジュール | 役割 |
| --- | --- |
| `preload/term_extractor.py` | LLM(Gemini/OpenAI)に生テキスト or スライド画像を渡し、`{source_term, target_term, notes}` のJSONを抽出させる共通ロジック |
| `preload/document_extractor.py` / `document_preload.py` | PDF/PPTXからテキストを抜き出し、上記extractorに渡す |
| `preload/video_preload.py` | 動画から数フレームを画像としてサンプリングし、Gemini Visionでスライド文字(タイトル・箇条書き・軸ラベル・数式等)を読み取って用語抽出(Vision専用、OpenAIには未対応) |
| `preload/auto_preload.py` | 拡張子で自動振り分け(`.pdf`/`.pptx`→document、`.mp4`等→video)。`PRELOAD_SOURCE=slides.pdf` を設定するだけで起動時に自動実行。抽出結果はファイルの内容(パス+サイズ+mtime)でハッシュ化してキャッシュされ、同じ資料への再実行はLLM呼び出しを再課金しない |
| `translation/domain_packs.py` + `dictionaries/domains/*.csv` | 動画固有ではない、ドメイン共通の辞書パック(`machine_learning.csv`, `particle_physics.csv`)。セッション固有辞書より優先度は低い |

CLIエントリポイント: `real-time-translation-preload-doc`, `real-time-translation-preload-video`(`pyproject.toml`参照)。

**実際に動画から抽出された成果物が存在する**: `dictionaries/sessions/LLM2024_8_part1.csv`(115行、`LLM2024_8_part1.mp4`から`video_preload`で自動生成されたと推測される)。中身は`Matsuo-Iwasawa Lab`→`松尾・岩澤研究室`、`LLM`→`大規模言語モデル`のような講演固有の固有名詞・専門語が並んでおり、汎用辞書では拾えない語がカバーされている。

### 1.2 定量評価: 事前抽出辞書あり/なしの比較(75分フル動画)

`experiments/20260724_dictionary_comparison_report.json`(`video/LLM2024_8_part1.mp4`全編、Deepgram nova-3 → Gemini 3.1 Flash-lite):

| 条件 | セグメント数 | avg confidence | 用語カバレッジ(glossary adherence) | 未対応語 |
| --- | --- | --- | --- | --- |
| 辞書あり(セッション抽出辞書、33語期待) | 1811 | 0.9460 | **1.00**(33/33) | なし |
| 辞書なし(基本`dictionary.csv`のみ、49語) | 1810 | 0.9412 | 0.931(27/29) | `Arena Score`, `Tokens Per Second` |

質的差(`experiments/20260724_dictionary_comparison_qualitative_examples.txt`より):
- `Arena Score` → 辞書なしでは「アリーナスコア」(競技場という一般名詞に空目)、辞書ありでは「Arenaスコア」(LMSYSのベンチマーク名として正しく保持)
- `Tokens Per Second` → 辞書なしでは「スーパー・トークン・パー・セカンド」(逐語カタカナ化)、辞書ありでは「トークン毎秒」(実際の業界標準表現)

**結論**: 「完璧な資料があればどこまで対応できるか」という当初の問いに対しては、この実験が実質的な回答になっている。事前抽出辞書は、辞書に載っている語に関しては**カバレッジ100%**を達成し、単なる直訳ではなく業界標準の訳語選択にも効いている。

### 1.3 私が追加で行った分析(独立データとしての価値)

初版で行った、2026-04-01時点の実験(`20260401_youtube_10m_to_20m.json`、AI/ML講演、60セグメント、**このセッション固有辞書機能が実装される前**のデータ)に対する人手での失敗分類は、上記の大規模実験とは別動画・別時期の一次データであり、クロスチェックとして残す価値がある。11件の事例(ASR誤聴7件、翻訳側の過剰保持1件、正常系2件、辞書バグ1件)は前版参照。特に注目すべきは:

- 当時見つけた `laundry model`(誤聴、正解`language model`)が、**後日・別チームによる独立したベンチマーク**(`hardest_5min_BENCHMARK_README.md`、§2参照)でも `launching model`(同じ単語への別の誤聴パターン)として**再現されている**。同じ実在語("language model")が、独立した2回の実験で2種類の異なる誤聴を生んでいることは、この語がDeepgramにとって系統的に脆弱であることの強い傍証になる。

- `dictionary.csv` のCSVパースバグ(`CBRN`行の未クォートカンマにより `Biological → Radiological` という誤エントリが混入する問題)は、**現在の`dictionary.csv`では修正済み**であることを確認した(`CBRN,CBRN,"Chemical, Biological, Radiological, Nuclear risks"` と正しくクォートされている)。

---

## 2. 発音の変換に失敗(ASR誤聴)

### 2.1 既存の権威あるベンチマーク

`experiments/clips/hardest_5min_BENCHMARK_README.md` に、75分フル動画中で**最もASR信頼度が低い5分間**(`find_hardest_segment.py`で自動特定)を対象にした、非常に丁寧な誤聴分析がある:

- **正解データの作り方**: 動画+スライドをGemini 3.1 Proに渡し、非リアルタイムで「注意深い書き起こし」を作成(曖昧な箇所は明示的にフラグ)。これをリアルタイムパイプラインの実際の出力(Deepgram, `hardest_5min_deepgram_realtime.txt`)と突き合わせ。
- **確認された誤り8件**中、**6件がconfidence 0.93以上**で発生(例: "the medicine for your launching model"←正しくは"the right thing for your language model"、confidence 0.999)。
- **結論として明記**: 「confidenceしきい値によるレビュー(例: 0.8未満をフラグ)」では、まさに専門用語の誤変換(medicine, spotty, country, data site, IO, sewing)を**軒並み見逃す**。confidenceは誤聴検知の指標として機能しない。

これは初版で私が「conf 0.97でも`laundry model`のような誤りが起きる」と指摘した内容を、より厳密な方法論(独立なground truth書き起こし)で裏付けている。

### 2.2 追加実験: Keyterm PromptingがASR誤聴そのものを減らすか(実施結果)

`wjZofJX0v4M`(5:00〜, ffmpeg+Deepgramで実処理、`real-time-translation-exp-video`)を使い、**Deepgramへのkeyterm提示だけをON/OFFして**(翻訳側の辞書ルックアップは両条件で同一)、同一区間のASR出力を比較する実験を実施した(`DEEPGRAM_KEYTERMS_ENABLED=true/false`、他は完全に同一条件)。

**結果は null(有意差なし)**。約3.5分間(6.3〜214.8秒、29 vs 28セグメント、文字数2109 vs 2057)の書き起こしはほぼ完全に一致しており、`transformer`・`attention blocks`・`multilayer perceptron blocks`のような辞書収録語はkeyterm ON/OFFどちらでも正しく認識されていた。1箇所だけ、OFF条件で"Some of you in the know may remember how long before chat GPT came into the..."という発話が丸ごと欠落している(ON条件には存在)が、これが意味のある差かは1サンプルでは判断できない。

**この結果の解釈には注意が必要**: このテスト区間はネイティブスピーカーの流暢なナレーションで、§2.1のhardest_5min(訛りのある非ネイティブ英語・ディスフルエンシー多数・专門用語密度が高いQ&A)ほど「難しい」区間ではなかった。つまり今回のnull結果は「keyterm promptingに効果がない」ことの証明ではなく、**「デフォルトのDeepgramモデルが既に得意な区間ではkeyterm の追加効果が観測しづらい」**ことを示しているに過ぎない。§2.1で実際に誤聴が確認された"language model"→"launching model"や"KV cache"→"KV catch"のような、実際に失敗が起きている語・区間を対象にこの比較をやり直すのが正しい次のステップ(今回はそのものずばりの音声区間の入手手段がなかったため未実施、§4参照)。

**副次的な発見(運用上の注意)**: 10分間(600秒)の区間長・speed=3.0でこの実験を最初に試みたところ、2回とも配信の途中でDeepgram接続が`1011 (internal error) did not receive audio data`エラーで切れ、それぞれ全体の6%・44%程度しか処理できずに終了した。区間を4分・speed=1.5に落としたところ安定して完走した。長時間・高速再生条件でのストリーム安定性に何らかの限界がある可能性があり、実運用(通常はspeed=1.0のリアルタイム再生)への直接の影響は小さいと考えられるものの、実験ツールとしては認識しておくとよい。

---

## 3. チャンクが短すぎて翻訳に失敗

### 3.1 発見・修正済みの重大バグ: セグメントの二重カウント

`experiments/results.csv` の2026-07-24〜07-31の一連の実験(`calibration_check` → `calibration_check2` → `calibration_baseline_no_packs` → `calibration_drift_fix` → `calibration_rpm60` → `post_dedup_fix_check`)から再構成した経緯:

1. 同一の2分間ウィンドウ(900–1020秒)で、セグメント数が**40〜43**と異常に多いことに気づく(実際の発話密度からすると多すぎる)。
2. まずGemini呼び出しのレート制限(`GEMINI_RPM_LIMIT`が9のまま)によるバックログを疑い、60に引き上げ→レイテンシは改善(avg 33.94s→4.14s)したが、セグメント数自体は変わらず(40→43)。
3. 最終的に**「無音待ち(soft-finalize)で確定した断片が、それぞれ別々のセグメントとしてログされていた」**ことが判明。実際の発話単位としては連続している文が、システム内部では細切れに複数回カウントされていた。
4. 「utterance-continuity fix(coalesced batching、順序保証、呼び出しをまたいだ蓄積)」を実装し、同じ2分間ウィンドウで検証(`post_dedup_fix_check`) → セグメント数は**21**に減少(元の約半分)。

**このレポートの文脈での意味**: 元々の`sweep_endpointing.sh`によるendpointing 300–1500msのsweep実験(`20260415_ep_sweep_*ms.json`、初版で報告)は、**このバグが修正される前のデータ**である。つまり、あのsweepで観測されたセグメント数のばらつき(同一条件でも2〜7個と大きく変動)は、endpointingそのものの効果というより、この二重カウントバグのノイズを相当程度含んでいた可能性が高い。**旧sweepの数値は参考程度に留め、鵜呑みにすべきではない。**

### 3.2 「リアルタイム翻訳に向いているモデル」調査(issue 3のサブ項目)

`experiments/model_comparison/COMPARISON_REPORT.md`(2026-07-24更新版)に、実際のDeepgram誤り込みの122セグメントを5モデル(`gpt-5.4-mini`, `gpt-5.4-nano`, `gemini-3.5-flash-lite`, `gpt-5.6-luna`, `gemini-3.6-flash`)へ通した実測比較がある:

| モデル | avg TTFT | ASR誤りの自己修正 | 総合評価 |
| --- | --- | --- | --- |
| `gpt-5.4-mini` | 0.56s(最速) | "KV catch"→"KV cache"を直せず | 速いが用語自己修正に穴 |
| `gemini-3.5-flash-lite` | 0.95s | 全スポットチェックで正解 | **速度・コスト・精度のバランスで推奨** |
| `gpt-5.6-luna` | 1.37s | 全スポットチェックで正解 | 精度は良いがコスト高め |
| `gpt-5.4-nano` | 0.68s | "country"を能動的に誤訳(国と訳す) | 最安だが積極的な誤訳リスク |
| `gemini-3.6-flash` | 2.70s(最遅) | — | `thinking`を完全に無効化できず遅い。現行差し替え候補としては非推奨 |

さらに `gemini-3.5-live-translate-preview`(ASR+翻訳を1パスで行うモデル)も実測されており、内部応答は速い(reaction latency avg 0.25s)がDeepgramにはない新種の誤り("Gemini's development"→"gymnast development"等)も確認されている。

推奨: **`gemini-3.5-flash-lite`**(現行の`gemini-3.1-flash-lite`と同系統への「まず差し替えてみる」候補として最有力、との結論が既に出ている)。

### 3.3 追加実験: 重複バグ修正後の正式なチャンク長sweep(実施結果)

`video/LLM2024_8_part1.mp4`は`.gitignore`対象でこの環境には存在しなかった(§4参照)ため、代わりに`wjZofJX0v4M`(5:00〜5:30、90秒、`real-time-translation-exp-video`、重複バグ修正後の現行コード)でendpointing 300/500/800/1200/1500/2000msを振った。

**1回目の実行は無効**: `GEMINI_RPM_LIMIT`を明示的に設定し忘れ、`.env`に値がなくデフォルトの`9`のままだった。これは§3.1でこのプロジェクト自身が発見・修正した「低RPMによるバックログ」バグを、そのまま自分で再現してしまった格好になる(avg end-to-end latency 7〜19秒、max latency最大48秒 — 現行の75分フル動画実績値avg 3.84秒と比べて明らかに異常)。`GEMINI_RPM_LIMIT=60`を設定して再実行し、そちらを正式な結果として採用する。

| endpointing | セグメント数 | avg confidence | avg end-to-end latency | max latency | avg words/segment |
| --- | --- | --- | --- | --- | --- |
| 300ms | 16 | 0.9991 | 7.08s | 12.07s | 11.6 |
| 500ms | 12 | 0.9994 | 6.81s | 9.88s | 10.6 |
| 800ms | 13 | 0.9994 | 7.01s | 9.85s | 10.6 |
| 1200ms | 13 | 0.9994 | 7.08s | 10.08s | 10.6 |
| 1500ms | 13 | 0.9994 | 6.92s | 9.72s | 10.6 |
| 2000ms | 13 | 0.9994 | 6.83s | 9.81s | 10.6 |

**結果**: RPM修正後は6条件ともレイテンシがavg 6.8〜7.1秒・max 9.7〜12.1秒とほぼ横並びで安定しており、endpointingを300msから2000msまで振っても、セグメント数・confidence・レイテンシのいずれにも一貫した傾向(単調増加/減少)が見られなかった。これは初版で報告した旧`ep_sweep_*ms`(セグメント数が2〜7個と大きく揺れていた)とは対照的に、**バグ修正後は実際にendpointingの効果そのものが小さい**ことを示す一次データである。

**解釈**: 3Blue1Brownのようなよどみなく話し続けるナレーションでは、そもそも300ms以上の無音区間がほぼ発生せず、無音待ち(`endpointing`)より`deepgram_max_interim_duration`(ソフトファイナライズのタイムアウト、既定2.5秒、`tuned_2_5s_window`実験で調整されたパラメータ)の方が実際のチャンク長を支配している可能性が高い。つまり「チャンクの長さと字幕表示速度のトレードオフ」を検証するなら、`endpointing`単体よりも**`deepgram_max_interim_duration`を振るsweep**の方が効果を捉えやすい可能性がある。これは当初のメモにあった「少しずつ長くしていく」検証がまだ本当の意味では終わっていないことを意味する — 次にやるならこのパラメータを対象にすべき。

**質的確認**: 全条件で文の途中の不自然な切断は見られず、"I'm glossing over some details about some normalization steps..."のような完全な文単位でセグメントが確定していた(§3.1の重複バグ修正が効いていることの追加的な裏付け)。

### 3.4 メモにあった追加アイデアの現状

- **直前の英語文脈を入れる**: 実装済み(`context_window_size`)。system prompt側でもASR誤りの文脈的訂正に使うよう明記されている。
- **不自然度を出力させてチャンクを伸ばす**: 依然未実装。§3.1の「utterance-continuity fix」は関連はするが、これは事後的な断片の再結合(バグ修正)であり、"不自然度スコアに基づいて次の確定を待つ"という提案自体とは別物。今回のリファクタ(`pipeline.py`の485行変更)の中身までは未確認のため、もし関連ロジックが入っていれば要再確認。

---

## 4. 現状のステータスと次のアクション

| 項目 | 状態 |
| --- | --- |
| `.env`のAPIキー | ✅ 設定済み(本セッションで確認) |
| 事前抽出辞書の仕組み・効果検証 | ✅ 実装・大規模実験とも完了 |
| ASR誤聴のground truth分析 | ✅ 完了(最難区間のみ) |
| チャンク重複バグ | ✅ 発見・修正・検証済み |
| リアルタイム翻訳向きモデル比較 | ✅ 完了、推奨モデルあり |
| 修正後の正式なchunk長sweep | ✅ 実施済み(§3.3)。endpointing自体の効果は小さいという結果 |
| Keyterm PromptingがASR誤聴自体を減らす効果の直接測定 | ✅ 実施済み(§2.2)、ただしテスト区間の難易度が低くnull結果。**難しい区間での再検証が次の課題** |
| `deepgram_max_interim_duration`のsweep | ❌ **未実施**(§3.3で新たに浮上した仮説) |
| `video/LLM2024_8_part1.mp4`本体 | ⚠️ `.gitignore`対象でこの作業環境には存在しない。今回の追加実験は代わりに`wjZofJX0v4M`で実施(§4.1) |

### 4.1 なぜ元の動画(`video/LLM2024_8_part1.mp4`)で追加実験できなかったか

`.gitignore`で`/video/*.mp4`と`experiments/clips/*.mp4`が除外対象になっており、この環境には動画本体(元動画・`hardest_5min`クリップとも)が存在しない。ソースURLもリポジトリ内に記録がなく、こちらで推測して取得することは避けた。そのため§2.2・§3.3の追加実験は、初版セッションで既にダウンロード済みだった`wjZofJX0v4M`(3Blue1Brown, パブリックなYouTube動画)で代替実施した。同一動画での追試ではないため、§3.1・§3.2・既存のhardest_5minベンチマークとの直接比較はできない点に注意。`video/LLM2024_8_part1.mp4`本体がある環境(元の実験を行った人の手元)で同じ実験(`experiments/refs/run_chunk_latency_sweep.sh` / `run_keyterm_asr_effect.sh`の`--input`を差し替えるだけ)を再実行すれば、直接比較可能な結果が得られる。

次に着手するなら、①`deepgram_max_interim_duration`のsweep(§3.3で浮上した新しい仮説の検証)、②keyterm効果の検証を実際に誤聴が起きている区間(hardest_5min相当)でやり直すこと、の2つが最も価値の高い残タスク。

## 付録: 追加実験で使用したスクリプト・素材(3Blue1Brown "Transformers"動画)

`experiments/refs/`に格納:
- `wjZofJX0v4M.en.vtt` / `.ja.vtt`, `wjZofJX0v4M_5_15_en.txt` / `_ja.txt` — 人手キャプション(全編・5:00-15:00区間抽出)
- `audio/wjZofJX0v4M.webm` — ローカル音声ファイル(`real-time-translation-exp-video`用、gitignore対象のため未コミット)
- `curated_dictionary_transformers.csv` — この動画用のキュレーション辞書(28語)
- `extract_vtt_range.py` — VTT区間抽出スクリプト
- `run_chunk_latency_sweep.sh` — §3.3のendpointing sweepスクリプト(`--input`を差し替えて再利用可能)
- `run_keyterm_asr_effect.sh` — §2.2のkeyterm ON/OFF比較スクリプト(同上)
- `asr_only_run.py` — 翻訳を経由しないDeepgram単体実行スクリプト(YouTube URL直接指定、未使用に終わったが再利用可)
