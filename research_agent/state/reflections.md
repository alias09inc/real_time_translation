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
