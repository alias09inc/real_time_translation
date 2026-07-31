"""Compare candidate LLM translation models on the real hardest-5min segments.

Reuses the actual production `LLMTranslator` class (same dictionary, same
context windowing, same system prompt construction) so this is a true
model-swap test, not a synthetic benchmark: each candidate model translates
the exact same 122 real Deepgram ASR segments from the hardest 5-minute
window of the full run, in the same order, building up the same kind of
running context a live session would.

Sequential and single-threaded per model (not the production 4-worker
pool) for reproducibility -- this measures each model's own per-call
latency honestly, without rate-limiter/worker-contention noise from the
comparison harness itself.

Usage:
  uv run real-time-translation-exp-compare-models \
      --experiment experiments/20260724_llm2024_8_part1_full.json \
      --window-start 3846.9 --window-end 4146.9 \
      --out-dir experiments/model_comparison
"""

from __future__ import annotations

import argparse
import asyncio
import json
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Literal

from real_time_translation.translation.llm_translator import LLMTranslator


@dataclass
class ModelSpec:
    label: str
    provider: Literal["gemini", "openai"]
    model: str
    thinking_budget: int | None = 0


MODELS: list[ModelSpec] = [
    ModelSpec("gpt-5.6-luna", "openai", "gpt-5.6-luna"),
    ModelSpec("gpt-5.4-mini", "openai", "gpt-5.4-mini"),
    ModelSpec("gpt-5.4-nano", "openai", "gpt-5.4-nano"),
    ModelSpec("gemini-3.6-flash", "gemini", "gemini-3.6-flash", thinking_budget=None),
    ModelSpec(
        "gemini-3.5-flash-lite",
        "gemini",
        "gemini-3.5-flash-lite",
        thinking_budget=None,
    ),
]


@dataclass
class SegmentResult:
    index: int
    asr_start_time: float
    source_text: str
    translation: str
    ttft_seconds: float | None
    total_seconds: float
    error: str | None = None


async def translate_segments(
    spec: ModelSpec,
    segments: list[dict],
    *,
    api_key: str,
    dictionary_path: Path,
    domain_packs: list[str],
    domain_packs_dir: Path,
) -> list[SegmentResult]:
    translator = LLMTranslator(
        provider=spec.provider,
        api_key=api_key,
        model=spec.model,
        dictionary_path=dictionary_path,
        domain_packs=domain_packs,
        domain_packs_dir=domain_packs_dir,
        thinking_budget=spec.thinking_budget,
    )
    if spec.provider == "gemini":
        await translator.prepare()

    results: list[SegmentResult] = []
    for i, seg in enumerate(segments):
        text = seg["asr"].strip()
        if not text:
            continue
        t0 = time.time()
        ttft: float | None = None
        full = ""
        error: str | None = None
        try:
            async for chunk in translator.translate_stream(text):
                if ttft is None:
                    ttft = time.time() - t0
                full += chunk
        except Exception as exc:  # noqa: BLE001
            error = f"{type(exc).__name__}: {exc}"
        results.append(
            SegmentResult(
                index=i,
                asr_start_time=seg["asr_start_time"],
                source_text=text,
                translation=full.strip(),
                ttft_seconds=ttft,
                total_seconds=time.time() - t0,
                error=error,
            )
        )
    return results


