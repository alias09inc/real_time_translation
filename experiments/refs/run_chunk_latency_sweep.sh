#!/bin/bash
set -e
export PATH="/opt/homebrew/bin:$PATH"
cd "$(dirname "$0")/../.."

AUDIO_PATH="${1:-experiments/refs/audio/wjZofJX0v4M.webm}"

for t in 300 500 800 1200 1500 2000; do
  echo "=== endpointing=${t}ms ==="
  DICTIONARY_PATH="experiments/refs/curated_dictionary_transformers.csv" \
  GEMINI_RPM_LIMIT=60 \
  uv run real-time-translation-exp-video \
    --input "$AUDIO_PATH" \
    --start 300 --duration 90 \
    --name "chunk_latency_sweep2_${t}ms" \
    --domain ml_transformers \
    --speed 1.0 \
    --endpointing "$t" \
    --notes "Post-dedup-fix chunk-length/endpointing sweep with honest (speed=1.0) latency measurement. wjZofJX0v4M 5:00-6:30, curated glossary active."
done

echo "SWEEP_DONE"
