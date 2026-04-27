"""LLM-based translator with Gemini/OpenAI support and context caching."""

from __future__ import annotations

import asyncio
import contextlib
import re
from collections.abc import AsyncIterator
from dataclasses import dataclass
from datetime import timedelta
from pathlib import Path
from typing import Any, Literal

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import HumanMessage, SystemMessage
from pydantic import BaseModel, Field

from real_time_translation.translation.dictionary import TermDictionary


class TranslationLLMOutput(BaseModel):
    """Structured output returned by the LLM."""

    latest_slide: str = Field(
        ...,
        description=(
            "Translated text for the current <target> only. Do not include any extra "
            "commentary."
        ),
    )
    kept_terms: list[str] = Field(
        default_factory=list,
        description=(
            "Source terms intentionally kept unchanged because they are proper nouns, "
            "acronyms, code identifiers, or ambiguous/unknown."
        ),
    )


@dataclass(frozen=True)
class TranslationOutput:
    """Application-level translation output."""

    latest_slide: str
    kept_terms: list[str]
    slide_window: list[str]


class LLMTranslator:
    """Translator using Gemini or OpenAI with contextual prompting."""

    SYSTEM_PROMPT_TEMPLATE = """You are a professional simultaneous interpreter translating from {source_language} to {target_language}.

You will be provided with <context> (previous utterances) and a <target> (the current text to translate).

Strict Rules:
1. TRANSLATE TARGET ONLY: Translate ONLY the text inside <target>. Use <context> purely to resolve pronouns, understand the ongoing grammatical structure, and correct phonetic ASR errors (e.g., 'laundry model' -> 'language model', 'three d deficient' -> '3D diffusion').
2. NO FORCED CLOSURES: The <target> is often a mid-sentence fragment from a live stream. DO NOT add terminal punctuation (e.g., periods, '。', 'です', 'ます') unless the <target> text clearly concludes a complete grammatical thought. 
3. USE CONTINUATIONS: If the <target> is a fragment, translate it as a continuation (e.g., using noun phrases, 'て' forms, or dangling particles) so it flows naturally into whatever text might come next.
4. PRESERVE TERMINOLOGY: Keep proper nouns, acronyms, and code identifiers EXACTLY as they appear. Do not translate, transliterate, or normalize them. If a term is ambiguous or unknown, keep it unchanged.
5. IGNORE PADDING: Ignore any content inside <cache_padding>...</cache_padding>.

Maintain the original tone and style.
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
        """Initialize LLM translator.

        Args:
            provider: LLM provider ("gemini" or "openai")
            api_key: API key for the provider
            model: Model name to use
            source_language: Source language name
            target_language: Target language name
            dictionary_path: Optional path to CSV dictionary file
            context_window_size: Number of previous lines to keep as context
        """
        self._provider = provider
        self._api_key = api_key
        self._model_name = model
        self._source_language = source_language
        self._target_language = target_language
        self._context_window_size = context_window_size

        self._openai_llm: BaseChatModel | None = None
        self._gemini_llm: BaseChatModel | None = None
        self._openai_structured_llm: Any | None = None
        self._gemini_structured_llm: Any | None = None
        self._context_buffer: list[str] = []
        self._slide_window: list[str] = []
        self._system_prompt_cache: str | None = None

        self._gemini_client: Any | None = None
        self._gemini_cache_name: str | None = None
        self._gemini_cache_ttl = timedelta(hours=12)

        # Load dictionary if provided
        self._dictionary = TermDictionary()
        if dictionary_path:
            self.load_dictionary(dictionary_path)

    def load_dictionary(self, path: Path | str) -> int:
        """Load terminology dictionary from CSV file.

        Args:
            path: Path to CSV file (format: source_term,target_term,notes)

        Returns:
            Number of entries loaded
        """
        count = self._dictionary.load_csv(path)
        self._system_prompt_cache = None
        self._invalidate_gemini_cache()
        return count

    @property
    def dictionary(self) -> TermDictionary:
        """Get the terminology dictionary."""
        return self._dictionary

    async def prepare(self) -> None:
        """Warm up translator state (e.g., create Gemini cache)."""
        if self._provider == "gemini":
            await asyncio.to_thread(self._ensure_gemini_cache)

    def refresh_cache(self) -> None:
        """Invalidate cached system prompt and Gemini cache."""
        self._system_prompt_cache = None
        self._invalidate_gemini_cache()

    def _invalidate_gemini_cache(self) -> None:
        if self._gemini_cache_name and self._gemini_client:
            with contextlib.suppress(Exception):
                self._gemini_client.caches.delete(name=self._gemini_cache_name)

        self._gemini_cache_name = None
        self._gemini_llm = None
        self._gemini_structured_llm = None

    def _get_openai_llm(self) -> BaseChatModel:
        """Get or create LLM instance for OpenAI.

        Returns:
            LangChain chat model
        """
        if self._openai_llm is None:
            from langchain_openai import ChatOpenAI

            self._openai_llm = ChatOpenAI(
                model=self._model_name,
                api_key=self._api_key,
                temperature=0.3,
            )
        return self._openai_llm

    def _get_system_prompt(self) -> str:
        """Get system prompt with language settings and dictionary.

        Returns:
            Formatted system prompt
        """
        if self._system_prompt_cache is not None:
            return self._system_prompt_cache

        dictionary_section = ""
        if self._dictionary:
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
        if context_lines is None:
            context_lines = self._context_buffer[-self._context_window_size :]
        else:
            context_lines = context_lines[-self._context_window_size :]
        context_block = "\n".join(context_lines)
        return f"<context>\n{context_block}\n</context>\n<target>\n{text}\n</target>"

    def _get_gemini_client(self) -> Any:
        if self._gemini_client is None:
            from google import genai

            self._gemini_client = genai.Client(api_key=self._api_key)
        return self._gemini_client

    def _create_gemini_cache(self) -> str:
        from google.genai import types

        client = self._get_gemini_client()
        base_system_prompt = self._get_system_prompt()
        ttl_seconds = int(self._gemini_cache_ttl.total_seconds())

        def _create(system_instruction: str) -> str:
            config = types.CreateCachedContentConfig(
                display_name="real-time-translation-system",
                system_instruction=system_instruction,
                contents=None,
                ttl=f"{ttl_seconds}s",
            )
            cache = client.caches.create(model=self._model_name, config=config)
            return cache.name

        try:
            return _create(base_system_prompt)
        except Exception as exc:
            message = str(exc)
            match = re.search(
                r"total_token_count=(\d+), min_total_token_count=(\d+)",
                message,
            )
            if "Cached content is too small" not in message or match is None:
                raise

            total = int(match.group(1))
            minimum = int(match.group(2))
            extra = max(0, minimum - total) + 256
            padding = (
                "\n\n<cache_padding>\n"
                "IGNORE EVERYTHING IN THIS TAG. It only exists to satisfy the "
                "minimum cached-content token requirement.\n"
                + ("PAD " * extra)
                + "\n</cache_padding>"
            )
            return _create(base_system_prompt + padding)

    def _ensure_gemini_cache(self) -> str:
        if self._gemini_cache_name is None:
            self._gemini_cache_name = self._create_gemini_cache()
        return self._gemini_cache_name

    def _get_gemini_llm(self) -> BaseChatModel:
        if self._gemini_llm is None:
            from langchain_google_genai import ChatGoogleGenerativeAI

            cache_name = self._ensure_gemini_cache()
            self._gemini_llm = ChatGoogleGenerativeAI(
                model=self._model_name,
                google_api_key=self._api_key,
                temperature=0.3,
                cached_content=cache_name,
            )
        return self._gemini_llm

    def _get_openai_structured_llm(self) -> Any:
        if self._openai_structured_llm is None:
            self._openai_structured_llm = self._get_openai_llm().with_structured_output(
                TranslationLLMOutput
            )
        return self._openai_structured_llm

    def _get_gemini_structured_llm(self) -> Any:
        if self._gemini_structured_llm is None:
            self._gemini_structured_llm = self._get_gemini_llm().with_structured_output(
                TranslationLLMOutput
            )
        return self._gemini_structured_llm

    async def translate(
        self,
        text: str,
        *,
        context_lines: list[str] | None = None,
        update_context: bool = True,
    ) -> TranslationOutput:
        """Translate text using LLM.

        Args:
            text: Text to translate
            context_lines: Optional explicit context lines (stateless mode)
            update_context: Whether to update internal context buffers

        Returns:
            Translation output including the latest slide and current slide window
        """
        if not text.strip():
            return TranslationOutput(latest_slide="", kept_terms=[], slide_window=[])

        prompt = self._build_user_prompt(text, context_lines=context_lines)

        if self._provider == "gemini":
            llm = self._get_gemini_structured_llm()
            output = await llm.ainvoke([HumanMessage(content=prompt)])
        else:
            llm = self._get_openai_structured_llm()
            messages = [
                SystemMessage(content=self._get_system_prompt()),
                HumanMessage(content=prompt),
            ]
            output = await llm.ainvoke(messages)

        should_update_context = update_context and context_lines is None
        if should_update_context:
            self._context_buffer.append(text)
            if len(self._context_buffer) > self._context_window_size:
                self._context_buffer.pop(0)

        translation = output.latest_slide.strip()
        kept_terms = list(output.kept_terms or [])

        if should_update_context:
            self._slide_window.append(translation)
            if len(self._slide_window) > self._context_window_size:
                self._slide_window.pop(0)

        return TranslationOutput(
            latest_slide=translation,
            kept_terms=kept_terms,
            slide_window=list(self._slide_window),
        )

    async def translate_stream(self, text: str) -> AsyncIterator[str]:
        """Translate text with streaming output.

        Args:
            text: Text to translate

        Yields:
            Translation chunks
        """
        if not text.strip():
            return

        result = await self.translate(text)
        yield result.latest_slide

    def clear_context(self) -> None:
        """Clear the context buffer."""
        self._context_buffer.clear()
        self._slide_window.clear()
