"""LLM-based technical terminology extraction from raw text.

Shared by both document-based (`document_preload`) and video-vision-based
(`video_preload`) pre-brief paths: both end up with some chunk of raw
{source_language} text (slide text, or a vision model's description of a
slide frame) and need the same "pull out the jargon" step.
"""

from __future__ import annotations

import json
from typing import Literal

from real_time_translation.translation.dictionary import DictionaryEntry

EXTRACTION_PROMPT_TEMPLATE = """You are helping a live simultaneous interpreter \
prepare for a talk before it starts, the way a professional interpreter reviews \
slides/an abstract in advance to pre-load unfamiliar vocabulary.

Below is raw text extracted from presentation material (slide titles, bullet \
points, speaker notes, or a description of what's visible on a slide). Identify \
technical or domain-specific terms, acronyms, and proper nouns that a live \
{source_language}-to-{target_language} interpreter should know in advance -- the \
kind of term a generalist interpreter would mistranslate, mishear, or \
mistranscribe.

For each term, provide:
- source_term: the term as it would be spoken/written in {source_language}
- target_term: the standard, idiomatic {target_language} translation. Keep \
acronyms/proper nouns/model names unchanged if that's how they're conventionally \
used in {target_language}.
- notes: brief context in a few words, empty string if not needed

Skip generic vocabulary any interpreter already knows. Skip duplicates. Return \
at most {max_terms} of the most important terms, ranked by importance.

<material>
{text}
</material>

Respond with ONLY a JSON object of this exact shape, no markdown code fences, \
no other text:
{{"terms": [{{"source_term": "...", "target_term": "...", "notes": "..."}}, ...]}}
"""

VIDEO_EXTRACTION_PROMPT_TEMPLATE = """You are helping a live simultaneous \
interpreter prepare for a talk before it starts, the way a professional \
interpreter reviews slides in advance to pre-load unfamiliar vocabulary.

The attached images are frames sampled directly from the talk's video -- \
there is no separate slide deck. Read the on-screen text (titles, bullet \
points, axis labels, equations, diagram labels) across all attached frames. \
Identify technical or domain-specific terms, acronyms, and proper nouns that \
a live {source_language}-to-{target_language} interpreter should know in \
advance -- the kind of term a generalist interpreter would mistranslate, \
mishear, or mistranscribe. Ignore anything that isn't legible text on screen.

For each term, provide:
- source_term: the term as it would be spoken/written in {source_language}
- target_term: the standard, idiomatic {target_language} translation. Keep \
acronyms/proper nouns/model names unchanged if that's how they're conventionally \
used in {target_language}.
- notes: brief context in a few words, empty string if not needed

Skip generic vocabulary any interpreter already knows. Skip duplicates. Return \
at most {max_terms} of the most important terms, ranked by importance.

Respond with ONLY a JSON object of this exact shape, no markdown code fences, \
no other text:
{{"terms": [{{"source_term": "...", "target_term": "...", "notes": "..."}}, ...]}}
"""


def _parse_terms_payload(raw: str) -> list[dict]:
    """Parse the LLM's JSON response, tolerating markdown code fences."""
    raw = raw.strip()
    if raw.startswith("```"):
        raw = raw.strip("`")
        if raw.lower().startswith("json"):
            raw = raw[4:]
        raw = raw.strip()

    data = json.loads(raw)
    if isinstance(data, dict):
        data = data.get("terms", [])
    if not isinstance(data, list):
        raise ValueError("Expected a JSON array of term objects, or {'terms': [...]}")
    return data


def _entries_from_payload(
    items: list[dict], *, max_terms: int
) -> list[DictionaryEntry]:
    entries: list[DictionaryEntry] = []
    seen: set[str] = set()
    for item in items:
        if not isinstance(item, dict):
            continue
        source = str(item.get("source_term", "")).strip()
        target = str(item.get("target_term", "")).strip()
        notes = str(item.get("notes", "")).strip()
        if not source or not target:
            continue
        key = source.lower()
        if key in seen:
            continue
        seen.add(key)
        entries.append(
            DictionaryEntry(source_term=source, target_term=target, notes=notes)
        )
        if len(entries) >= max_terms:
            break
    return entries


