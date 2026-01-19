"""LLM-based translator with Gemini/OpenAI support and context caching."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from datetime import timedelta
from pathlib import Path
from typing import Any, Literal

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import HumanMessage, SystemMessage

from real_time_translation.translation.dictionary import TermDictionary


class LLMTranslator:
    """Translator using Gemini or OpenAI with contextual prompting."""

    SYSTEM_PROMPT_TEMPLATE = """You are a professional simultaneous interpreter.
Translate from {source_language} to {target_language}.
Output ONLY the translated text. Do not add notes or explanations.
If confidence indicators like [uncertain: ...] appear, infer meaning from context.
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
        self._context_buffer: list[str] = []
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
            try:
                self._gemini_client.caches.delete(name=self._gemini_cache_name)
            except Exception:
                pass

        self._gemini_cache_name = None
        self._gemini_llm = None

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

    def _build_user_prompt(self, text: str) -> str:
        context_lines = self._context_buffer[-self._context_window_size :]
        context_block = "\n".join(context_lines)
        return (
            "<context>\n"
            f"{context_block}\n"
            "</context>\n"
            "<target>\n"
            f"{text}\n"
            "</target>"
        )

    def _get_gemini_client(self) -> Any:
        if self._gemini_client is None:
            from google import genai

            self._gemini_client = genai.Client(api_key=self._api_key)
        return self._gemini_client

    def _create_gemini_cache(self) -> str:
        from google.genai import types

        client = self._get_gemini_client()
        system_prompt = self._get_system_prompt()
        ttl_seconds = int(self._gemini_cache_ttl.total_seconds())

        config = types.CreateCachedContentConfig(
            display_name="real-time-translation-system",
            system_instruction=system_prompt,
            contents=None,
            ttl=f"{ttl_seconds}s",
        )
        cache = client.caches.create(model=self._model_name, config=config)
        return cache.name

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

    async def translate(self, text: str) -> str:
        """Translate text using LLM.

        Args:
            text: Text to translate

        Returns:
            Translated text
        """
        if not text.strip():
            return ""

        prompt = self._build_user_prompt(text)

        if self._provider == "gemini":
            llm = self._get_gemini_llm()
            response = await llm.ainvoke([HumanMessage(content=prompt)])
            translation = str(response.content or "")
        else:
            llm = self._get_openai_llm()
            messages = [
                SystemMessage(content=self._get_system_prompt()),
                HumanMessage(content=prompt),
            ]
            response = await llm.ainvoke(messages)
            translation = str(response.content)

        self._context_buffer.append(text)
        if len(self._context_buffer) > self._context_window_size:
            self._context_buffer.pop(0)

        return translation

    async def translate_stream(self, text: str) -> AsyncIterator[str]:
        """Translate text with streaming output.

        Args:
            text: Text to translate

        Yields:
            Translation chunks
        """
        if not text.strip():
            return

        prompt = self._build_user_prompt(text)
        full_response = ""

        if self._provider == "gemini":
            llm = self._get_gemini_llm()
            async for chunk in llm.astream([HumanMessage(content=prompt)]):
                if chunk.content is None:
                    continue
                content = str(chunk.content)
                if content:
                    full_response += content
                    yield content
        else:
            llm = self._get_openai_llm()
            messages = [
                SystemMessage(content=self._get_system_prompt()),
                HumanMessage(content=prompt),
            ]
            async for chunk in llm.astream(messages):
                if chunk.content is None:
                    continue
                content = str(chunk.content)
                if content:
                    full_response += content
                    yield content

        self._context_buffer.append(text)
        if len(self._context_buffer) > self._context_window_size:
            self._context_buffer.pop(0)

    def clear_context(self) -> None:
        """Clear the context buffer."""
        self._context_buffer.clear()
