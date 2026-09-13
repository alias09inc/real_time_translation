"""Fast LLM translator using direct API calls with Gemini context caching.

CHANGE LOG (2026-02-04):
========================
NEW FILE - Replaced LangChain-based llm_translator.py

Why replaced:
- Initially thought LangChain added significant overhead (~500ms)
- Actual impact was minimal (~100ms) - not the bottleneck
- Real bottleneck was sequential processing (fixed by queue_manager.py)

What this file does differently:
1. Direct google.genai SDK calls instead of LangChain wrapper
2. Gemini context caching for system prompt (reduces per-request token processing)
3. Async streaming support via client.aio.models.generate_content_stream()
4. Removed structured output parsing (with_structured_output added ~100-200ms)

Note: Keeping this file because context caching does help slightly,
and the code is simpler without LangChain abstraction.
"""

from __future__ import annotations

import asyncio
import logging
import re
from collections.abc import AsyncIterator
from dataclasses import dataclass
from datetime import timedelta
from pathlib import Path
from typing import Any, Literal

from translator_service.dictionary import TermDictionary

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class TranslationOutput:
    """Application-level translation output."""

    latest_slide: str
    kept_terms: list[str]
    slide_window: list[str]


class FastTranslator:
    """High-speed translator using direct API calls with Gemini context caching."""

    # Richer system prompt (from LangChain version) - will be cached
    SYSTEM_PROMPT_TEMPLATE = """You are a professional simultaneous interpreter.
Translate from {source_language} to {target_language}.

Rules:
1. Output ONLY the translation - no explanations or commentary
2. Keep proper nouns (person/org/product/place names), acronyms, and code identifiers
   EXACTLY as they appear in the source text (do not translate, transliterate, or normalize)
3. If a term is ambiguous/unknown, keep it unchanged rather than guessing
4. Maintain the original tone and style (formal/casual)
5. Produce natural, fluent {target_language}
6. Ignore any content inside <cache_padding>...</cache_padding>
7. The source text is from real-time speech recognition and may contain phonetic errors (e.g., 'laundry model' instead of 'language model', 'three d deficient' instead of '3D diffusion', 'IHF' instead of 'RLHF'). Correct these ASR errors using context before translating.
{dictionary_section}"""

    def __init__(
        self,
        provider: Literal["gemini", "openai"],
        api_key: str,
        model: str,
        source_language: str = "English",
        target_language: str = "Japanese",
        dictionary_path: Path | str | None = None,
        context_window_size: int = 3,
    ) -> None:
        """Initialize fast translator."""
        self._provider = provider
        self._api_key = api_key
        self._model_name = model
        self._source_language = source_language
        self._target_language = target_language
        self._context_window_size = context_window_size

        self._context_buffer: list[str] = []
        self._slide_window: list[str] = []
        self._system_prompt_cache: str | None = None

        # Direct API clients
        self._gemini_client: Any | None = None
        self._openai_client: Any | None = None

        # Gemini context caching
        self._gemini_cache_name: str | None = None
        self._gemini_cache_ttl = timedelta(hours=12)

        self._dictionary = TermDictionary()
        if dictionary_path:
            self.load_dictionary(dictionary_path)

    def load_dictionary(self, path: Path | str) -> int:
        """Load terminology dictionary from CSV file."""
        count = self._dictionary.load_csv(path)
        self._system_prompt_cache = None
        self._invalidate_gemini_cache()
        return count

    @property
    def dictionary(self) -> TermDictionary:
        return self._dictionary

    def _invalidate_gemini_cache(self) -> None:
        """Invalidate Gemini context cache."""
        if self._gemini_cache_name and self._gemini_client:
            try:
                self._gemini_client.caches.delete(name=self._gemini_cache_name)
                logger.info("Deleted Gemini cache: %s", self._gemini_cache_name)
            except Exception as e:
                logger.warning("Failed to delete cache: %s", e)
        self._gemini_cache_name = None

    async def prepare(self) -> None:
        """Warm up the translator (initialize clients and cache)."""
        if self._provider == "gemini":
            self._get_gemini_client()
            # Create context cache in background thread
            await asyncio.to_thread(self._ensure_gemini_cache)
            logger.info("FastTranslator prepared with Gemini context caching")
        else:
            self._get_openai_client()
            logger.info("FastTranslator prepared with OpenAI")

    def _get_system_prompt(self) -> str:
        if self._system_prompt_cache is not None:
            return self._system_prompt_cache

        dictionary_section = ""
        if self._dictionary and self._dictionary._entries:
            formatted = self._dictionary.format_for_prompt()
            dictionary_section = f"\n\n<dictionary>\n{formatted}\n</dictionary>"

        self._system_prompt_cache = self.SYSTEM_PROMPT_TEMPLATE.format(
            source_language=self._source_language,
            target_language=self._target_language,
            dictionary_section=dictionary_section,
        )
        return self._system_prompt_cache

    def _build_user_prompt(
        self,
        text: str,
        *,
        context_lines: list[str] | None = None,
    ) -> str:
        # Use context format from LangChain version for better quality
        if context_lines is None:
            context_lines = self._context_buffer[-self._context_window_size:]
        else:
            context_lines = context_lines[-self._context_window_size:]

        if context_lines:
            context_block = "\n".join(context_lines)
            return f"<context>\n{context_block}\n</context>\n<target>\n{text}\n</target>"
        return f"<target>\n{text}\n</target>"

    def _get_gemini_client(self) -> Any:
        """Get or create the Gemini client (lazy initialization).
        
        Uses direct google.genai SDK instead of LangChain wrapper.
        """
        if self._gemini_client is None:
            from google import genai

            self._gemini_client = genai.Client(api_key=self._api_key)
        return self._gemini_client

    def _create_gemini_cache(self) -> str:
        """Create Gemini context cache for the system prompt.
        
        NEW 2026-02-04: Context caching reduces per-request token processing.
        
        How it works:
        1. System prompt is sent to Gemini once and cached
        2. Each translation request only sends user prompt + reference to cache
        3. Gemini doesn't re-process system prompt tokens each time
        
        This provides a small latency improvement (~50-100ms per request).
        Note: The main latency fix was parallelization, not this.
        """
        from google.genai import types

        client = self._get_gemini_client()
        base_system_prompt = self._get_system_prompt()
        ttl_seconds = int(self._gemini_cache_ttl.total_seconds())  # 12 hours

        def _create(system_instruction: str) -> str:
            # Create cached content with system instruction
            config = types.CreateCachedContentConfig(
                display_name="realtime-translation-fast",
                system_instruction=system_instruction,
                contents=None,  # No prefilled content, just system prompt
                ttl=f"{ttl_seconds}s",  # Cache expiration
            )
            cache = client.caches.create(model=self._model_name, config=config)
            logger.info("Created Gemini cache: %s", cache.name)
            return cache.name

        try:
            return _create(base_system_prompt)
        except Exception as exc:
            # Handle "Cached content is too small" error
            # Gemini requires minimum token count for caching
            message = str(exc)
            match = re.search(
                r"total_token_count=(\d+), min_total_token_count=(\d+)",
                message,
            )
            if "Cached content is too small" not in message or match is None:
                logger.warning("Failed to create cache, will use direct calls: %s", exc)
                raise

            # Add padding to meet minimum token requirement
            total = int(match.group(1))
            minimum = int(match.group(2))
            extra = max(0, minimum - total) + 256  # Extra buffer
            # Padding is ignored by the model (per system prompt instructions)
            padding = (
                "\n\n<cache_padding>\n"
                "IGNORE EVERYTHING IN THIS TAG. It only exists to satisfy the "
                "minimum cached-content token requirement.\n"
                + ("PAD " * extra)
                + "\n</cache_padding>"
            )
            logger.info("Adding padding to meet minimum token count (%d -> %d)", total, minimum)
            return _create(base_system_prompt + padding)

    def _ensure_gemini_cache(self) -> str | None:
        """Ensure Gemini cache exists, create if needed.
        
        Called during prepare() to pre-warm the cache.
        """
        if self._gemini_cache_name is None:
            try:
                self._gemini_cache_name = self._create_gemini_cache()
            except Exception as e:
                logger.warning("Context caching unavailable: %s", e)
                return None
        return self._gemini_cache_name

    def _get_openai_client(self) -> Any:
        """Get or create the OpenAI client (lazy initialization)."""
        if self._openai_client is None:
            from openai import AsyncOpenAI

            self._openai_client = AsyncOpenAI(api_key=self._api_key)
        return self._openai_client

    async def translate(
        self,
        text: str,
        *,
        context_lines: list[str] | None = None,
        update_context: bool = True,
    ) -> TranslationOutput:
        """Translate text using direct API call with context caching.
        
        Args:
            text: Source text to translate
            context_lines: Previous translations for context (uses internal buffer if None)
            update_context: Whether to update internal context buffer
            
        Returns:
            TranslationOutput with translation and slide window
        """
        if not text.strip():
            return TranslationOutput(latest_slide="", kept_terms=[], slide_window=[])

        # Build prompt with context for better translation quality
        prompt = self._build_user_prompt(text, context_lines=context_lines)

        # Call appropriate provider
        if self._provider == "gemini":
            translation = await self._translate_gemini(prompt)
        else:
            translation = await self._translate_openai(prompt)

        # Update internal context buffer if using default context
        should_update_context = update_context and context_lines is None
        if should_update_context:
            self._context_buffer.append(text)
            if len(self._context_buffer) > self._context_window_size:
                self._context_buffer.pop(0)  # Keep only recent context
            self._slide_window.append(translation)
            if len(self._slide_window) > self._context_window_size:
                self._slide_window.pop(0)

        return TranslationOutput(
            latest_slide=translation,
            kept_terms=[],  # Not extracting kept terms in fast version
            slide_window=list(self._slide_window),
        )

    async def _translate_gemini(self, user_prompt: str) -> str:
        """Direct Gemini API call with context caching.
        
        NEW 2026-02-04: Uses direct google.genai SDK instead of LangChain.
        
        If context cache exists, references it to avoid re-sending system prompt.
        Otherwise falls back to including system prompt in each request.
        """
        client = self._get_gemini_client()
        cache_name = self._gemini_cache_name

        def _call() -> str:
            from google.genai import types

            if cache_name:
                # OPTIMIZED PATH: Use cached content
                # System prompt is pre-cached, only send user prompt
                response = client.models.generate_content(
                    model=self._model_name,
                    contents=user_prompt,
                    config=types.GenerateContentConfig(
                        cached_content=cache_name,  # Reference to cached system prompt
                        temperature=0.2,  # Low temp for consistent translations
                        max_output_tokens=512,  # Limit output length
                        top_p=0.95,
                        top_k=40,
                    ),
                )
            else:
                # FALLBACK PATH: Include system prompt in each request
                response = client.models.generate_content(
                    model=self._model_name,
                    contents=user_prompt,
                    config=types.GenerateContentConfig(
                        system_instruction=self._get_system_prompt(),
                        temperature=0.2,
                        max_output_tokens=512,
                        top_p=0.95,
                        top_k=40,
                    ),
                )
            return response.text.strip()

        # Run sync call in thread pool to avoid blocking event loop
        return await asyncio.to_thread(_call)

    async def translate_stream(
        self,
        text: str,
        *,
        context_lines: list[str] | None = None,
        update_context: bool = True,
    ) -> AsyncIterator[str]:
        """Stream translation tokens as they are generated."""
        if not text.strip():
            return

        prompt = self._build_user_prompt(text, context_lines=context_lines)

        if self._provider == "gemini":
            full_text = ""
            async for chunk in self._translate_gemini_stream(prompt):
                full_text += chunk
                yield chunk

            # Update context after streaming completes
            should_update_context = update_context and context_lines is None
            if should_update_context:
                self._context_buffer.append(text)
                if len(self._context_buffer) > self._context_window_size:
                    self._context_buffer.pop(0)
                self._slide_window.append(full_text)
                if len(self._slide_window) > self._context_window_size:
                    self._slide_window.pop(0)
        else:
            # OpenAI streaming
            full_text = ""
            async for chunk in self._translate_openai_stream(prompt):
                full_text += chunk
                yield chunk

            should_update_context = update_context and context_lines is None
            if should_update_context:
                self._context_buffer.append(text)
                if len(self._context_buffer) > self._context_window_size:
                    self._context_buffer.pop(0)
                self._slide_window.append(full_text)
                if len(self._slide_window) > self._context_window_size:
                    self._slide_window.pop(0)

    async def _translate_gemini_stream(self, user_prompt: str) -> AsyncIterator[str]:
        """Stream Gemini API response token by token using async API."""
        from google.genai import types

        client = self._get_gemini_client()
        cache_name = self._gemini_cache_name

        if cache_name:
            config = types.GenerateContentConfig(
                cached_content=cache_name,
                temperature=0.2,
                max_output_tokens=512,
                top_p=0.95,
                top_k=40,
            )
        else:
            config = types.GenerateContentConfig(
                system_instruction=self._get_system_prompt(),
                temperature=0.2,
                max_output_tokens=512,
                top_p=0.95,
                top_k=40,
            )

        # Use async streaming API - await the coroutine to get the async iterator
        stream = await client.aio.models.generate_content_stream(
            model=self._model_name,
            contents=user_prompt,
            config=config,
        )
        async for chunk in stream:
            if chunk.text:
                yield chunk.text

    async def _translate_openai_stream(self, user_prompt: str) -> AsyncIterator[str]:
        """Stream OpenAI API response token by token."""
        client = self._get_openai_client()

        stream = await client.chat.completions.create(
            model=self._model_name,
            messages=[
                {"role": "system", "content": self._get_system_prompt()},
                {"role": "user", "content": user_prompt},
            ],
            temperature=0.3,
            max_tokens=512,
            stream=True,
        )

        async for chunk in stream:
            if chunk.choices and chunk.choices[0].delta.content:
                yield chunk.choices[0].delta.content

    async def _translate_openai(self, user_prompt: str) -> str:
        """Direct OpenAI API call."""
        client = self._get_openai_client()

        response = await client.chat.completions.create(
            model=self._model_name,
            messages=[
                {"role": "system", "content": self._get_system_prompt()},
                {"role": "user", "content": user_prompt},
            ],
            temperature=0.3,
            max_tokens=512,
        )
        return response.choices[0].message.content.strip()

    async def summarize_texts(self, texts: list[str]) -> str:
        """Summarize multiple texts for batch translation."""
        if not texts:
            return ""
        if len(texts) == 1:
            return texts[0]

        # Simple concatenation with separator for speed
        return " ... ".join(texts)

    def clear_context(self) -> None:
        """Clear the context buffer."""
        self._context_buffer.clear()
        self._slide_window.clear()

    def refresh_cache(self) -> None:
        """Invalidate cached system prompt and Gemini cache."""
        self._system_prompt_cache = None
        self._invalidate_gemini_cache()
