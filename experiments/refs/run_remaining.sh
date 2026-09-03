#!/bin/bash
set -e
export PATH="/opt/homebrew/bin:$PATH"
cd "$(dirname "$0")/../.."

echo "=== Curated dictionary run ==="
DICTIONARY_PATH="experiments/refs/curated_dictionary_transformers.csv" \
uv run real-time-translation-exp-youtube \
  --url "https://www.youtube.com/watch?v=wjZofJX0v4M" \
  --start 5:00 --end 15:00 \
  --name transformers_curated_dict \
  --domain ml_transformers \
  --speed 5.0 \
  --reference-ja experiments/refs/wjZofJX0v4M_5_15_ja.txt \
  --notes "Same segment as transformers_baseline_currentdict, but with a curated 27-term glossary built specifically for this video's vocabulary (transformer, GPT, embedding, softmax, etc.) instead of the shipped domain-mismatched dictionary.csv."

echo "=== Endpointing / chunk-length sweep (3 min segment) ==="
for t in 300 500 800 1200 1500 2000; do
  echo "--- endpointing=${t}ms ---"
  uv run real-time-translation-exp-youtube \
    --url "https://www.youtube.com/watch?v=wjZofJX0v4M" \
    --start 5:00 --end 8:00 \
    --name "chunk_sweep_${t}ms" \
    --domain ml_transformers \
    --speed 5.0 \
    --endpointing "$t" \
    --notes "Chunk-length/endpointing sweep, 3-min segment (5:00-8:00), current shipped dictionary."
done

echo "ALL_RUNS_DONE"
