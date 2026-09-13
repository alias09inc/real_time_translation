# Benchmark clips: hardest region of LLM2024_8_part1.mp4

Identified via `real-time-translation-exp-find-hardest` (`src/real_time_translation/experiments/find_hardest_segment.py`) as the lowest-average-ASR-confidence
window of the full 75-minute run ([20260724_llm2024_8_part1_full.json](../20260724_llm2024_8_part1_full.json)).
It's a live Q&A answer segment: non-native/accented English, heavy disfluency
("many many many", "how how how"), and dense ML jargon (MoE, quantization,
KV cache, sparsity, distillation, hallucination).

## Files

- `hardest_5min_64m07-69m07.mp4` — 5-minute clip, original video timestamp 3846.9s–4146.9s (64:07–69:07), avg ASR confidence 0.918 (video-wide avg was 0.946)
- `hardest_50s_68m13-69m03.mp4` — 50-second clip, original video timestamp 4092.6s–4142.6s (68:13–69:03). **Nested inside the 5-min clip**, at relative offset [04:05.7]–[04:55.7] — the quantization/KV-cache/throughput passage at the end of the transcript below.
- `hardest_5min_ground_truth.txt` — careful reference transcription (Gemini `gemini-3.1-pro-preview`, non-real-time, given the video+slides for context), with its own uncertain spots flagged inline
- `hardest_5min_deepgram_realtime.txt` — what the real-time pipeline (Deepgram, the system under test) actually transcribed for the same window, with its per-segment confidence scores, for direct diffing against the ground truth

## Confirmed real-time ASR errors (ground truth vs. Deepgram)

Cross-checked every jargon-adjacent divergence between the two transcripts.
**Deepgram's own confidence score does not reliably predict which of these
are wrong** — most of the worst errors were made at *high* confidence:

| Timestamp | Deepgram said | Ground truth | Deepgram confidence | Flagged low-conf by Deepgram? |
|---|---|---|---|---|
| 03:04 | "the **medicine** for your **launching** model" | "the right thing for your **language** model" | 0.999 | No |
| 03:09 | "**compatible**" | "**capable**" | 0.639 | Yes |
| 02:28–02:36 | "no knowledge about your data **site**... do any the data **site**" | "no knowledge about your data **set**... let it to **learn how to reasoning in** data **set**" | 0.997 / 0.932 | No |
| 03:50 | "MOE is already **spotty**" | "MoE is already **sparsity**" | 0.983 | No |
| 04:16 | "quantization, **country**, we have vector quantization" | "quantization, **currently** we have vector quantization" | 0.947 | No |
| 04:36–04:39 | "KV **catch**" (x2) | "KV **cache**" (x2) | 0.771 / 0.973 | Only the first, barely |
| 04:46 | "**IO** training throughput" | "**RL** training throughput" | 0.868 | No |
| 04:49 | "For **sewing**" | "For **serving**" | 0.953 | No |

**Takeaway**: 6 of 8 confirmed errors were made at ≥0.93 confidence. A
confidence-threshold-based review process (e.g. "flag anything under 0.8")
would catch "compatible" and maybe "KV catch," but would silently miss
"medicine," "spotty," "country," "data site," "IO," and "sewing" —
exactly the errors most likely to matter, since they're all
domain-terminology substitutions, not filler-word noise.

## Where even the careful (ground-truth) pass is uncertain

Only 2 spots in the full 5 minutes, both genuinely ambiguous even off the
real-time constraint:

- **[00:01]** "secret **source**" — speaker likely meant the idiom "secret **sauce**" but the pronunciation is ambiguous
- **[00:59]** "**anti your** intuition" (said 2x) — unclear pronunciation, likely means "**counter to your** intuition"

These are good candidates for a native-speaker manual check if you want a
fully authoritative reference — everything else in the ground truth is at
Gemini's stated confidence, not hedged.
