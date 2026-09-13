"""Find the hardest sliding window of a video_segment.py experiment run.

"Hardest" = lowest average ASR confidence over a fixed-length window,
tie-broken by count of low-confidence segments. Confidence is Deepgram's
own per-segment score, already recorded in the experiment JSON -- this is
a cheap, no-new-API-calls way to locate candidate benchmark clips before
spending anything on a careful ground-truth pass over them.

Usage:
  uv run real-time-translation-exp-find-hardest \
      experiments/20260724_llm2024_8_part1_full.json --window 50
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path


def find_hardest_window(
    segments: list[dict], window_seconds: float, *, min_density: float = 0.6
) -> tuple[float, float, float, int]:
    """Slide a window across segments (anchored at each segment's start)
    and return (window_start, window_end, avg_confidence, segment_count)
    for the window with the lowest average confidence.

    `min_density` rejects sparse windows (e.g. near the very end of the
    video, where a window has few segments purely because there isn't
    `window_seconds` of content left) -- otherwise those show up as
    spuriously "hardest" from small-sample variance, not genuine
    difficulty. Windows must have at least `min_density` times the
    video's overall average segment density to be eligible.
    """
    starts = sorted(
        s["asr_start_time"] for s in segments if s["asr_start_time"] is not None
    )
    if not starts:
        raise RuntimeError("No segments with a start time found")

    total_span = starts[-1] - starts[0]
    overall_density = len(starts) / total_span if total_span > 0 else 0.0
    min_segment_count = max(1, int(min_density * overall_density * window_seconds))

    best: tuple[float, float, float, int] | None = None
    for anchor in starts:
        window = [
            s
            for s in segments
            if s["asr_start_time"] is not None
            and anchor <= s["asr_start_time"] < anchor + window_seconds
        ]
        if len(window) < min_segment_count:
            continue
        avg_conf = sum(s["confidence"] for s in window) / len(window)
        candidate = (anchor, anchor + window_seconds, avg_conf, len(window))
        if best is None or avg_conf < best[2]:
            best = candidate

    if best is None:
        raise RuntimeError(
            f"No window met the minimum segment density "
            f"({min_segment_count} segments per {window_seconds}s window)"
        )
    return best


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("experiment", type=Path)
    parser.add_argument(
        "--window", type=float, required=True, help="Window size, seconds"
    )
    parser.add_argument(
        "--exclude-before",
        type=float,
        default=0.0,
        help="Ignore windows starting before this",
    )
    args = parser.parse_args()

    data = json.loads(args.experiment.read_text(encoding="utf-8"))
    segments = data["results"]["segments"]
    if args.exclude_before:
        segments = [
            s
            for s in segments
            if s["asr_start_time"] is not None
            and s["asr_start_time"] >= args.exclude_before
        ]

    start, end, avg_conf, count = find_hardest_window(segments, args.window)
    print(f"window: {start:.1f}s - {end:.1f}s ({args.window}s)")
    print(f"avg_confidence: {avg_conf:.4f}")
    print(f"segment_count: {count}")
    print()
    for s in segments:
        if s["asr_start_time"] is not None and start <= s["asr_start_time"] < end:
            print(
                f"  [{s['asr_start_time']:.1f}s] conf={s['confidence']:.3f}  {s['asr']}"
            )


if __name__ == "__main__":
    main()
