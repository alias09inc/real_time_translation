"""Compare two video_segment.py experiment runs (with vs. without a
domain-pack dictionary active) on a fair, common footing.

Each run's own `glossary_adherence_rate` (in its experiment JSON) is scored
against whatever dictionary was loaded *for that run*, so the two numbers
aren't directly comparable -- the with-dictionary run's dictionary has more
terms to hit in the first place. This script instead scores both runs'
translation output against the same fixed reference glossary (the
video-extracted session dictionary), so the only thing that differs between
the two scores is translation quality, not the yardstick.

Usage:
  uv run real-time-translation-exp-compare-dictionary \
      --with-dict experiments/20260724_llm2024_8_part1_full.json \
      --without-dict experiments/20260724_llm2024_8_part1_full_baseline_no_dict.json \
      --reference dictionaries/sessions/LLM2024_8_part1.csv
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from real_time_translation.experiments.glossary_metrics import (
    compute_glossary_adherence,
)
from real_time_translation.translation.dictionary import TermDictionary


def _load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _closest_segment(segments: list[dict], start_time: float) -> dict | None:
    if not segments:
        return None
    return min(segments, key=lambda s: abs((s["asr_start_time"] or 0) - start_time))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--with-dict", type=Path, required=True)
    parser.add_argument("--without-dict", type=Path, required=True)
    parser.add_argument("--reference", type=Path, required=True)
    parser.add_argument(
        "--out", type=Path, default=None, help="Optional path to write a JSON report"
    )
    args = parser.parse_args()

    reference = TermDictionary()
    reference.load_csv(args.reference)

    with_data = _load(args.with_dict)
    without_data = _load(args.without_dict)

    report: dict = {"reference_glossary": str(args.reference), "runs": {}}

    for label, data, path in (
        ("with_dictionary", with_data, args.with_dict),
        ("without_dictionary", without_data, args.without_dict),
    ):
        r = data["results"]
        full_asr = r["full_asr"]
        full_translation = r["full_translation"]
        glossary = compute_glossary_adherence(
            reference, source_text=full_asr, hypothesis_text=full_translation
        )
        report["runs"][label] = {
            "json_path": str(path),
            "segment_count": r["segment_count"],
            "avg_confidence": r["avg_confidence"],
            "avg_end_to_end_latency_seconds": r.get("avg_end_to_end_latency_seconds"),
            "max_end_to_end_latency_seconds": r.get("max_end_to_end_latency_seconds"),
            "reference_glossary_expected_terms": glossary.expected_terms,
            "reference_glossary_matched_terms": glossary.matched_terms,
            "reference_glossary_adherence_rate": glossary.rate,
            "reference_glossary_missed_terms": glossary.missed_terms,
        }

    with_missed = set(
        report["runs"]["with_dictionary"]["reference_glossary_missed_terms"]
    )
    without_missed = set(
        report["runs"]["without_dictionary"]["reference_glossary_missed_terms"]
    )
    only_missed_without = sorted(without_missed - with_missed)
    only_missed_with = sorted(with_missed - without_missed)
    report["comparison"] = {
        "terms_fixed_by_dictionary": only_missed_without,
        "terms_broken_by_dictionary": only_missed_with,
    }

    print(json.dumps(report, ensure_ascii=False, indent=2))

    if args.out:
        args.out.write_text(
            json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        print(f"\nWrote: {args.out}")

    # Qualitative: for each term the dictionary fixed, pull the matching
    # segment from both runs (nearest by asr_start_time) so the effect can
    # be inspected directly, not just inferred from the aggregate rate.
    if only_missed_without:
        print("\n=== Qualitative examples: terms only correct WITH the dictionary ===")
        with_segments = with_data["results"]["segments"]
        without_segments = without_data["results"]["segments"]
        for term in only_missed_without[:15]:
            for seg in with_segments:
                if term.lower() in seg["asr"].lower():
                    other = _closest_segment(without_segments, seg["asr_start_time"])
                    print(f"\nTerm: {term!r} (asr_start={seg['asr_start_time']:.0f}s)")
                    print(f"  ASR:              {seg['asr']}")
                    print(f"  WITH dictionary:  {seg['translation']}")
                    if other:
                        print(f"  WITHOUT dict:     {other['translation']}")
                    break


if __name__ == "__main__":
    main()
