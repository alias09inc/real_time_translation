"""Automatic pre-session glossary loading, dispatched by file extension.

The manual counterpart to this is running `document_preload`/`video_preload`
by hand. This module is what lets a session just point at a file --
`PRELOAD_SOURCE=slides.pdf` -- and have it happen automatically at startup,
the way a human interpreter reads the material before the talk starts.
"""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import TYPE_CHECKING

from real_time_translation.preload.document_preload import (
    extract_glossary_from_document,
    save_glossary_csv,
)
from real_time_translation.preload.video_preload import extract_glossary_from_video
from real_time_translation.translation.dictionary import DictionaryEntry, TermDictionary

if TYPE_CHECKING:
    from real_time_translation.config import Config
    from real_time_translation.translation.llm_translator import LLMTranslator

DOCUMENT_EXTENSIONS = {".pdf", ".pptx"}
VIDEO_EXTENSIONS = {".mp4", ".mov", ".mkv", ".webm", ".avi", ".m4v"}

DEFAULT_CACHE_DIR = Path("dictionaries/sessions/.cache")


def _cache_path(source: Path, cache_dir: Path) -> Path:
    """Deterministic cache path for a source file's current content.

    Keyed on path + size + mtime, not just the path, so editing a deck
    (new slide, fixed typo) invalidates the cache instead of silently
    reusing stale extracted terms.
    """
    stat = source.stat()
    key = f"{source.resolve()}::{stat.st_size}::{stat.st_mtime_ns}"
    digest = hashlib.sha1(key.encode("utf-8")).hexdigest()[:16]
    return cache_dir / f"{source.stem}_{digest}.csv"


async def extract_glossary_auto(
    path: Path | str,
    *,
    config: Config,
    source_language: str,
    target_language: str,
    max_terms: int = 80,
    cache_dir: Path | str = DEFAULT_CACHE_DIR,
) -> list[DictionaryEntry]:
    """Extract a candidate glossary from `path`, dispatched by extension.

    Results are cached to `cache_dir` keyed on the source file's content,
    so re-running against the same (unchanged) file doesn't re-pay for the
    LLM extraction call.

    Args:
        path: Path to a .pdf/.pptx deck or a video file
        config: App config -- source of API keys/models for extraction
        source_language: Source language name (should match the session)
        target_language: Target language name
        max_terms: Maximum terms to extract
        cache_dir: Where cached extraction results are stored

    Returns:
        Extracted entries. Empty if the file type isn't recognized, or if
        it's a video and no Google API key is configured (vision
        extraction is Gemini-only -- see `video_preload`).

    Raises:
        FileNotFoundError: If `path` doesn't exist
    """
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(f"Preload source not found: {path}")

    cache_dir = Path(cache_dir)
    cache_file = _cache_path(path, cache_dir)
    if cache_file.exists():
        cached = TermDictionary()
        cached.load_csv(cache_file)
        return list(cached)

    suffix = path.suffix.lower()
    entries: list[DictionaryEntry]

    if suffix in DOCUMENT_EXTENSIONS:
        provider = config.llm_provider
        api_key = (
            config.google_api_key if provider == "gemini" else config.openai_api_key
        )
        model = config.gemini_model if provider == "gemini" else config.openai_model
        entries = await extract_glossary_from_document(
            path,
            provider=provider,  # type: ignore[arg-type]
            api_key=api_key or "",
            model=model,
            source_language=source_language,
            target_language=target_language,
            max_terms=max_terms,
        )
    elif suffix in VIDEO_EXTENSIONS:
        if not config.google_api_key:
            return []
        entries = await extract_glossary_from_video(
            path,
            api_key=config.google_api_key,
            model=config.gemini_model,
            source_language=source_language,
            target_language=target_language,
            max_terms=max_terms,
        )
    else:
        return []

    if entries:
        cache_dir.mkdir(parents=True, exist_ok=True)
        save_glossary_csv(entries, cache_file)
    return entries


async def preload_translator(
    translator: LLMTranslator,
    path: Path | str,
    *,
    config: Config,
    max_terms: int = 80,
    cache_dir: Path | str = DEFAULT_CACHE_DIR,
) -> int:
    """Extract from `path` and merge the result into `translator`.

    A broken/unreadable preload source must never prevent a session from
    starting -- it's a best-effort quality improvement layered on top of a
    session that works fine without it -- so failures are caught and
    logged rather than raised.

    Returns:
        Number of new terms actually added (0 on failure or no new terms)
    """
    try:
        entries = await extract_glossary_auto(
            path,
            config=config,
            source_language=translator.source_language,
            target_language=translator.target_language,
            max_terms=max_terms,
            cache_dir=cache_dir,
        )
    except Exception as exc:  # noqa: BLE001
        print(f"Auto-preload from {path} failed, continuing without it: {exc}")
        return 0

    return translator.merge_supplementary_entries(entries)
