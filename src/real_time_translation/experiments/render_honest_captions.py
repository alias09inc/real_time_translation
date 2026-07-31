"""Burn translated captions onto a video at their TRUE arrival time.

This deliberately does NOT resync captions to when the speaker actually
said the words. Each caption cue is timed to `playback_offset` from a
video_segment.py experiment JSON -- the real wall-clock moment the text
streamed in during a real-time (speed=1.0) run. Watching the output shows
genuinely how the system performs: captions visibly lag behind speech by
whatever the real end-to-end latency was, and text grows incrementally as
translation tokens actually streamed in rather than appearing all at once.

Usage:
  uv run python -m real_time_translation.experiments.render_honest_captions \
    --experiment experiments/20260722_soft_finalize_timeout_flashlite.json \
    --video experiments/clips/clip_4m00_40s_stall_repro.mp4 \
    --output experiments/clips/honest_captions_demo.mp4
"""

from __future__ import annotations

import argparse
import asyncio
import json
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class Cue:
    start: float
    end: float
    text: str


def _ass_timestamp(seconds: float) -> str:
    seconds = max(0.0, seconds)
    hours = int(seconds // 3600)
    minutes = int((seconds % 3600) // 60)
    secs = seconds % 60
    centis = int(round((secs - int(secs)) * 100))
    if centis >= 100:
        centis -= 100
        secs += 1
    return f"{hours:d}:{minutes:02d}:{int(secs):02d}.{centis:02d}"


def _escape_ass_text(text: str) -> str:
    return text.replace("\\", "\\\\").replace("{", "\\{").replace("}", "\\}").replace(
        "\n", "\\N"
    )


def _probe_resolution(video_path: Path) -> tuple[int, int]:
    if shutil.which("ffprobe") is None:
        return (1920, 1080)
    result = subprocess.run(
        [
            "ffprobe",
            "-v",
            "error",
            "-select_streams",
            "v:0",
            "-show_entries",
            "stream=width,height",
            "-of",
            "csv=s=x:p=0",
            str(video_path),
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    try:
        width_str, height_str = result.stdout.strip().split("x")
        return int(width_str), int(height_str)
    except (ValueError, AttributeError):
        return (1920, 1080)


def build_cues(events: list[dict[str, Any]], clip_end: float) -> list[Cue]:
    """Build sequential caption cues from translation events.

    Each event's text is shown from its own arrival time until the next
    translation event arrives (or the clip ends), reproducing the true
    incremental reveal -- and true lag -- of the live run.
    """
    translation_kinds = ("translation_partial", "translation_complete")
    translation_events = [e for e in events if e["kind"] in translation_kinds]
    cues: list[Cue] = []
    for i, event in enumerate(translation_events):
        text = event["text"].strip()
        if not text:
            continue
        start = event["playback_offset"]
        end = (
            translation_events[i + 1]["playback_offset"]
            if i + 1 < len(translation_events)
            else clip_end
        )
        if end <= start:
            continue
        cues.append(Cue(start=start, end=end, text=text))
    return cues


_ASS_STYLE_FORMAT = (
    "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, "
    "OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, "
    "ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, "
    "MarginL, MarginR, MarginV, Encoding"
)
_ASS_STYLE_LINE = (
    # BorderStyle=1 (outline, not a filled box): BorderStyle=3 opaque boxes
    # were found to silently fail to render on this libass build. A bold
    # white face with a thick black outline + shadow is a standard,
    # YouTube-caption-like look on its own.
    "Style: Default,Arial,{fontsize},&H00FFFFFF,&H000000FF,&H00000000,"
    "&H00000000,-1,0,0,0,100,100,0,0,1,4,2,2,{margin_lr},{margin_lr},"
    "{margin_v},1"
)

ASS_HEADER_TEMPLATE = (
    "[Script Info]\n"
    "ScriptType: v4.00+\n"
    "PlayResX: {width}\n"
    "PlayResY: {height}\n"
    "WrapStyle: 0\n"
    "ScaledBorderAndShadow: yes\n"
    "\n"
    "[V4+ Styles]\n"
    f"{_ASS_STYLE_FORMAT}\n"
    f"{_ASS_STYLE_LINE}\n"
    "\n"
    "[Events]\n"
    "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, "
    "Effect, Text\n"
)


def write_ass_file(cues: list[Cue], *, width: int, height: int, path: Path) -> None:
    fontsize = max(24, height // 24)
    margin_lr = width // 20
    margin_v = height // 15
    header = ASS_HEADER_TEMPLATE.format(
        width=width,
        height=height,
        fontsize=fontsize,
        margin_lr=margin_lr,
        margin_v=margin_v,
    )
    lines = [header]
    for cue in cues:
        lines.append(
            f"Dialogue: 0,{_ass_timestamp(cue.start)},{_ass_timestamp(cue.end)},"
            f"Default,,0,0,0,,{_escape_ass_text(cue.text)}\n"
        )
    path.write_text("".join(lines), encoding="utf-8")


async def burn_captions(
    *, video_path: Path, ass_path: Path, output_path: Path
) -> None:
    if shutil.which("ffmpeg") is None:
        raise RuntimeError("ffmpeg not found in PATH")

    # libass on ffmpeg's filtergraph needs escaped path separators/colons.
    ass_filter_path = str(ass_path).replace("\\", "/").replace(":", "\\:")
    cmd = [
        "ffmpeg",
        "-y",
        "-hide_banner",
        "-loglevel",
        "error",
        "-i",
        str(video_path),
        "-vf",
        f"ass='{ass_filter_path}'",
        "-c:v",
        "libx264",
        "-preset",
        "medium",
        "-crf",
        "20",
        "-c:a",
        "copy",
        str(output_path),
    ]
    proc = await asyncio.create_subprocess_exec(
        *cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
    )
    _, stderr = await proc.communicate()
    if proc.returncode != 0:
        raise RuntimeError(f"ffmpeg failed (rc={proc.returncode}):\n{stderr.decode()}")


async def run(*, experiment_path: Path, video_path: Path, output_path: Path) -> None:
    data = json.loads(experiment_path.read_text(encoding="utf-8"))
    events = data["results"]["events"]

    width, height = _probe_resolution(video_path)

    duration_seconds = data["input"].get("duration_seconds")
    if duration_seconds is None:
        # Fall back to the last event's offset plus a small tail.
        duration_seconds = (events[-1]["playback_offset"] + 5.0) if events else 30.0

    cues = build_cues(events, clip_end=duration_seconds)
    if not cues:
        raise RuntimeError("No translation events found in experiment JSON")

    ass_path = output_path.with_suffix(".ass")
    write_ass_file(cues, width=width, height=height, path=ass_path)

    await burn_captions(
        video_path=video_path, ass_path=ass_path, output_path=output_path
    )
    print(f"Subtitle file: {ass_path}")
    print(f"Output video: {output_path}")
    print(f"Cues: {len(cues)}")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Burn honest-timing (non-resynced) captions onto a video."
    )
    parser.add_argument(
        "--experiment",
        required=True,
        type=Path,
        help="Path to a video_segment.py experiment JSON",
    )
    parser.add_argument(
        "--video",
        required=True,
        type=Path,
        help="Path to the source video (with picture) to caption",
    )
    parser.add_argument("--output", required=True, type=Path, help="Output mp4 path")
    return parser


def main(argv: list[str] | None = None) -> None:
    args = build_parser().parse_args(argv)
    asyncio.run(
        run(
            experiment_path=args.experiment,
            video_path=args.video,
            output_path=args.output,
        )
    )


if __name__ == "__main__":
    main()