async def run_comparison(
    *,
    experiment_path: Path,
    window_start: float,
    window_end: float,
    out_dir: Path,
    google_api_key: str,
    openai_api_key: str,
    dictionary_path: Path,
    domain_packs: list[str],
    domain_packs_dir: Path,
    only: list[str] | None = None,
) -> None:
    models = [m for m in MODELS if only is None or m.label in only]
    data = json.loads(experiment_path.read_text(encoding="utf-8"))
    segments = [
        s
        for s in data["results"]["segments"]
        if s["asr_start_time"] is not None
        and window_start <= s["asr_start_time"] < window_end
    ]
    segments.sort(key=lambda s: s["asr_start_time"])
    print(f"Replaying {len(segments)} segments through each model...\n")

    out_dir.mkdir(parents=True, exist_ok=True)
    summary_path = out_dir / "summary.json"
    summary: dict[str, dict] = (
        json.loads(summary_path.read_text(encoding="utf-8"))
        if summary_path.exists()
        else {}
    )

    for spec in models:
        api_key = google_api_key if spec.provider == "gemini" else openai_api_key
        if not api_key:
            print(f"=== {spec.label}: SKIPPED (no API key) ===\n")
            summary[spec.label] = {"skipped": "no API key"}
            continue

        print(f"=== {spec.label} ===")
        t0 = time.time()
        try:
            results = await translate_segments(
                spec,
                segments,
                api_key=api_key,
                dictionary_path=dictionary_path,
                domain_packs=domain_packs,
                domain_packs_dir=domain_packs_dir,
            )
        except Exception as exc:  # noqa: BLE001
            print(f"  FAILED to run: {type(exc).__name__}: {exc}\n")
            summary[spec.label] = {"failed": f"{type(exc).__name__}: {exc}"}
            continue
        elapsed = time.time() - t0

        errors = [r for r in results if r.error]
        ok = [r for r in results if not r.error]
        ttfts = [r.ttft_seconds for r in ok if r.ttft_seconds is not None]
        empty = [r for r in ok if not r.translation]

        out_path = out_dir / f"{spec.label}.json"
        out_path.write_text(
            json.dumps([asdict(r) for r in results], ensure_ascii=False, indent=2)
            + "\n",
            encoding="utf-8",
        )

        avg_ttft = sum(ttfts) / len(ttfts) if ttfts else None
        summary[spec.label] = {
            "segments": len(results),
            "errors": len(errors),
            "empty_translations": len(empty),
            "avg_ttft_seconds": avg_ttft,
            "max_ttft_seconds": max(ttfts) if ttfts else None,
            "total_wall_seconds": elapsed,
            "output_file": str(out_path),
        }
        print(
            f"  segments={len(results)} errors={len(errors)} "
            f"empty={len(empty)} avg_ttft={avg_ttft}"
            if avg_ttft is None
            else f"  segments={len(results)} errors={len(errors)} "
            f"empty={len(empty)} avg_ttft={avg_ttft:.2f}s "
            f"total={elapsed:.1f}s"
        )
        if errors:
            print(f"  first error: {errors[0].error}")
        print(f"  wrote: {out_path}\n")

    summary_path.write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(f"Summary: {summary_path}")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--experiment", type=Path, required=True)
    parser.add_argument("--window-start", type=float, required=True)
    parser.add_argument("--window-end", type=float, required=True)
    parser.add_argument("--out-dir", type=Path, required=True)
    parser.add_argument("--dictionary-path", type=Path, default=Path("dictionary.csv"))
    parser.add_argument("--domain-packs", default="LLM2024_8_part1")
    parser.add_argument(
        "--domain-packs-dir", type=Path, default=Path("dictionaries/sessions")
    )
    parser.add_argument(
        "--only",
        default=None,
        help="Comma-separated model labels to run (default: all)",
    )
    return parser


def main(argv: list[str] | None = None) -> None:
    from real_time_translation.config import Config

    args = build_parser().parse_args(argv)
    config = Config.from_env(require_zoom=False)

    asyncio.run(
        run_comparison(
            experiment_path=args.experiment,
            window_start=args.window_start,
            window_end=args.window_end,
            out_dir=args.out_dir,
            google_api_key=config.google_api_key or "",
            openai_api_key=config.openai_api_key or "",
            dictionary_path=args.dictionary_path,
            domain_packs=[p for p in args.domain_packs.split(",") if p],
            domain_packs_dir=args.domain_packs_dir,
            only=[m for m in args.only.split(",") if m] if args.only else None,
        )
    )


if __name__ == "__main__":
    main()
