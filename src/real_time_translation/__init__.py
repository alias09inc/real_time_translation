"""Real-time translation package."""

from real_time_translation.config import Config
from real_time_translation.pipeline import TranslationPipeline, TranslationResult

__version__ = "0.1.0"

__all__ = [
    "Config",
    "TranslationPipeline",
    "TranslationResult",
]
