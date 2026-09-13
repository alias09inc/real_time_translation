#!/bin/bash
set -e
export PATH="/opt/homebrew/bin:$PATH"
cd "$(dirname "$0")/../.."

AUDIO_PATH="${1:-experiments/refs/audio/wjZofJX0v4M.webm}"

echo "=== WITH Deepgram keyterms (curated glossary) ==="
DICTIONARY_PATH="experiments/refs/curated_dictionary_transformers.csv" \
DEEPGRAM_KEYTERMS_ENABLED=true \
GEMINI_RPM_LIMIT=60 \
uv run real-time-translation-exp-video \
  --input "$AUDIO_PATH" \
  --start 300 --duration 240 \
  --name "asr_keyterms_on3" \
  --domain ml_transformers \
  --speed 1.5 \
  --reference-ja experiments/refs/wjZofJX0v4M_5_15_ja.txt \
  --notes "Isolates Deepgram Keyterm Prompting's effect on ASR itself (not just translation-side dictionary). Curated 27-term glossary passed as Deepgram keyterms. wjZofJX0v4M 5:00-15:00, matches experiments/refs/wjZofJX0v4M_5_15_en.txt ground truth for WER comparison."

echo "=== WITHOUT Deepgram keyterms (same dictionary still active for translation) ==="
DICTIONARY_PATH="experiments/refs/curated_dictionary_transformers.csv" \
DEEPGRAM_KEYTERMS_ENABLED=false \
GEMINI_RPM_LIMIT=60 \
uv run real-time-translation-exp-video \
  --input "$AUDIO_PATH" \
  --start 300 --duration 240 \
  --name "asr_keyterms_off3" \
  --domain ml_transformers \
  --speed 1.5 \
  --reference-ja experiments/refs/wjZofJX0v4M_5_15_ja.txt \
  --notes "Same segment/dictionary as asr_keyterms_on, but DEEPGRAM_KEYTERMS_ENABLED=false so Deepgram gets no keyterm hints (translation-side dictionary lookup still active identically in both runs -- only the ASR-level hint differs). wjZofJX0v4M 5:00-15:00."

echo "KEYTERM_EFFECT_DONE"
