# Model comparison report — 2026-07-24 (updated after OpenAI fix)

Tested against the hardest 5-minute clip (`experiments/clips/hardest_5min_64m07-69m07.mp4`,
and its nested 50s sub-clip) identified earlier: a live Q&A answer with
non-native English, heavy disfluency, and dense ML jargon.

## Status up front

**All 5 LLM translation candidates now tested with real data.** The initial
OpenAI failures were three separate bugs, not a billing issue as first
suspected — see "OpenAI pipeline fixes" below. `gpt-realtime-whisper`
remains untested (out of scope for this pass; the fixes below unblock it
too, just not yet run).

---

## Part 1: Translation models

Methodology: replayed the actual 122 real Deepgram ASR segments from the
hardest window through the real `LLMTranslator` class (same dictionary,
same context window) for each candidate model, sequentially. Raw output
for your own inspection: `experiments/model_comparison/<model>.json`;
side-by-side jargon spot-check: `experiments/model_comparison/quality_spotcheck.txt`.

| Model | Avg TTFT | Max TTFT | Total (122 segs) | Errors |
|---|---|---|---|---|
| **`gpt-5.4-mini`** | **0.56s** | 2.01s | 80.3s | 0 |
| `gpt-5.4-nano` | 0.68s | 2.68s | 100.3s | 0 |
| `gemini-3.5-flash-lite` | 0.95s | 1.31s | 123.7s | 1 transient 503 |
| `gpt-5.6-luna` | 1.37s | 5.43s | 179.3s | 0 (self-healed 1 param-rejection retry) |
| `gemini-3.6-flash` | 2.70s | 4.10s | 332.9s | 1 transient 503 |

`gpt-5.4-mini` is the fastest of all five candidates tested — faster even
than the currently-deployed `gemini-3.1-flash-lite` (~0.73-0.89s TTFT
measured earlier this session).

### OpenAI pipeline fixes (this is why it failed before)

Three separate, unrelated bugs, all now fixed in the codebase:

1. **`config.py`** — `load_dotenv()` doesn't override a same-named variable
   already set in the shell/OS environment. A stale `OPENAI_API_KEY` was
   sitting in the shell (unrelated to this project), completely different
   from the one in `.env`, and silently won every time. Fixed:
   `load_dotenv(override=True)`.
2. **The `.env` key itself** was 163 characters instead of the correct 164
   (a truncated copy-paste) — user-fixed.
3. **Two real API-compatibility bugs**, only surfaced once auth succeeded:
   - `max_tokens` → `max_completion_tokens` (newer OpenAI models reject the
     old parameter name entirely). Fixed in both `llm_translator.py` and
     `preload/term_extractor.py`.
   - `gpt-5.6-luna` specifically rejects any non-default `temperature`
     (400). Fixed with a self-healing retry in `_translate_openai_stream`:
     catches the specific error, retries once without `temperature`, and
     remembers for the rest of that translator's session — consistent with
     the adaptive-backoff pattern already used for Deepgram's keyterm
     token-budget limit, rather than a hardcoded per-model exception list
     that goes stale the next time a model ships with a new quirk.

### Critical practical finding: `gemini-3.6-flash` cannot fully disable "thinking"

Unlike the currently-deployed `gemini-3.1-flash-lite`, both `gemini-3.6-flash`
*and* `gemini-3.5-flash-lite` **reject an explicit `thinking_budget=0`**
(400 INVALID_ARGUMENT) — the parameter has to be omitted entirely instead.
Even with it omitted, `gemini-3.6-flash` still spends ~150-200 tokens/call
on mandatory internal reasoning before producing visible output, which is
almost certainly why its TTFT (2.70s avg) is the slowest of all five
candidates and well above this project's <3s "green" latency target on its
own, before Deepgram latency is even added. For a real-time captioning use
case, **`gemini-3.6-flash` is very likely not viable as-is** despite being
the newer/more capable model.

### Quality observations (see `quality_spotcheck.txt` for full data)

All five models translate straightforward jargon correctly and fluently.
The differences show up specifically in how each one handles **ASR errors
already baked into the source text** (these are real Deepgram outputs
being replayed, including its actual errors):

- **"KV catch" → should become "KV cache"**: `gpt-5.6-luna`,
  `gemini-3.6-flash`, and `gemini-3.5-flash-lite` all correctly
  self-corrected it. **`gpt-5.4-mini` and `gpt-5.4-nano` did not** — both
  propagated "KV catch" verbatim into the Japanese output
  (`KV catch に関しても`), a real, visible defect a viewer would notice.
  This is a genuine quality gap for the two fastest/cheapest OpenAI models
  specifically.
