# Research Agent Reflections (self-improvement log)

Append-only. One dated entry per pass through the REFLECT state. English
is fine here -- this is internal working memory for future sessions of
this same agent, not a human-facing report (see `research_agent/reports/`
for the Japanese human-facing reports).

---

## Cycle 1 (2026-09-08)

**What worked:** Picking a $0, retroactive-analysis hypothesis
(h-flicker-metric) first was the right call -- it needed no approval
back-and-forth, produced a genuinely new and interesting finding
(translation layer is stable, ASR-interim layer is not, ~0.20 NE), and
gave the next two queued hypotheses (masking, LocalAgreement) a concrete
baseline to beat instead of testing blind. Recommend future cycles keep
prioritizing $0/no-new-data hypotheses before spending any of the daily
budget, per PLAYBOOK's existing guidance -- this cycle confirms that
guidance was right, not just cautious.

**What didn't work / gaps:** The literature search this cycle was a single
WebSearch query, not a real EXTRACT_PAPERS pass -- the 3 new papers found
(AlignAtt4LLM, Google stability blog, NeMo@IWSLT2026) are still snippet-only
stubs in papers.json with empty key_findings. Next cycle's SEARCH_PAPERS/
EXTRACT_PAPERS should WebFetch AlignAtt4LLM (arXiv:2606.03967) properly
before finalizing the h-localagreement-asr-commit experiment design, since
that paper's commit rule may differ from plain LocalAgreement-2 in a way
that matters (it's decoder-only-LLM-specific, which is closer to this
repo's setup than the original whisper-streaming paper).

**Backlog calibration:** 3 hypotheses, 1 tested this cycle, 2 queued for
next -- reasonable, not over-ambitious. Don't add more until at least one
of the 2 queued ones is tested; PLAYBOOK's "prefer depth over breadth,
cap backlog at ~6" rule is fine as-is, no change needed.

**Budget policy:** No spend yet ($0 of $7 daily cap used). Too early to
tell if $7/day is well-calibrated -- revisit after h-masking-holdback and
h-localagreement-asr-commit actually run (estimated $1.5 each). No
proposal to change it yet.

**Playbook changes made this cycle:** None needed -- the state machine and
approval flow worked as designed. One thing worth flagging for a human
(not changing unilaterally): the orchestrator.py note strings should avoid
`$` characters when passed through a shell (a note with a literal cost
figure got shell-mangled into a `/bin/zsh` path during this cycle's
HUMAN_APPROVAL transition -- harmless since it's just a free-text note
field, but worth using single-quoted heredocs or the --note flag with
plain text only, no `$0`-style placeholders, in future shell invocations).

---

## Cycle 2 (2026-09-08)

**What worked:** Extracting the 3 stubbed papers via WebSearch (since
WebFetch was EGRESS_BLOCKED for arxiv.org/research.google/aclanthology.org
in this sandbox) still produced substantive, specific findings, not
marketing fluff -- the AlignAtt4LLM read in particular caught a real
design error before any code was written: the original hypothesis draft
implicitly assumed AlignAtt4LLM's commit rule was LocalAgreement-style,
but it's actually attention-internals-based and inapplicable to an
API-only translator. Catching that during READ_PAPERS/GENERATE_HYPOTHESES
(cheap, no API spend) instead of after implementing and running an
AlignAtt-style experiment (expensive, and impossible anyway) validates
the playbook's ordering of literature-then-hypotheses.

**What didn't work / gaps:** Assumed "DEEPGRAM_API_KEY set" + "ffmpeg
installed" meant an experiment could actually run, and only discovered
otherwise after implementing the masking-holdback code and attempting a
live run -- the Deepgram websocket handshake failed with a 403 that
turned out to be the sandbox's network egress proxy rejecting
api.deepgram.com outright (org policy), while generativelanguage.
googleapis.com (Gemini) was fine. This should have been caught earlier
with a direct `curl` connectivity check instead of just checking whether
env vars were non-empty. Fixed the playbook itself (RUN_EXPERIMENTS
section now curls both API hosts directly) so a future session catches
this in the first orientation step instead of after writing code.

**Backlog calibration:** 4 hypotheses now (1 tested, 2 blocked-on-infra,
1 new $0.3 workaround). Still under the ~6 cap. The new
h-gemini-only-masking-replay hypothesis is deliberately scoped to route
around the newly-discovered Deepgram block rather than just waiting for
a human to fix the proxy -- felt like the right call given the playbook's
"never fabricate results, but don't just stall either" spirit. Next
cycle should actually implement it rather than adding yet more hypotheses
on top -- backlog depth over breadth still applies.

**Budget policy:** Still $0 spent (both real runs this cycle failed at
the Deepgram connection step, before any billable Deepgram audio was
sent; Gemini was never called since the pipeline never got past
`transcriber.connect()`). No proposal to change the budget policy --
haven't actually spent anything against it yet to have an opinion.

**Playbook changes made this cycle:**
1. RUN_EXPERIMENTS's environment check now curls both `api.deepgram.com`
   and `generativelanguage.googleapis.com` directly instead of only
   checking whether the env vars are non-empty, since a set key and a
   reachable API turned out to be two different things in this sandbox.
2. Noted that a missing `ffmpeg` is often fixable in-session via
   `apt-get install ffmpeg` (worked cleanly this cycle) rather than being
   an automatic hard blocker.
3. Updated 00_pipeline_overview_ja.md section 7 to reflect that
   hypothesis-required code changes (env-gated experimental toggles) are
   normal, and to document the asymmetric-egress-proxy gotcha for anyone
   reading the pipeline overview (not just PLAYBOOK.md).

Did not touch the approval-gate or budget-check steps themselves.

## Cycle 3 (2026-09-08, later session)

**What worked:** Verifying the environment fresh rather than trusting
cycle 2's blocked_reason at face value paid off -- the sandbox's network
state had genuinely changed (Deepgram REST reachable, ffmpeg installed
cleanly again) within the same day, across sessions. Re-checking instead
of assuming "still blocked" is the right default for anything
environment-dependent. Also good: reading `pipeline.py`'s
`_stream_batch`/`_translation_worker` in detail *before* writing
`replay_masking.py`, which surfaced that `flicker_metrics.py`'s
translation-NE grouping is per-batch, not per-utterance, and would not
have actually measured what h-masking-holdback is meant to fix
(cross-continuation retranslation drift). Stopping short of implementing
against a metric known to be wrong, instead of rushing a "looks done"
result, matches the playbook's "never fabricate results" spirit even
though this wasn't literally a fabrication risk -- it would have been a
*real* experiment measuring the *wrong thing* and reporting a false
negative, which is arguably worse because it looks legitimate.

**What didn't work / gaps:** Assumed a 200 on Deepgram's REST endpoint
meant streaming would work too -- wrong again, in a new way (cycle 2 was
REST+WS both blocked at the proxy CONNECT level; cycle 3 is REST fine,
WS-upgrade specifically 403). Two cycles in a row where an environment
check that looked sufficient turned out not to be. Fixed by adding an
actual WS-connect test to PLAYBOOK.md's RUN_EXPERIMENTS section this
cycle -- if a future session hits the same thing a third time, that's a
sign to look harder at *why* (proxy WS-upgrade policy vs. a Deepgram
key/plan scope difference) rather than just re-documenting the symptom
again. Separately, `uv sync`/`uv run` failing on an unrelated `zoom`
extra (testpypi's `rtms`, blocked by the proxy) cost real time to
diagnose -- worth having caught in cycle 1 or 2 already since experiments
never need that extra; documented the `uv pip install -e ".[experiments]"`
workaround now so it's a non-issue going forward.

**Backlog calibration:** Still 4 hypotheses, unchanged this cycle
(GENERATE_HYPOTHESES was correctly a no-op per the cycle-2 plan). Next
cycle's GENERATE_HYPOTHESES should consider adding a small, scoped
hypothesis for cross-utterance/cross-continuation translation NE
(diffing successive full-utterance retranslations directly, per the
note on h-gemini-only-masking-replay) -- this is arguably higher-value
than either blocked live-ASR hypothesis right now, since it's a $0
retroactive analysis (like h-flicker-metric was) that doesn't depend on
Deepgram at all and fixes a real gap in already-tested h-flicker-metric's
methodology.

**Budget policy:** Still $0 spent, three cycles running. No proposal to
change caps -- there's simply been no successful billable run yet to
have data-driven grounds to revisit them. Not concerning yet, but if
cycle 4 also fails to spend anything, worth flagging in the report to
the human as a "the auto-approved backlog has been stuck on
infra for three cycles" signal rather than silently repeating the same
loop.

**Playbook changes made this cycle:**
1. RUN_EXPERIMENTS's environment check now also tests the actual
   Deepgram listen-websocket directly (Python + `websockets`), not just
   the REST `/v1/projects` endpoint -- REST-reachable was proven
   insufficient evidence twice now.
2. Documented the `uv sync`/`uv run` all-extras-lock problem (pulls in
   the unreachable `zoom`/`rtms` testpypi dependency even for a plain
   experiment run) and the `uv pip install -e ".[experiments]"`
   workaround.
3. Updated `00_pipeline_overview_ja.md` section 7 with both of the above
   for the human-facing pipeline explainer.

Did not touch the approval-gate or budget-check steps themselves.

## Cycle 4 (2026-09-08, later session, scheduled/automated run)

**What worked:** Following through on cycle 3's own plan
(h-cross-utterance-flicker was flagged there as the recommended next
hypothesis) paid off immediately -- it needed no live API access at all,
so it was runnable regardless of whether the Deepgram infra blocker had
recurred this session (it wasn't even re-checked at the WS level this
cycle, deliberately, since it wasn't needed). The result was also a
genuine, non-trivial finding, not a null result: cross-batch translation
NE (~1.47 mean, 275 multi-batch spans out of 4471 total) is three to
four orders of magnitude higher than the within-batch figure
h-flicker-metric reported in cycle 1, and manual inspection of raw
events (the smoketest file) confirmed it's real -- successive batches
for the same utterance produce unrelated Japanese wording, not a shared
prefix. Also worked: sanity-checking a surprising aggregate number (NE >
1, which isn't intuitive) against the underlying raw event text before
writing it into the human-facing report, rather than trusting the
aggregate alone.

**What didn't work / gaps:** `uv run` still fails on the unrelated `zoom`
extra even after cycle 3 documented the workaround -- worth being more
precise next time: `uv pip install -e ".[experiments]"` avoids it at
*install* time, but `uv run <console-script>` re-triggers a sync anyway.
The actual fix used this cycle was calling
`python3 -m real_time_translation.experiments.flicker_metrics` directly
via the activated venv, bypassing `uv run` entirely for pure-analysis
scripts that need no live API access. Documenting this precisely in
PLAYBOOK.md now (see change #1 below) so a future session doesn't
rediscover the same "workaround didn't actually work" gap. Also: did not
re-verify the Deepgram Listen WebSocket or install ffmpeg this cycle,
since the chosen hypothesis needed neither -- that's a deliberate scope
choice, not an oversight, but it does mean cycle 5 starts with the
live-ASR environment status unknown again and should re-check before
picking among the three still-blocked hypotheses.

**Backlog calibration:** 5 queued/proposed hypotheses now (under the cap
of 6), one newly tested this cycle. This cycle's result also changes the
calculus for the backlog: h-masking-holdback and
h-localagreement-asr-commit are no longer just "blocked on infra" --
they now target a confirmed, sizeable problem (not a hypothetical one),
which raises their priority once Deepgram access is restored. Also
worth flagging: the survey-derived literature base (papers.json) has not
had a fresh WebSearch pass since cycle 1 (cycles 2-4 all reused or
skipped search, per each cycle's own REFLECT decision) -- three cycles
running now. That was a reasonable call each individual time (there was
always a clearer, more valuable non-search action available), but
"reasonable every time" can still add up to "the search step has quietly
atrophied." Recommending cycle 5 actually run a fresh SEARCH_PAPERS pass
(targeting: multi-batch/continuation retranslation stability policies
specifically, given this cycle's finding) rather than deferring again by
default.

**Budget policy:** Still $0 total spent, four cycles running, entirely
because every hypothesis actually executed so far has been a $0
retroactive analysis (by design -- PLAYBOOK.md prioritizes these) while
the three hypotheses that need real spend remain blocked on Deepgram
Listen-WebSocket access. This is worth surfacing to the human plainly
(also stated in this cycle's Japanese report): the auto-approval budget
policy itself has never actually been exercised end-to-end. No proposed
change to the caps themselves -- there's still no data suggesting they're
wrong, just no evidence yet that they're right either.

**Playbook changes made this cycle:**
1. Will document the `uv run` vs `python3 -m <module>` distinction for
   pure-analysis scripts (`uv run` still re-triggers the zoom-extra sync
   even inside an installed `.venv`; use `python3 -m
   real_time_translation.experiments.<script>` directly instead) --
   adding this to PLAYBOOK.md's RUN_EXPERIMENTS environment-setup note
   now.

**Next state:** Advancing to `SEARCH_PAPERS` (new cycle) rather than
`GENERATE_HYPOTHESES` directly, per the backlog-calibration note above --
it's been three cycles since the last real search and this cycle's
finding (large cross-batch retranslation drift) gives a concrete new
angle to search for (streaming MT continuation/re-translation stability
policies) rather than repeating the cycle-1 query blindly.
