"""Translation pipeline for real-time audio translation."""

import asyncio
import time
from collections import deque
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from real_time_translation.audio.capture import AudioCapture
from real_time_translation.config import Config
from real_time_translation.preload.auto_preload import preload_translator
from real_time_translation.transcription.deepgram_client import (
    DeepgramTranscriber,
    TranscriptionResult,
)
from real_time_translation.translation.llm_translator import LLMTranslator
from real_time_translation.translation.rate_limiter import RateLimiter


@dataclass
class TranslationResult:
    """Complete (or in-progress) translation result.

    `translated_text` is cumulative: while a translation is streaming in,
    consumers receive successive results with growing text and
    `is_translation_complete=False`, then one final result with the full
    text and `is_translation_complete=True`. Consumers that only care about
    finished translations should filter on `is_final and is_translation_complete`.
    """

    original_text: str
    translated_text: str
    is_final: bool
    confidence: float
    is_translation_complete: bool = True
    start_time: float | None = None
    end_time: float | None = None
    kept_terms: list[str] = field(default_factory=list)
    slide_window: list[str] = field(default_factory=list)
    # False for a soft-finalized mid-utterance chunk (see
    # `deepgram_max_interim_duration`): more text for the same utterance is
    # still coming, `translated_text` is the utterance's accumulated
    # translation so far, and consumers should keep updating the *current*
    # displayed line rather than committing a new one. True (the default)
    # means this is the real end of the utterance -- safe to commit as a
    # finished line and start fresh for the next one.
    is_utterance_end: bool = True
    # Stable grouping key shared by every result belonging to the same
    # spoken utterance, including across separate (non-coalesced)
    # translation calls -- unlike `start_time`, which differs per call.
    # Consumers that need to associate a continuation result with its
    # predecessor (rather than relying on `translated_text` already being
    # pipeline-accumulated) should key on this instead.
    utterance_id: int = 0


@dataclass
class QueuedTranscription:
    """Queued transcription with masked text when needed."""

    original: TranscriptionResult
    text_for_translation: str
    context: list[str]
    queued_at: float = field(default_factory=time.time)


