"""Orchestrates video -> candidate terminology glossary extraction via vision.

No slide deck available? Sample frames directly from the video and let a
vision-capable LLM read the on-screen slide text itself. This path never
touches audio -- it's a pure-vision alternative to `document_preload` for
when a talk was recorded but the deck wasn't shared.

Usage (manual/standalone; automatic wiring is handled by `auto_preload`):
  uv run real-time-translation-preload-video video/talk.mp4 \\
      --out dictionaries/sessions/talk.csv
"""

from __future__ import annotations

import argparse
import asyncio
import shutil
import tempfile
from pathlib import Path

from real_time_translation.preload.document_preload import save_glossary_csv
from real_time_translation.preload.term_extractor import extract_terms_from_images
from real_time_translation.translation.dictionary import DictionaryEntry

# ffmpeg scene-change score (0..1) above which a frame is sampled. Chosen
# over fixed-interval (fps) sampling because talks are mostly static
# slides punctuated by occasional transitions: fixed-interval sampling
# either wastes calls on near-duplicate frames of a slide that's been up
# for minutes, or misses a slide that's only shown briefly. Scene detection
# naturally samples ~once per slide change instead.
DEFAULT_SCENE_THRESHOLD = 0.15
DEFAULT_MAX_FRAMES = 40
DEFAULT_BATCH_SIZE = 6


async def sample_slide_frames(
    video_path: Path | str,
    *,
    start_seconds: float = 0.0,
    duration_seconds: float | None = None,
    scene_threshold: float = DEFAULT_SCENE_THRESHOLD,
    max_frames: int = DEFAULT_MAX_FRAMES,
    out_dir: Path | str | None = None,
) -> list[Path]:
    """Sample distinct-looking frames from a video via ffmpeg scene detection.

    Args:
        video_path: Path to a local video file
        start_seconds: Skip to this offset before sampling
        duration_seconds: Only sample within this many seconds (default: rest
            of file)
        scene_threshold: ffmpeg scene-change score threshold, 0..1. Lower
            samples more frames (more sensitive to change).
        max_frames: Hard cap on frames extracted (bounds LLM call cost on a
            long or highly dynamic video)
        out_dir: Directory to write frames to (default: a fresh temp dir --
            caller owns cleanup either way)

    Returns:
        Paths to sampled JPEG frames, in chronological order

    Raises:
        RuntimeError: If ffmpeg isn't installed or the extraction fails
        FileNotFoundError: If `video_path` doesn't exist
    """
    if shutil.which("ffmpeg") is None:
        raise RuntimeError("ffmpeg not found in PATH")

    video_path = Path(video_path)
    if not video_path.is_file():
        raise FileNotFoundError(f"Video not found: {video_path}")

    frames_dir = Path(out_dir) if out_dir else Path(tempfile.mkdtemp(prefix="slides_"))
    frames_dir.mkdir(parents=True, exist_ok=True)

    cmd = ["ffmpeg", "-hide_banner", "-loglevel", "error"]
    if start_seconds:
        cmd += ["-ss", f"{start_seconds}"]
    cmd += ["-i", str(video_path)]
    if duration_seconds is not None:
        cmd += ["-t", f"{duration_seconds}"]
    cmd += [
        "-vf",
        f"select='gt(scene,{scene_threshold})'",
        "-vsync",
        "vfr",
        "-frames:v",
        str(max_frames),
        "-q:v",
        "3",
        str(frames_dir / "frame_%04d.jpg"),
    ]

    proc = await asyncio.create_subprocess_exec(
        *cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
    )
    _, stderr = await proc.communicate()
    if proc.returncode != 0:
        raise RuntimeError(
            f"ffmpeg frame sampling failed (rc={proc.returncode}): "
            f"{stderr.decode('utf-8', errors='replace')}"
        )

    return sorted(frames_dir.glob("frame_*.jpg"))


def _batch(items: list[Path], size: int) -> list[list[Path]]:
    return [items[i : i + size] for i in range(0, len(items), size)]


