"""Deepgram WebSocket client for real-time transcription."""

import asyncio
import contextlib
import time
from collections.abc import AsyncIterator, Callable
from dataclasses import dataclass
from typing import Any

from deepgram import AsyncDeepgramClient
from deepgram.listen.v1.types import ListenV1KeepAlive


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
        keepalive_interval: float = 5.0,
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
        self._keepalive_interval = keepalive_interval

        self._client: AsyncDeepgramClient | None = None
        self._connection_cm: Any = None
        self._connection: Any = None
        self._listener_task: asyncio.Task[None] | None = None
        self._keepalive_task: asyncio.Task[None] | None = None
        self._last_audio_at = 0.0
        self._running = False
        self._result_queue: asyncio.Queue[TranscriptionResult] = asyncio.Queue()
        self._on_transcript: Callable[[TranscriptionResult], None] | None = None

    async def connect(self) -> None:
        """Establish WebSocket connection to Deepgram."""
        self._client = AsyncDeepgramClient(api_key=self._api_key)

        def _bool_str(value: bool) -> str:
            return "true" if value else "false"

        options = {
            "model": self._model,
            "language": self._language,
            "punctuate": _bool_str(self._punctuate),
            "smart_format": _bool_str(self._smart_format),
            "interim_results": _bool_str(self._interim_results),
            "encoding": "linear16",
            "sample_rate": "16000",
            "channels": "1",
        }
        if self._endpointing is not None:
            options["endpointing"] = str(self._endpointing)

        self._connection_cm = self._client.listen.v1.connect(**options)
        self._connection = await self._connection_cm.__aenter__()
        self._running = True
        self._last_audio_at = time.monotonic()
        self._listener_task = asyncio.create_task(self._listen())
        self._keepalive_task = asyncio.create_task(self._keepalive_loop())

    async def disconnect(self) -> None:
        """Close WebSocket connection."""
        self._running = False
        if self._listener_task:
            self._listener_task.cancel()
            await asyncio.gather(self._listener_task, return_exceptions=True)
            self._listener_task = None
        if self._keepalive_task:
            self._keepalive_task.cancel()
            await asyncio.gather(self._keepalive_task, return_exceptions=True)
            self._keepalive_task = None
        if self._connection_cm:
            await self._connection_cm.__aexit__(None, None, None)
            self._connection_cm = None
            self._connection = None

    async def send_audio(self, audio_data: bytes) -> None:
        """Send audio data to Deepgram for transcription.

        Args:
            audio_data: Raw PCM audio data (16-bit, 16kHz, mono)
        """
        if self._connection and self._running:
            self._last_audio_at = time.monotonic()
            await self._connection.send_media(audio_data)

    def set_callback(self, callback: Callable[[TranscriptionResult], None]) -> None:
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
                result = await asyncio.wait_for(self._result_queue.get(), timeout=1.0)
                yield result
            except TimeoutError:
                continue

    async def _listen(self) -> None:
        if not self._connection:
            return
        try:
            async for result in self._connection:
                self._handle_message(result)
        except asyncio.CancelledError:
            pass
        except Exception as exc:  # noqa: BLE001
            self._on_error(exc)

    async def _keepalive_loop(self) -> None:
        if not self._connection:
            return
        try:
            while self._running:
                await asyncio.sleep(self._keepalive_interval)
                if not self._connection or not self._running:
                    continue
                idle_time = time.monotonic() - self._last_audio_at
                if idle_time < self._keepalive_interval:
                    continue
                await self._connection.send_keep_alive(
                    ListenV1KeepAlive(type="KeepAlive")
                )
        except asyncio.CancelledError:
            pass
        except Exception as exc:  # noqa: BLE001
            self._on_error(exc)

    def _handle_message(self, result: Any) -> None:
        """Handle transcription message from Deepgram.

        Args:
            result: Deepgram transcription result
        """
        try:
            if getattr(result, "type", None) != "Results":
                return

            channel = result.channel
            alternative = channel.alternatives[0]

            if not alternative.transcript:
                return

            transcript_result = TranscriptionResult(
                text=alternative.transcript,
                is_final=bool(result.is_final),
                confidence=float(alternative.confidence),
                start_time=float(result.start),
                end_time=float(result.start + result.duration),
            )

            # Put result in queue for async iteration
            with contextlib.suppress(asyncio.QueueFull):
                self._result_queue.put_nowait(transcript_result)

            # Call callback if set
            if self._on_transcript:
                self._on_transcript(transcript_result)

        except (AttributeError, IndexError):
            pass  # Ignore malformed results

    def _on_error(self, error: Any) -> None:
        """Handle error from Deepgram.

        Args:
            error: Error information
        """
        print(f"Deepgram error: {error}")
