"""Translation pipeline for real-time audio translation."""

import asyncio
import contextlib
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from real_time_translation.audio.capture import AudioCapture
from real_time_translation.config import Config
from real_time_translation.transcription.deepgram_client import (
    DeepgramTranscriber,
    TranscriptionResult,
)
from real_time_translation.translation.llm_translator import LLMTranslator


@dataclass
class TranslationResult:
    """Complete translation result."""

    original_text: str
    translated_text: str
    is_final: bool
    confidence: float
    kept_terms: list[str] = field(default_factory=list)
    slide_window: list[str] = field(default_factory=list)


@dataclass
class QueuedTranscription:
    """Queued transcription with masked text when needed."""

    original: TranscriptionResult
    text_for_translation: str


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
            model=config.deepgram_model,
            interim_results=config.deepgram_interim_results,
            smart_format=config.deepgram_smart_format,
            endpointing=config.deepgram_endpointing,
            utterance_end_ms=config.deepgram_utterance_end_ms,
            vad_events=config.deepgram_vad_events,
            emit_interim=True,  # Emit interim results for real-time UI
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
            context_window_size=config.context_window_size,
        )

        self._running = False
        self._on_result: Callable[[TranslationResult], None] | None = None
        self._tasks: list[asyncio.Task[Any]] = []
        self._transcription_queue: asyncio.Queue[QueuedTranscription] = asyncio.Queue(
            maxsize=config.translation_queue_size
        )

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

    def set_callback(self, callback: Callable[[TranslationResult], None]) -> None:
        """Set callback for translation results.

        Args:
            callback: Function to call with results
        """
        self._on_result = callback

    async def start(self) -> None:
        """Start the translation pipeline."""
        self._running = True

        # Initialize translator (e.g., Gemini context cache)
        await self._translator.prepare()

        # Connect to Deepgram
        await self._transcriber.connect()

        # Start audio capture
        await self._audio_capture.start()

        # Start processing tasks
        self._tasks = [
            asyncio.create_task(self._audio_to_transcription()),
            asyncio.create_task(self._collect_transcriptions()),
            asyncio.create_task(self._translation_worker()),
        ]

    async def stop(self) -> None:
        """Stop the translation pipeline."""
        # First, stop audio capture to signal no more audio
        await self._audio_capture.stop()

        # Finalize the transcriber (signal end of audio stream)
        await self._transcriber.finalize()

        self._running = False

        # Cancel all tasks
        for task in self._tasks:
            task.cancel()

        # Wait for tasks to complete
        await asyncio.gather(*self._tasks, return_exceptions=True)
        self._tasks.clear()

        # Disconnect transcriber
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

    async def _collect_transcriptions(self) -> None:
        """Collect transcription results into a queue."""
        try:
            async for result in self._transcriber.results():
                if not self._running:
                    break

                text = result.text.strip()
                if not text:
                    continue

                # Emit interim results to UI (without translation)
                if not result.is_final:
                    if self._on_result:
                        interim_result = TranslationResult(
                            original_text=text,
                            translated_text="",
                            is_final=False,
                            confidence=result.confidence,
                        )
                        self._on_result(interim_result)
                    continue

                # Handle low confidence by masking for translation input
                masked_text = (
                    f"[uncertain: {text}]" if result.is_low_confidence else text
                )

                if self._transcription_queue.full():
                    with contextlib.suppress(asyncio.QueueEmpty):
                        self._transcription_queue.get_nowait()

                queued = QueuedTranscription(
                    original=result,
                    text_for_translation=masked_text,
                )
                with contextlib.suppress(asyncio.QueueFull):
                    self._transcription_queue.put_nowait(queued)
        except asyncio.CancelledError:
            pass

    async def _translation_worker(self) -> None:
        """Consume queued transcriptions and translate."""
        try:
            while self._running:
                queued = await self._transcription_queue.get()
                output = await self._translator.translate(queued.text_for_translation)
                translation_result = TranslationResult(
                    original_text=queued.original.text,
                    translated_text=output.latest_slide,
                    is_final=queued.original.is_final,
                    confidence=queued.original.confidence,
                    kept_terms=output.kept_terms,
                    slide_window=output.slide_window,
                )
                if self._on_result:
                    self._on_result(translation_result)
        except asyncio.CancelledError:
            pass

    def clear_context(self) -> None:
        """Clear translation context buffer."""
        self._translator.clear_context()

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