async def extract_glossary_from_video(
    video_path: Path | str,
    *,
    api_key: str,
    model: str = "gemini-3.1-flash-lite",
    source_language: str = "English",
    target_language: str = "Japanese",
    start_seconds: float = 0.0,
    duration_seconds: float | None = None,
    scene_threshold: float = DEFAULT_SCENE_THRESHOLD,
    max_frames: int = DEFAULT_MAX_FRAMES,
    batch_size: int = DEFAULT_BATCH_SIZE,
    max_terms: int = 80,
    keep_frames_dir: Path | str | None = None,
) -> list[DictionaryEntry]:
    """Extract a candidate terminology glossary straight from a video's slides.

    Samples frames via `sample_slide_frames`, then sends batches of frames
    to a vision LLM (see `term_extractor.extract_terms_from_images`) that
    reads on-screen terminology directly -- no slide deck file required.

    Args:
        video_path: Path to a local video file
        api_key: Google AI API key (vision extraction is Gemini-only)
        model: Gemini model name (must support image input)
        source_language: Source language name
        target_language: Target language name
        start_seconds: Skip to this offset before sampling
        duration_seconds: Only sample within this many seconds
        scene_threshold: ffmpeg scene-change sensitivity, see
            `sample_slide_frames`
        max_frames: Hard cap on frames sampled
        batch_size: Frames sent per vision LLM call
        max_terms: Maximum total terms returned across all batches
        keep_frames_dir: If given, sampled frames are written here and kept
            (for inspection/debugging) instead of a temp dir that gets
            deleted after extraction

    Returns:
        Extracted entries, deduplicated case-insensitively on source_term
    """
    owns_temp_dir = keep_frames_dir is None
    frames = await sample_slide_frames(
        video_path,
        start_seconds=start_seconds,
        duration_seconds=duration_seconds,
        scene_threshold=scene_threshold,
        max_frames=max_frames,
        out_dir=keep_frames_dir,
    )

    try:
        if not frames:
            return []

        batches = _batch(frames, batch_size)
        per_batch_limit = max(10, max_terms // max(1, len(batches)) + 10)

        seen: set[str] = set()
        entries: list[DictionaryEntry] = []
        for batch_paths in batches:
            if len(entries) >= max_terms:
                break
            images = [p.read_bytes() for p in batch_paths]
            batch_entries = await extract_terms_from_images(
                images,
                api_key=api_key,
                model=model,
                source_language=source_language,
                target_language=target_language,
                max_terms=per_batch_limit,
            )
            for entry in batch_entries:
                key = entry.source_term.lower()
                if key in seen:
                    continue
                seen.add(key)
                entries.append(entry)
                if len(entries) >= max_terms:
                    break
        return entries
    finally:
        if owns_temp_dir and frames:
            shutil.rmtree(frames[0].parent, ignore_errors=True)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Extract a candidate terminology glossary directly from a "
            "video's slide frames (vision only, no audio/transcript) -- "
            "for talks with no separate slide deck available."
        )
    )
    parser.add_argument("video", type=Path, help="Path to a local video file")
    parser.add_argument(
        "--out",
        type=Path,
        default=None,
        help="Output CSV path (default: dictionaries/sessions/<stem>.csv)",
    )
    parser.add_argument("--start", type=float, default=0.0, help="Start offset (s)")
    parser.add_argument(
        "--duration", type=float, default=None, help="Seconds to sample (s)"
    )
    parser.add_argument("--source-language", default="English")
    parser.add_argument("--target-language", default="Japanese")
    parser.add_argument("--max-terms", type=int, default=80)
    parser.add_argument("--max-frames", type=int, default=DEFAULT_MAX_FRAMES)
    parser.add_argument(
        "--scene-threshold", type=float, default=DEFAULT_SCENE_THRESHOLD
    )
    parser.add_argument("--model", default=None)
    parser.add_argument(
        "--keep-frames-dir",
        type=Path,
        default=None,
        help="Keep sampled frames here instead of deleting them after use",
    )
    return parser


def main(argv: list[str] | None = None) -> None:
    from real_time_translation.config import Config

    args = build_parser().parse_args(argv)

    config = Config.from_env(require_zoom=False)
    api_key = config.google_api_key or ""
    model = args.model or config.gemini_model

    out_path = args.out or Path("dictionaries/sessions") / f"{args.video.stem}.csv"

    entries = asyncio.run(
        extract_glossary_from_video(
            args.video,
            api_key=api_key,
            model=model,
            source_language=args.source_language,
            target_language=args.target_language,
            start_seconds=args.start,
            duration_seconds=args.duration,
            scene_threshold=args.scene_threshold,
            max_frames=args.max_frames,
            max_terms=args.max_terms,
            keep_frames_dir=args.keep_frames_dir,
        )
    )
    written_path = save_glossary_csv(entries, out_path)

    print(f"Extracted {len(entries)} candidate terms from {args.video}")
    print(f"Wrote: {written_path}")


if __name__ == "__main__":
    main()
