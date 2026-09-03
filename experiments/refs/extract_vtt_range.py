"""Extract plain text from a WebVTT file within [start, end) seconds."""
from __future__ import annotations

import re
import sys
from pathlib import Path


def to_seconds(ts: str) -> float:
    h, m, s = ts.split(":")
    return int(h) * 3600 + int(m) * 60 + float(s)


def extract(path: Path, start: float, end: float) -> str:
    raw = path.read_text(encoding="utf-8")
    blocks = raw.split("\n\n")
    ts_re = re.compile(r"(\d\d:\d\d:\d\d\.\d\d\d) --> (\d\d:\d\d:\d\d\.\d\d\d)")
    tag_re = re.compile(r"<[^>]+>")
    seen: list[str] = []
    last = None
    for block in blocks:
        m = ts_re.search(block)
        if not m:
            continue
        bstart = to_seconds(m.group(1))
        if not (start <= bstart < end):
            continue
        lines = block.split("\n")
        text_lines = [tag_re.sub("", ln).strip() for ln in lines[lines.index(m.group(0)) + 1 :] if ln.strip()]
        text = " ".join(text_lines).strip()
        if text and text != last:
            seen.append(text)
            last = text
    return " ".join(seen)


if __name__ == "__main__":
    path = Path(sys.argv[1])
    start = float(sys.argv[2])
    end = float(sys.argv[3])
    print(extract(path, start, end))
