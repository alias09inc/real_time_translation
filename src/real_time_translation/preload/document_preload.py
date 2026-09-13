"""Orchestrates PDF/PPTX -> candidate terminology glossary extraction.

Usage (manual/standalone; automatic wiring into a live session is handled
by `auto_preload`):
  uv sync --extra preload
  uv run real-time-translation-preload-doc slides.pdf \\
      --out dictionaries/sessions/talk.csv
"""

from __future__ import annotations

import argparse
import asyncio
import csv
from pathlib import Path
from typing import Literal

from real_time_translation.preload.document_extractor import extract_document_text
from real_time_translation.preload.term_extractor import extract_terms_from_text
from real_time_translation.translation.dictionary import DictionaryEntry

# Conservative default: comfortably inside every current model's context
# window while keeping each extraction call cheap and fast, since a large
# deck is chunked into multiple calls rather than one huge one anyway.
DEFAULT_CHUNK_CHAR_LIMIT = 12000


def _chunk_blocks(blocks: list[str], *, char_limit: int) -> list[str]:
    """Group per-page/slide text blocks into LLM-call-sized chunks."""
    chunks: list[str] = []
    current: list[str] = []
    current_len = 0
    for block in blocks:
        if current and current_len + len(block) > char_limit:
            chunks.append("\n\n---\n\n".join(current))
            current = []
            current_len = 0
        current.append(block)
        current_len += len(block)
    if current:
        chunks.append("\n\n---\n\n".join(current))
    return chunks


async def extract_glossary_from_document(
    path: Path | str,
    *,
    provider: Literal["gemini", "openai"],
    api_key: str,
    model: str,
    source_language: str = "English",
    target_language: str = "Japanese",
    max_terms: int = 80,
    chunk_char_limit: int = DEFAULT_CHUNK_CHAR_LIMIT,
) -> list[DictionaryEntry]:
    """Extract a candidate terminology glossary from a PDF/PPTX document.

    Args:
        path: Path to a .pdf or .pptx file
        provider: LLM provider for extraction ("gemini" or "openai")
        api_key: API key for the provider
        model: Model name to use
        source_language: Source language name
        target_language: Target language name
        max_terms: Maximum total terms to return across the whole document
        chunk_char_limit: Max characters of slide text per extraction call

    Returns:
        Extracted entries, deduplicated case-insensitively on source_term,
        in document order. Empty if the document has no extractable text.
    """
    blocks = extract_document_text(path)
    if not blocks:
        return []

    chunks = _chunk_blocks(blocks, char_limit=chunk_char_limit)
    # Ask each chunk for a bit more than its even share, since some chunks
    # will yield fewer relevant terms than others (e.g. a title slide).
    per_chunk_limit = max(10, max_terms // max(1, len(chunks)) + 10)

    seen: set[str] = set()
    entries: list[DictionaryEntry] = []
    for chunk_text in chunks:
        if len(entries) >= max_terms:
            break
        chunk_entries = await extract_terms_from_text(
            chunk_text,
            provider=provider,
            api_key=api_key,
            model=model,
            source_language=source_language,
            target_language=target_language,
            max_terms=per_chunk_limit,
        )
        for entry in chunk_entries:
            key = entry.source_term.lower()
            if key in seen:
                continue
            seen.add(key)
            entries.append(entry)
            if len(entries) >= max_terms:
                break
    return entries


def save_glossary_csv(entries: list[DictionaryEntry], path: Path | str) -> Path:
    """Write extracted entries to a dictionary-format CSV.

    Returns:
        The path written to
    """
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["source_term", "target_term", "notes"])
        for entry in entries:
            writer.writerow([entry.source_term, entry.target_term, entry.notes])
    return path


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Extract a candidate terminology glossary from a slide deck "
            "(PDF/PPTX) before a session, the way a human interpreter "
            "pre-reads slides."
        )
    )
    parser.add_argument("document", type=Path, help="Path to a .pdf or .pptx file")
    parser.add_argument(
        "--out",
        type=Path,
        default=None,
        help="Output CSV path (default: dictionaries/sessions/<stem>.csv)",
    )
    parser.add_argument("--source-language", default="English")
    parser.add_argument("--target-language", default="Japanese")
    parser.add_argument("--max-terms", type=int, default=80)
    parser.add_argument("--provider", choices=["gemini", "openai"], default=None)
    parser.add_argument("--model", default=None)
    return parser


def main(argv: list[str] | None = None) -> None:
    from real_time_translation.config import Config

    args = build_parser().parse_args(argv)

    config = Config.from_env(require_zoom=False)
    provider = args.provider or config.llm_provider
    if provider == "gemini":
        api_key = config.google_api_key or ""
        model = args.model or config.gemini_model
    else:
        api_key = config.openai_api_key or ""
        model = args.model or config.openai_model

    out_path = args.out or Path("dictionaries/sessions") / f"{args.document.stem}.csv"

    entries = asyncio.run(
        extract_glossary_from_document(
            args.document,
            provider=provider,
            api_key=api_key,
            model=model,
            source_language=args.source_language,
            target_language=args.target_language,
            max_terms=args.max_terms,
        )
    )
    written_path = save_glossary_csv(entries, out_path)

    print(f"Extracted {len(entries)} candidate terms from {args.document}")
    print(f"Wrote: {written_path}")


if __name__ == "__main__":
    main()