- **"quantization, country, we have vector quantization" (should be
  "currently")**: `gpt-5.6-luna`, both Gemini models gracefully dropped the
  garbled word and produced a clean sentence. `gpt-5.4-mini` gave up and
  left "country" and "vector quantization" untranslated in Roman letters
  mid-sentence. `gpt-5.4-nano` is the worst case here — it didn't just fail
  to fix the error, it **actively mistranslated** "country" into 国 (the
  literal Japanese word for "nation/country"), producing a confidently
  wrong sentence rather than an obviously garbled one.
- **Terminology consistency for "hallucination"**: Gemini models
  consistently used the katakana loanword ハルシネーション, matching actual
  Japanese ML-community usage. OpenAI models were inconsistent, mixing
  ハルシネーション and the more literal/clinical 幻覚 depending on the
  specific call.
- `gemini-3.6-flash`'s one dropped segment (transient 503, not a quality
  failure) is itself a useful data point: this project's existing
  `_translation_worker` retry logic only retries on `TimeoutError`, not
  generic server errors — a 503 mid-session gets silently dropped in
  production today, for any model.

**Net read**: `gpt-5.4-mini` is fastest but has a real terminology
self-correction gap. `gpt-5.6-luna` and `gemini-3.5-flash-lite` both
handled every tricky case correctly in this spot-check, at roughly 1s and
comparable cost tiers respectively — either is a more defensible choice
than raw speed alone would suggest. `gpt-5.4-nano`'s active mistranslation
behavior (vs. gracefully dropping/preserving an error) is a meaningfully
different failure mode worth weighing against its low price.

---

## Part 2: ASR / speech-to-text APIs

### Deepgram (current production baseline)

Full real data already exists from the 75-minute validation run + hardest-5min
analysis: avg confidence 0.946 (whole video) / 0.918 (hardest window), avg
end-to-end latency 3.84s across the full 75-min run. Recall the important
caveat already found: **Deepgram's own confidence score doesn't reliably
flag actual errors** — 6 of 8 confirmed errors in the hardest window were
made at ≥0.93 confidence (see `hardest_5min_BENCHMARK_README.md`).

### Gemini Live Translate API (`gemini-3.5-live-translate-preview`)

Genuinely tested with a real bidirectional streaming session (not a batch
substitute) — audio sent in real-time-paced 100ms chunks, both input
transcription and Japanese output translation captured live. This model
is architecturally different from the current pipeline: **it does ASR and
translation in a single pass**, potentially collapsing Deepgram+Gemini into
one call.

Raw results: `experiments/clips/gemini_live_translate_50s_readable.txt`
(50s) and `experiments/clips/gemini_live_translate_5min_readable.txt` (full
5min, 588 events); concatenated transcript/translation text also saved
separately for easy reading.

- **Reaction latency** (input-transcript-event → next output-translation-event,
  292 paired events across the 5-min clip): avg **0.25s**, max 0.44s. Caveat:
  this measures the gap *within* the live session, not true audio-spoken-to-
  caption-displayed latency (no clean way to measure that from this test) —
  so it's not directly comparable to the Deepgram pipeline's 3.84s
  end-to-end figure, but it's a strong signal the internal turnaround is fast.
- **Transcription quality vs. Deepgram**: mixed, not a clean win either way.
  Correctly heard "KV cache" (all mentions, without the "catch" error) and
  "KV caching" — better than Deepgram there. But introduced *new* errors
  Deepgram didn't make: "Gemini's development" → **"gymnast development"**,
  "for LLM efficiency" → **"for Elon efficiency"**, and badly mangled "MoE is
  already sparsity, right?" into "**I'm already past it, right?**" (worse
  than Deepgram's "spotty" substitution, which at least kept the sentence
  structure recognizable). Also dropped a repeated "many" ("many, many,
  many talents" → "many, many talents").
  Both systems independently mis-heard "RL training throughput" as "IO
  training throughput" — worth treating as a genuinely hard/ambiguous
  moment in the audio rather than a system-specific weakness.
- **Practical note**: `translation_config=TranslationConfig(target_language_code="ja")`
  plus `input_audio_transcription`/`output_audio_transcription` on
  `LiveConnectConfig` is what makes this work — undocumented in this
  codebase since it's a brand-new integration; see the (now-deleted, but
  logic preserved in git history if needed) test scripts' pattern for
  `send_realtime_input(audio=Blob(...))` + concurrent `session.receive()`.

### GPT-Realtime-Whisper