async def _call_gemini(prompt: str, *, api_key: str, model: str) -> str:
    from google import genai
    from google.genai import types

    client = genai.Client(api_key=api_key)
    config = types.GenerateContentConfig(
        temperature=0.1,
        max_output_tokens=4096,
        response_mime_type="application/json",
    )
    response = await client.aio.models.generate_content(
        model=model, contents=prompt, config=config
    )
    return response.text or ""


async def _call_gemini_vision(
    images: list[bytes], prompt: str, *, api_key: str, model: str
) -> str:
    from google import genai
    from google.genai import types

    client = genai.Client(api_key=api_key)
    config = types.GenerateContentConfig(
        temperature=0.1,
        max_output_tokens=4096,
        response_mime_type="application/json",
    )
    image_parts = [
        types.Part.from_bytes(data=image, mime_type="image/jpeg") for image in images
    ]
    response = await client.aio.models.generate_content(
        model=model, contents=[prompt, *image_parts], config=config
    )
    return response.text or ""


async def _call_openai(prompt: str, *, api_key: str, model: str) -> str:
    from openai import AsyncOpenAI

    client = AsyncOpenAI(api_key=api_key)
    response = await client.chat.completions.create(
        model=model,
        messages=[{"role": "user", "content": prompt}],
        temperature=0.1,
        max_completion_tokens=4096,
        response_format={"type": "json_object"},
    )
    return response.choices[0].message.content or ""


async def extract_terms_from_text(
    text: str,
    *,
    provider: Literal["gemini", "openai"],
    api_key: str,
    model: str,
    source_language: str = "English",
    target_language: str = "Japanese",
    max_terms: int = 60,
) -> list[DictionaryEntry]:
    """Extract candidate terminology from raw text via one LLM call.

    A malformed/unparseable LLM response yields an empty list rather than
    raising -- pre-brief extraction is a best-effort quality improvement,
    not something that should be able to crash a session that would
    otherwise start fine without it.

    Args:
        text: Raw source-language text to extract terms from
        provider: LLM provider ("gemini" or "openai")
        api_key: API key for the provider
        model: Model name to use
        source_language: Source language name
        target_language: Target language name
        max_terms: Maximum number of terms to return

    Returns:
        Extracted entries, deduplicated case-insensitively on source_term
    """
    if not text.strip():
        return []

    prompt = EXTRACTION_PROMPT_TEMPLATE.format(
        source_language=source_language,
        target_language=target_language,
        max_terms=max_terms,
        text=text,
    )

    if provider == "gemini":
        raw = await _call_gemini(prompt, api_key=api_key, model=model)
    else:
        raw = await _call_openai(prompt, api_key=api_key, model=model)

    try:
        items = _parse_terms_payload(raw)
    except (json.JSONDecodeError, ValueError):
        return []

    return _entries_from_payload(items, max_terms=max_terms)


async def extract_terms_from_images(
    images: list[bytes],
    *,
    api_key: str,
    model: str,
    source_language: str = "English",
    target_language: str = "Japanese",
    max_terms: int = 60,
) -> list[DictionaryEntry]:
    """Extract candidate terminology directly from slide frame images.

    Gemini-only: OpenAI's image-part API differs and isn't wired up here.
    Pass a Google API key regardless of which provider the live translation
    session uses -- this is a one-time pre-session step, not part of the
    real-time translation path, so it doesn't need to match `llm_provider`.

    Args:
        images: Raw JPEG/PNG bytes of sampled video frames
        api_key: Google AI API key
        model: Gemini model name (must support image input)
        source_language: Source language name
        target_language: Target language name
        max_terms: Maximum number of terms to return

    Returns:
        Extracted entries, deduplicated case-insensitively on source_term
    """
    if not images:
        return []

    prompt = VIDEO_EXTRACTION_PROMPT_TEMPLATE.format(
        source_language=source_language,
        target_language=target_language,
        max_terms=max_terms,
    )
    raw = await _call_gemini_vision(images, prompt, api_key=api_key, model=model)

    try:
        items = _parse_terms_payload(raw)
    except (json.JSONDecodeError, ValueError):
        return []

    return _entries_from_payload(items, max_terms=max_terms)
