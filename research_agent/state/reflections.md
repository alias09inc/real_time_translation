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