Confirmed to exist (`gpt-realtime-whisper` in the model list) and the
account is now confirmed working (OpenAI models tested successfully above),
but this specific model hasn't been tested yet — it needs its own
streaming/session integration (different API shape than chat completions),
which wasn't built in this pass. Straightforward to add as a follow-up
using the same real-time-paced-audio pattern used for the Gemini Live test.

---

## Part 3: Cost & rate limits (researched, current as of 2026-07-24)

*Note: exact per-model RPM/TPM tables for the newest OpenAI models
(GPT-5.6/5.4 family) aren't publicly published — OpenAI directs developers
to the account Limits page / response headers instead. Figures below
marked "not confirmed per-model" are general tier extrapolations, not
verified for these specific models.*

| Model | Price (per 1M tokens, standard tier) | Context | Rate limits |
|---|---|---|---|
| `gpt-5.6-luna` | $1.00 in / $6.00 out (Batch $0.50/$3.00; Priority $2/$12) | 1.05M in / 128K out | Not published per-model; check account Limits page |
| `gpt-5.4-mini` | $0.75 / $4.50 | 400K in / 128K out | Not confirmed per-model |
| `gpt-5.4-nano` | $0.20 / $1.25 (cheapest current OpenAI model) | 400K in / 128K out | Not confirmed per-model |
| `gemini-3.6-flash` | $1.50 / $7.50 (Batch $0.75/$3.75) | 1M+ (exact figure not confirmed) | Free tier exists; paid ~150-300 RPM (Tier 1) up to 4,000+ RPM (enterprise) — general Gemini tier figures, not 3.6-specific |
| `gemini-3.5-flash-lite` | $0.30 / $2.50 (Batch $0.15/$1.25) — ~5x/3x cheaper than 3.6 Flash | 1M+ | Free tier ~15 RPM (one source, not independently confirmed) |

| Speech API | Price | Concurrency | Latency |
|---|---|---|---|
| Deepgram Nova-3 | $0.0048/min mono, $0.0058/min multilingual (streaming PAYG) | 150 concurrent streams (PAYG); up to 225-300 on higher plans | — |
| Deepgram Flux | $0.0065/min English, $0.0078/min multilingual | Same tiers; needs manual `flux.max_streams` tuning | Sub-300ms end-of-turn |
| Gemini Live API | $3/1M audio-input tokens, $12/1M audio-output tokens (≈$0.005/min in, $0.018/min out) | 1,000 concurrent sessions/project (Vertex); Gemini Developer API limits vary by tier | Session capped ~10-15 min (audio-only), 128K context |
| GPT-Realtime-Whisper | $0.017/min (2.8x plain `whisper-1`) | Tiered: 100 min-of-audio/min (Tier 1) up to 1,300 min/min (Tier 5); **no free tier** | 16K context, "very fast" per OpenAI, no published number |

**Practical read, updated**: no single model wins cleanly.
`gpt-5.4-mini` is fastest and mid-priced but has a real terminology
self-correction gap (missed "KV cache"). `gemini-3.5-flash-lite` is
cheapest-per-token among the strong performers, ~1s TTFT, and got every
spot-checked correction right. `gpt-5.6-luna` also got every correction
right but costs more and runs slower than either. `gpt-5.4-nano` is
cheapest overall but showed the only *active mistranslation* (vs.
graceful degradation) in this test, which matters more than raw price for
a captioning product people are trusting to be accurate. `gemini-3.6-flash`
is hard to justify: 5x `gemini-3.5-flash-lite`'s input price and ~3x
its latency, with no quality edge shown here.

If forced to pick one drop-in candidate today: **`gemini-3.5-flash-lite`**
— best combination of speed, cost, and terminology accuracy shown in this
test, and closest to a like-for-like swap with the current production
model (`gemini-3.1-flash-lite`, same family). Worth a longer/full-session
validation run before committing, the same way the current model got one.

---

## Files for your own inspection

- `experiments/model_comparison/{model}.json` — full per-segment translation output, per model (all 5 now populated)
- `experiments/model_comparison/quality_spotcheck.txt` — side-by-side jargon-segment comparison, all 5 models
- `experiments/model_comparison/summary.json` — latency/error summary, machine-readable
- `experiments/clips/gemini_live_translate_5min_readable.txt` — full Gemini Live session transcript+translation, chronological
- `experiments/clips/gemini_live_translate_5min_full_input.txt` / `..._full_output.txt` — concatenated text
- `real-time-translation-exp-compare-models` (`src/real_time_translation/experiments/compare_translation_models.py`) — rerunnable, e.g. `--only gpt-realtime-whisper` once that integration exists
