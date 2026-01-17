"""LLM-based translator using LangChain."""

from collections.abc import AsyncIterator
from pathlib import Path
from typing import Literal

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import HumanMessage, SystemMessage

from real_time_translation.translation.dictionary import TermDictionary


class LLMTranslator:
    """Translator using LangChain with Gemini or OpenAI."""

    SYSTEM_PROMPT_TEMPLATE = """You are a professional translator. 
Translate the following text from {source_language} to {target_language}.
Only output the translation, nothing else.
If confidence indicators like [MASK] appear, try to infer the meaning from context.
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
    ) -> None:
        """Initialize LLM translator.
        
        Args:
            provider: LLM provider ("gemini" or "openai")
            api_key: API key for the provider
            model: Model name to use
            source_language: Source language name
            target_language: Target language name
            dictionary_path: Optional path to CSV dictionary file
        """
        self._provider = provider
        self._api_key = api_key
        self._model_name = model
        self._source_language = source_language
        self._target_language = target_language
        self._llm: BaseChatModel | None = None
        self._context_buffer: list[str] = []
        self._max_context_lines = 5
        
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
        # Clear LLM cache to regenerate system prompt with dictionary
        self._llm = None
        return count

    @property
    def dictionary(self) -> TermDictionary:
        """Get the terminology dictionary."""
        return self._dictionary

    def _get_llm(self) -> BaseChatModel:
        """Get or create LLM instance.
        
        Returns:
            LangChain chat model
        """
        if self._llm is None:
            if self._provider == "gemini":
                from langchain_google_genai import ChatGoogleGenerativeAI
                self._llm = ChatGoogleGenerativeAI(
                    model=self._model_name,
                    google_api_key=self._api_key,
                    temperature=0.3,
                )
            else:
                from langchain_openai import ChatOpenAI
                self._llm = ChatOpenAI(
                    model=self._model_name,
                    api_key=self._api_key,
                    temperature=0.3,
                )
        return self._llm

    def _get_system_prompt(self) -> str:
        """Get system prompt with language settings and dictionary.
        
        Returns:
            Formatted system prompt
        """
        dictionary_section = ""
        if self._dictionary:
            dictionary_section = "\n\n" + self._dictionary.format_for_prompt()
        
        return self.SYSTEM_PROMPT_TEMPLATE.format(
            source_language=self._source_language,
            target_language=self._target_language,
            dictionary_section=dictionary_section,
        )

    async def translate(self, text: str) -> str:
        """Translate text using LLM.
        
        Args:
            text: Text to translate
            
        Returns:
            Translated text
        """
        if not text.strip():
            return ""

        llm = self._get_llm()
        
        # Build context from previous translations
        context = ""
        if self._context_buffer:
            prev_context = "\n".join(self._context_buffer[-3:])
            context = f"\n[Previous context:]\n{prev_context}\n\n"

        messages = [
            SystemMessage(content=self._get_system_prompt()),
            HumanMessage(content=f"{context}[Translate this:]\n{text}"),
        ]

        response = await llm.ainvoke(messages)
        translation = str(response.content)

        # Update context buffer
        self._context_buffer.append(f"{text} → {translation}")
        if len(self._context_buffer) > self._max_context_lines:
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

        llm = self._get_llm()

        messages = [
            SystemMessage(content=self._get_system_prompt()),
            HumanMessage(content=text),
        ]

        full_response = ""
        async for chunk in llm.astream(messages):
            content = str(chunk.content)
            full_response += content
            yield content

        # Update context buffer
        self._context_buffer.append(f"{text} → {full_response}")
        if len(self._context_buffer) > self._max_context_lines:
            self._context_buffer.pop(0)

    def clear_context(self) -> None:
        """Clear the context buffer."""
        self._context_buffer.clear()
