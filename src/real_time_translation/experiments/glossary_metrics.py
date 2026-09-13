"""Glossary adherence scoring for domain-terminology translation quality.

chrF/BLEU score whole-sentence similarity, which is a poor proxy for the
thing this project actually differentiates on: did the specific technical
terms in `dictionary.csv` come out right? A single dropped "attention" ->
"注意" (should be "アテンション") barely moves chrF but is exactly the kind of
error that matters to a domain-expert listener.

This module scores that directly, requires no reference translation, and
runs against the system's own ASR output so it reflects what was actually
said in the segment, not the full dictionary.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from real_time_translation.translation.dictionary import TermDictionary, term_pattern


@dataclass(frozen=True)
class GlossaryAdherenceResult:
    """Result of scoring translation output against dictionary terms.

    `rate` is None (not 0.0) when no dictionary term was spoken in this
    segment, so callers/aggregators can distinguish "no terms to check"
    from "checked and failed".
    """

    expected_terms: int
    matched_terms: int
    rate: float | None
    missed_terms: list[str] = field(default_factory=list)


def compute_glossary_adherence(
    dictionary: TermDictionary,
    *,
    source_text: str,
    hypothesis_text: str,
) -> GlossaryAdherenceResult:
    """Score how many dictionary terms spoken in `source_text` made it into
    `hypothesis_text` with their designated translation.

    Args:
        dictionary: Loaded terminology dictionary (source_term -> target_term)
        source_text: Full ASR transcript for the segment (source language)
        hypothesis_text: Full system translation output for the segment

    Returns:
        GlossaryAdherenceResult with expected/matched counts and rate
    """
    expected = 0
    matched = 0
    missed: list[str] = []

    hypothesis_lower = hypothesis_text.lower()

    for entry in dictionary:
        if not term_pattern(entry.source_term).search(source_text):
            continue
        expected += 1
        if entry.target_term.lower() in hypothesis_lower:
            matched += 1
        else:
            missed.append(entry.source_term)

    rate = (matched / expected) if expected > 0 else None
    return GlossaryAdherenceResult(
        expected_terms=expected,
        matched_terms=matched,
        rate=rate,
        missed_terms=missed,
    )
