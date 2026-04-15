# Experiment Logging Rules

翻訳精度の比較実験を行ったら必ず以下を実行すること：

1. `experiments/YYYYMMDD_<実験名>.json` を作成
2. `experiments/results.csv` に1行追記（なければ新規作成）
3. `git add` してコミット

## Recommended Tooling

このリポジトリには、YouTubeの指定区間（例: 10:00–20:00）を入力として
Deepgram → LLM 翻訳のパイプラインを回し、**確定(=final)のASR + 翻訳**を
JSON/CSV に保存するランナーがあります。

### Install

```bash
uv sync --extra experiments
```

### Run (default: 10:00–20:00)

```bash
uv run real-time-translation-exp-youtube \
  --url "https://www.youtube.com/watch?v=JycsHP-sGmw" \
  --start 10:00 \
  --end 20:00 \
  --name youtube_10m_to_20m \
  --domain particle_physics
```

Outputs:
- `experiments/YYYYMMDD_<name>.json`
- `experiments/results.csv`

### Optional: chrF

参照訳（正解テキスト）を `--reference-ja` に渡すと、翻訳全体に対して chrF を計算します。

```bash
uv run real-time-translation-exp-youtube --reference-ja reference_ja.txt
```

## Notes

- `ffmpeg` がホストに必要です。
- YouTube等のコンテンツは、取り扱い権限/利用規約に従ってください。
