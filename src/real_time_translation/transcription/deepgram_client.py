"""Deepgram WebSocket client for real-time transcription."""

import asyncio
import contextlib
from collections.abc import AsyncIterator, Callable
from dataclasses import dataclass
from typing import Any

from deepgram import DeepgramClient


@dataclass
class TranscriptionResult:
    """Result from transcription service."""

    text: str
    is_final: bool
    confidence: float
    start_time: float
    end_time: float

    @property
    def is_low_confidence(self) -> bool:
        """Check if confidence is below threshold."""
        return self.confidence < 0.7


class DeepgramTranscriber:
    """Deepgram WebSocket client for real-time transcription.
    
    Uses Deepgram's streaming API to transcribe audio in real-time.
    """

    def __init__(
        self,
        api_key: str,
        language: str = "en",
        model: str = "nova-2-general",
        punctuate: bool = True,
        smart_format: bool = True,
        interim_results: bool = True,
        endpointing: int | None = 500,
    ) -> None:
        """Initialize Deepgram transcriber.
        
        Args:
            api_key: Deepgram API key
            language: Language code for transcription
            model: Deepgram model to use
            punctuate: Whether to add punctuation
            smart_format: Whether to use Deepgram smart formatting
            interim_results: Whether to receive interim (non-final) results
            endpointing: Silence timeout in ms to finalize transcription
        """
        self._api_key = api_key
        self._language = language
        self._model = model
        self._punctuate = punctuate
        self._smart_format = smart_format
        self._interim_results = interim_results
        self._endpointing = endpointing
        
        self._client: DeepgramClient | None = None
        self._connection: Any = None
        self._running = False
        self._result_queue: asyncio.Queue[TranscriptionResult] = asyncio.Queue()
        self._on_transcript: Callable[[TranscriptionResult], None] | None = None

    async def connect(self) -> None:
        """Establish WebSocket connection to Deepgram."""
        self._client = DeepgramClient(api_key=self._api_key)
        
        # Deepgram SDK v5 uses different API
        options = {
            "model": self._model,
            "language": self._language,
            "punctuate": self._punctuate,
            "smart_format": self._smart_format,
            "interim_results": self._interim_results,
            "encoding": "linear16",
            "sample_rate": 16000,
            "channels": 1,
        }
        if self._endpointing is not None:
            options["endpointing"] = self._endpointing

        self._connection = self._client.listen.websocket.v("1")
        
        # Register event handlers
        self._connection.on("Results", self._on_message)
        self._connection.on("Error", self._on_error)
        
        await self._connection.start(options)
        self._running = True

    async def disconnect(self) -> None:
        """Close WebSocket connection."""
        self._running = False
        if self._connection:
            await self._connection.finish()
            self._connection = None

    async def send_audio(self, audio_data: bytes) -> None:
        """Send audio data to Deepgram for transcription.
        
        Args:
            audio_data: Raw PCM audio data (16-bit, 16kHz, mono)
        """
        if self._connection and self._running:
            await self._connection.send(audio_data)

    def set_callback(
        self, callback: Callable[[TranscriptionResult], None]
    ) -> None:
        """Set callback for transcription results.
        
        Args:
            callback: Function to call with transcription results
        """
        self._on_transcript = callback

    async def results(self) -> AsyncIterator[TranscriptionResult]:
        """Async iterator for transcription results.
        
        Yields:
            TranscriptionResult objects
        """
        while self._running:
            try:
                result = await asyncio.wait_for(
                    self._result_queue.get(), timeout=1.0
                )
                yield result
            except TimeoutError:
                continue

    def _on_message(self, _self: Any, result: Any, **_kwargs: Any) -> None:
        """Handle transcription message from Deepgram.
        
        Args:
            result: Deepgram transcription result
        """
        try:
            channel = result.channel
            alternative = channel.alternatives[0]
            
            if not alternative.transcript:
                return

            transcript_result = TranscriptionResult(
                text=alternative.transcript,
                is_final=result.is_final,
                confidence=alternative.confidence,
                start_time=result.start,
                end_time=result.start + result.duration,
            )

            # Put result in queue for async iteration
            with contextlib.suppress(asyncio.QueueFull):
                self._result_queue.put_nowait(transcript_result)

            # Call callback if set
            if self._on_transcript:
                self._on_transcript(transcript_result)

        except (AttributeError, IndexError):
            pass  # Ignore malformed results

    def _on_error(self, _self: Any, error: Any, **_kwargs: Any) -> None:
        """Handle error from Deepgram.
        
        Args:
            error: Error information
        """
        print(f"Deepgram error: {error}")
