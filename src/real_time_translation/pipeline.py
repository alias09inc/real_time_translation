"""Translation pipeline for real-time audio translation."""

import asyncio
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from real_time_translation.audio.capture import AudioCapture
from real_time_translation.config import Config
from real_time_translation.transcription.deepgram_client import DeepgramTranscriber
from real_time_translation.translation.llm_translator import LLMTranslator


@dataclass
class TranslationResult:
    """Complete translation result."""

    original_text: str
    translated_text: str
    is_final: bool
    confidence: float


class TranslationPipeline:
    """Pipeline for real-time audio translation.
    
    Coordinates audio capture, transcription, and translation.
    """

    def __init__(
        self,
        config: Config,
        audio_capture: AudioCapture,
    ) -> None:
        """Initialize translation pipeline.
        
        Args:
            config: Application configuration
            audio_capture: Audio capture instance
        """
        self._config = config
        self._audio_capture = audio_capture
        
        # Initialize transcriber
        self._transcriber = DeepgramTranscriber(
            api_key=config.deepgram_api_key,
            language=config.source_language,
        )
        
        # Initialize translator
        api_key = (
            config.google_api_key 
            if config.llm_provider == "gemini" 
            else config.openai_api_key
        )
        model = (
            config.gemini_model 
            if config.llm_provider == "gemini" 
            else config.openai_model
        )
        
        self._translator = LLMTranslator(
            provider=config.llm_provider,  # type: ignore
            api_key=api_key or "",
            model=model,
            source_language=self._language_name(config.source_language),
            target_language=self._language_name(config.target_language),
            dictionary_path=config.dictionary_path,
        )
        
        self._running = False
        self._on_result: Callable[[TranslationResult], None] | None = None
        self._tasks: list[asyncio.Task[Any]] = []

    @staticmethod
    def _language_name(code: str) -> str:
        """Convert language code to language name.
        
        Args:
            code: Language code (e.g., "en", "ja")
            
        Returns:
            Language name
        """
        names = {
            "en": "English",
            "ja": "Japanese",
            "zh": "Chinese",
            "ko": "Korean",
            "es": "Spanish",
            "fr": "French",
            "de": "German",
        }
        return names.get(code, code)

    def set_callback(
        self, callback: Callable[[TranslationResult], None]
    ) -> None:
        """Set callback for translation results.
        
        Args:
            callback: Function to call with results
        """
        self._on_result = callback

    async def start(self) -> None:
        """Start the translation pipeline."""
        self._running = True
        
        # Connect to Deepgram
        await self._transcriber.connect()
        
        # Start audio capture
        await self._audio_capture.start()
        
        # Start processing tasks
        self._tasks = [
            asyncio.create_task(self._audio_to_transcription()),
            asyncio.create_task(self._transcription_to_translation()),
        ]

    async def stop(self) -> None:
        """Stop the translation pipeline."""
        self._running = False
        
        # Cancel all tasks
        for task in self._tasks:
            task.cancel()
        
        # Wait for tasks to complete
        await asyncio.gather(*self._tasks, return_exceptions=True)
        self._tasks.clear()
        
        # Stop components
        await self._audio_capture.stop()
        await self._transcriber.disconnect()

    async def _audio_to_transcription(self) -> None:
        """Send audio data to transcriber."""
        try:
            async for audio_chunk in self._audio_capture.stream():
                if not self._running:
                    break
                await self._transcriber.send_audio(audio_chunk)
        except asyncio.CancelledError:
            pass

    async def _transcription_to_translation(self) -> None:
        """Process transcription and translate."""
        try:
            async for result in self._transcriber.results():
                if not self._running:
                    break
                
                # Only translate final results or high-confidence interim
                if not result.is_final and result.is_low_confidence:
                    continue
                
                # Handle low confidence by masking
                text = result.text
                if result.is_low_confidence:
                    text = f"[uncertain: {text}]"
                
                # Translate
                translated = await self._translator.translate(text)
                
                # Emit result
                translation_result = TranslationResult(
                    original_text=result.text,
                    translated_text=translated,
                    is_final=result.is_final,
                    confidence=result.confidence,
                )
                
                if self._on_result:
                    self._on_result(translation_result)
                    
        except asyncio.CancelledError:
            pass

    async def run(self) -> None:
        """Run the pipeline until stopped."""
        await self.start()
        try:
            while self._running:
                await asyncio.sleep(0.1)
        except asyncio.CancelledError:
            pass
        finally:
            await self.stop()
