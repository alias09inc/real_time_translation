"""Translation module for real-time text translation."""

from real_time_translation.translation.dictionary import DictionaryEntry, TermDictionary
from real_time_translation.translation.llm_translator import LLMTranslator

__all__ = [
    "DictionaryEntry",
    "LLMTranslator",
    "TermDictionary",
]