class _FragmentQueue:
    """Bounded FIFO queue of `QueuedTranscription`, with peek support.

    Deliberately not `asyncio.Queue`: batch draining (see
    `TranslationPipeline._drain_batch`) needs to look at the next item and
    decide *without removing it* whether it fits the current batch's
    character budget. `asyncio.Queue` has no peek, and popping-then-maybe-
    pushing-back would reorder it behind items queued after it (`put_nowait`
    only appends), silently breaking chronological order. `put` is the only
    method that adds items and wakes waiters, so there's a single code path
    to reason about for wakeups (no lost-wakeup risk from a second entry
    point mutating the deque).
    """

    def __init__(self, maxsize: int) -> None:
        self._maxsize = max(1, maxsize)
        self._items: deque[QueuedTranscription] = deque()
        self._waiters: deque[asyncio.Future[None]] = deque()

    def put(self, item: QueuedTranscription) -> None:
        """Append, dropping the oldest not-yet-drained item if full."""
        if len(self._items) >= self._maxsize:
            self._items.popleft()
        self._items.append(item)
        while self._waiters:
            waiter = self._waiters.popleft()
            if not waiter.done():
                waiter.set_result(None)
                break

    async def get(self) -> QueuedTranscription:
        """Block until at least one item is available, then pop the front."""
        while not self._items:
            waiter: asyncio.Future[None] = asyncio.get_running_loop().create_future()
            self._waiters.append(waiter)
            try:
                await waiter
            except asyncio.CancelledError:
                waiter.cancel()
                raise
        return self._items.popleft()

    def peek(self) -> QueuedTranscription | None:
        """Look at the front item without removing it."""
        return self._items[0] if self._items else None

    def pop_peeked(self) -> QueuedTranscription:
        """Remove the item just returned by `peek()`."""
        return self._items.popleft()


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

        # Initialize translator first: it loads the terminology dictionary,
        # which the transcriber below also needs (as Deepgram keyterms) so
        # domain terms are ASR-corrected at the source instead of only
        # being patched up later by the LLM.
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
            thinking_budget=config.gemini_thinking_budget,
            dictionary_dynamic_threshold=config.dictionary_dynamic_threshold,
            dictionary_dynamic_limit=config.dictionary_dynamic_limit,
            domain_packs=config.domain_packs,
            domain_packs_dir=config.domain_packs_dir,
        )

        keyterms = (
            self._translator.dictionary.source_terms(
                limit=config.deepgram_max_keyterms
            )
            if config.deepgram_keyterms_enabled
            else None
        )

        # Initialize transcriber
        self._transcriber = DeepgramTranscriber(
            api_key=config.deepgram_api_key,
            language=config.deepgram_language,
            model=config.deepgram_model,
            interim_results=config.deepgram_interim_results,
            smart_format=config.deepgram_smart_format,
            endpointing=config.deepgram_endpointing,
            utterance_end_ms=config.deepgram_utterance_end_ms,
            vad_events=config.deepgram_vad_events,
            emit_interim=True,  # Emit interim results for real-time UI
            max_interim_duration=config.deepgram_max_interim_duration,
            keyterms=keyterms,
        )

        # Rate limiter shared across all translation workers, to stay under
        # the provider's RPM quota instead of firing requests that 429.
        self._translation_rate_limiter = RateLimiter(rate=config.gemini_rpm_limit)
        self._num_translation_workers = max(1, config.translation_workers)
        self._translation_timeout = config.translation_timeout
        self._translation_batch_max_items = max(1, config.translation_batch_max_items)
        self._translation_batch_max_chars = max(
            1, config.translation_batch_max_chars
        )

        # Concurrent workers finish translation calls in whatever order the
        # provider happens to respond, not the order utterances were spoken
        # in. `_emit_lock` serializes both the shared context/accumulator
        # mutation *and* delivery to `_on_result` so consumers only ever see
        # results in speech order, regardless of which worker finished
        # first. `_next_batch_id`/`_next_emit_batch_id` implement a small
        # reorder buffer: a batch that finishes early is held in
        # `_pending_batches` until every earlier batch has been emitted.
        self._emit_lock = asyncio.Lock()
        self._next_batch_id = 0
        self._next_emit_batch_id = 0
        self._pending_batches: dict[int, tuple[list[QueuedTranscription], str | None]] = {}
        # Per-utterance accumulated (source, translation) text, for
        # utterances split across multiple soft-finalized translation calls
        # (see TranslationResult.is_utterance_end) -- keyed by
        # TranscriptionResult.utterance_id.
        self._utterance_acc: dict[int, tuple[str, str]] = {}

        self._running = False
        self._on_result: Callable[[TranslationResult], None] | None = None
        self._tasks: list[asyncio.Task[Any]] = []
        self._transcription_queue = _FragmentQueue(maxsize=config.translation_queue_size)

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

    async def _auto_preload(self) -> None:
        """Merge supplementary terminology from `config.preload_source`.

        Runs before `prepare()`/`connect()` so a freshly-created Gemini
        cache and Deepgram's keyterm list both include any newly-merged
        terms from the start, rather than only from the next session. A
        no-op if `preload_source` isn't configured.
        """
        if self._config.preload_source is None:
            return

        added = await preload_translator(
            self._translator,
            self._config.preload_source,
            config=self._config,
            max_terms=self._config.preload_max_terms,
        )
        if added and self._config.deepgram_keyterms_enabled:
            self._transcriber.set_keyterms(
                self._translator.dictionary.source_terms(
                    limit=self._config.deepgram_max_keyterms
                )
            )

    async def start(self) -> None:
        """Start the translation pipeline."""
        self._running = True

        await self._auto_preload()

        # Initialize translator (e.g., Gemini context cache)
        await self._translator.prepare()

        # Connect to Deepgram
        await self._transcriber.connect()

        # Start audio capture
        await self._audio_capture.start()

        # Start processing tasks. Multiple parallel translation workers
        # prevent the sequential-processing lag-accumulation bug (see
        # CHANGELOG_2026-02-04.md): with one worker, a ~1s-per-Gemini-call
        # latency against continuous speech causes the queue (and lag) to
        # grow without bound. A shared rate limiter keeps workers from
        # exceeding the provider's RPM quota.
        self._tasks = [
            asyncio.create_task(self._audio_to_transcription()),
            asyncio.create_task(self._collect_transcriptions()),
            *(
                asyncio.create_task(self._translation_worker(i))
                for i in range(self._num_translation_workers)
            ),
        ]

    async def stop(self) -> None:
        """Stop the translation pipeline."""
        # Signal tasks to stop first to prevent blocking
        self._running = False

        # Stop audio capture to signal no more audio
        await self._audio_capture.stop()

        # Finalize the transcriber (signal end of audio stream)
        await self._transcriber.finalize()

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
                            start_time=result.start_time,
                            end_time=result.end_time,
                        )
                        self._on_result(interim_result)
                    continue

                # Handle low confidence by masking for translation input
                masked_text = (
                    f"[uncertain: {text}]" if result.is_low_confidence else text
                )

                queued = QueuedTranscription(
                    original=result,
                    text_for_translation=masked_text,
                    context=self._translator.context_snapshot(),
                )
                self._transcription_queue.put(queued)
        except asyncio.CancelledError:
            pass

    async def _drain_batch(self) -> list[QueuedTranscription]:
        """Block for one queued transcription, then greedily grab more.

        Draining beyond the first item never `await`s, so no other worker
        can interleave and steal part of the batch -- the queue's FIFO
        order guarantees batches are formed in strictly increasing speech
        order across all workers (see `_next_batch_id` in `start()`'s
        docstring-adjacent comment on `_emit_lock`). Coalescing multiple
        queued fragments into one LLM call is what keeps request volume
        bounded when translation falls behind realtime (e.g. continuous
        speech soft-finalizing every `deepgram_max_interim_duration`
        seconds against a low `gemini_rpm_limit`), and gives the model a
        fuller, more coherent span of text instead of many disjoint
        mid-sentence fragments.
        """
        batch = [await self._transcription_queue.get()]
        total_chars = len(batch[0].text_for_translation)
        while len(batch) < self._translation_batch_max_items:
            item = self._transcription_queue.peek()
            if item is None:
                break
            if total_chars + len(item.text_for_translation) > (
                self._translation_batch_max_chars
            ):
                # Leave it at the front of the queue for the next batch --
                # a peek never removes it, so no reordering risk.
                break
            batch.append(self._transcription_queue.pop_peeked())
            total_chars += len(item.text_for_translation)
        return batch

    async def _stream_batch(
        self, batch_id: int, batch: list[QueuedTranscription], combined_text: str
    ) -> str:
        """Stream a translation for a coalesced batch, emitting live updates.

        Live (`is_translation_complete=False`) updates are only forwarded to
        `_on_result` while this batch is the head of the emit order
        (`batch_id == self._next_emit_batch_id`); a batch that raced ahead
        of an earlier one still-in-flight accumulates silently and is
        delivered in one shot by `_finish_batch` once its turn comes, so
        viewers never see a later utterance's text race an earlier one's
        onto the screen.

        Returns the accumulated (stripped) translation text.
        """
        _, prefix = self._utterance_acc.get(
            batch[0].original.utterance_id, ("", "")
        )
        accumulated = ""
        async for chunk in self._translator.translate_stream(
            combined_text,
            context_lines=batch[0].context,
            update_context=False,
        ):
            accumulated += chunk
            if self._on_result and batch_id == self._next_emit_batch_id:
                live_text = f"{prefix} {accumulated}".strip() if prefix else accumulated
                self._on_result(
                    TranslationResult(
                        original_text=" ".join(q.original.text for q in batch),
                        translated_text=live_text,
                        is_final=True,
                        is_translation_complete=False,
                        confidence=min(q.original.confidence for q in batch),
                        start_time=batch[0].original.start_time,
                        end_time=batch[-1].original.end_time,
                        is_utterance_end=batch[-1].original.is_utterance_end,
                        utterance_id=batch[-1].original.utterance_id,
                    )
                )
        return accumulated.strip()

    async def _finish_batch(
        self, batch_id: int, batch: list[QueuedTranscription], translation: str | None
    ) -> None:
        """Record a finished (or failed) batch and emit everything now in order.

        `translation is None` marks a batch that was dropped after retries
        (see `_translation_worker`) -- it still occupies `batch_id`'s slot
        in the reorder buffer so later batches aren't stuck waiting on a
        result that will never arrive.
        """
        async with self._emit_lock:
            self._pending_batches[batch_id] = (batch, translation)
            while self._next_emit_batch_id in self._pending_batches:
                ready_batch, ready_translation = self._pending_batches.pop(
                    self._next_emit_batch_id
                )
                self._next_emit_batch_id += 1
                if ready_translation is not None:
                    self._emit_batch_result(ready_batch, ready_translation)

    def _emit_batch_result(
        self, batch: list[QueuedTranscription], translation: str
    ) -> None:
        """Commit context, fold in utterance accumulation, and notify."""
        combined_source = " ".join(q.text_for_translation for q in batch)
        self._translator.commit_context(combined_source, translation)
        slide_window = self._translator.slide_window

        first_utterance_id = batch[0].original.utterance_id
        last = batch[-1].original
        prev_source, prev_translation = self._utterance_acc.get(
            first_utterance_id, ("", "")
        )
        source_text = " ".join(q.original.text for q in batch)
        acc_source = f"{prev_source} {source_text}".strip() if prev_source else source_text
        acc_translation = (
            f"{prev_translation} {translation}".strip() if prev_translation else translation
        )

        # Drop any leftover accumulator entries this batch subsumed (e.g. a
        # batch that spans more than one utterance under heavy backlog) so
        # they can't be resurrected by a later, unrelated utterance_id. If
        # the batch's last fragment isn't the utterance's true end, re-add
        # the running accumulation under its id so the next continuation
        # picks up where this one left off.
        for q in batch:
            self._utterance_acc.pop(q.original.utterance_id, None)
        if not last.is_utterance_end:
            self._utterance_acc[last.utterance_id] = (acc_source, acc_translation)

        if self._on_result:
            self._on_result(
                TranslationResult(
                    original_text=acc_source,
                    translated_text=acc_translation,
                    is_final=True,
                    is_translation_complete=True,
                    confidence=min(q.original.confidence for q in batch),
                    start_time=batch[0].original.start_time,
                    end_time=last.end_time,
                    slide_window=slide_window,
                    is_utterance_end=last.is_utterance_end,
                    utterance_id=last.utterance_id,
                )
            )

    async def _translation_worker(self, worker_id: int) -> None:
        """Consume queued transcriptions and translate, streaming output.

        Runs as one of several concurrent workers (see `start()`). Each
        translation call is stateless (`update_context=False`, explicit
        `context_lines` snapshotted at enqueue time) so concurrent workers
        don't race on the translator's internal context buffer; completed
        batches are committed and delivered in speech order by
        `_finish_batch` regardless of which worker finishes first.

        A hung provider call (observed in practice: `generate_content_stream`
        can stall indefinitely with no error) must never permanently strand
        a worker -- that silently stops the whole pool one hang at a time,
        which is worse than a dropped segment. Every attempt is bounded by
        `translation_timeout` (scaled up slightly for larger batches) and
        retried once before the segment is dropped.
        """
        try:
            while self._running:
                batch = await self._drain_batch()
                batch_id = self._next_batch_id
                self._next_batch_id += 1

                await self._translation_rate_limiter.acquire()

                combined_text = " ".join(q.text_for_translation for q in batch)
                timeout = self._translation_timeout + 2.0 * (len(batch) - 1)

                translation: str | None = None
                for attempt in range(2):
                    try:
                        translation = await asyncio.wait_for(
                            self._stream_batch(batch_id, batch, combined_text),
                            timeout=timeout,
                        )
                        break
                    except TimeoutError:
                        print(
                            f"Translation worker {worker_id}: timed out after "
                            f"{timeout}s (attempt {attempt + 1}/2)"
                            f" on {combined_text[:50]!r}"
                        )
                    except Exception as exc:  # noqa: BLE001
                        print(f"Translation worker {worker_id}: error: {exc}")
                        break

                await self._finish_batch(batch_id, batch, translation)
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
