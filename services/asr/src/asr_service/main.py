"""ASR microservice entrypoint."""

from __future__ import annotations

import asyncio
import csv
import logging
import os
import time
from collections import deque
from dataclasses import dataclass, field
from typing import Any

import httpx

from asr_service.audio_capture import FFmpegRTMPCapture
from asr_service.deepgram_client import DeepgramTranscriber, TranscriptionResult

logger = logging.getLogger(__name__)


def _get_bool_env(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _get_optional_int_env(name: str) -> int | None:
    value = os.getenv(name)
    if value is None:
        return None
    value = value.strip()
    if not value:
        return None
    return int(value)


def _load_keyterms_from_csv(path: str) -> list[str]:
    """Load source terms from dictionary CSV as keyterms."""
    keyterms: list[str] = []
    try:
        with open(path, encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                source_term = row.get("source_term", "").strip()
                if source_term:
                    keyterms.append(source_term)
        logger.info("Loaded %d keyterms from %s", len(keyterms), path)
    except FileNotFoundError:
        logger.warning("Dictionary file not found: %s", path)
    except Exception:  # noqa: BLE001
        logger.exception("Failed to load keyterms from %s", path)
    return keyterms


@dataclass(frozen=True)
class ASRServiceConfig:
    deepgram_api_key: str
    deepgram_model: str
    deepgram_interim_results: bool
    deepgram_smart_format: bool
    deepgram_endpointing: int | None
    deepgram_utterance_end_ms: int | None
    deepgram_vad_events: bool | None
    rtmp_url: str
    ffmpeg_chunk_ms: int
    ffmpeg_sample_rate: int
    ffmpeg_channels: int
    ws_publish_url: str
    translation_api_url: str
    send_interim: bool
    translate_interim: bool
    partial_min_interval_ms: int
    context_window_size: int
    translation_concurrency: int
    http_timeout: float
    keyterms: list[str] = field(default_factory=list)

    @staticmethod
    def from_env() -> ASRServiceConfig:
        api_key = os.getenv("DEEPGRAM_API_KEY", "")
        if not api_key:
            raise ValueError("DEEPGRAM_API_KEY is required")

        rtmp_url = os.getenv("RTMP_URL", "")
        if not rtmp_url:
            raise ValueError("RTMP_URL is required")

        endpointing_value = os.getenv("DEEPGRAM_ENDPOINTING")
        deepgram_endpointing = (
            500
            if endpointing_value is None
            else _get_optional_int_env("DEEPGRAM_ENDPOINTING")
        )

        return ASRServiceConfig(
            deepgram_api_key=api_key,
            deepgram_model=os.getenv("DEEPGRAM_MODEL", "nova-2-general"),
            deepgram_interim_results=_get_bool_env("DEEPGRAM_INTERIM_RESULTS", True),
            deepgram_smart_format=_get_bool_env("DEEPGRAM_SMART_FORMAT", True),
            deepgram_endpointing=deepgram_endpointing,
            deepgram_utterance_end_ms=_get_optional_int_env(
                "DEEPGRAM_UTTERANCE_END_MS"
            ),
            deepgram_vad_events=(
                _get_bool_env("DEEPGRAM_VAD_EVENTS", False)
                if os.getenv("DEEPGRAM_VAD_EVENTS") is not None
                else None
            ),
            rtmp_url=rtmp_url,
            ffmpeg_chunk_ms=int(os.getenv("FFMPEG_CHUNK_MS", "20")),
            ffmpeg_sample_rate=int(os.getenv("FFMPEG_SAMPLE_RATE", "16000")),
            ffmpeg_channels=int(os.getenv("FFMPEG_CHANNELS", "1")),
            ws_publish_url=os.getenv("WS_PUBLISH_URL", "http://ws:8000/publish"),
            translation_api_url=os.getenv(
                "TRANSLATION_API_URL", "http://gemini:8000/translate"
            ),
            send_interim=_get_bool_env("ASR_SEND_INTERIM", True),
            translate_interim=_get_bool_env("TRANSLATE_INTERIM", False),
            partial_min_interval_ms=int(
                os.getenv("ASR_PARTIAL_MIN_INTERVAL_MS", "200")
            ),
            context_window_size=int(os.getenv("CONTEXT_WINDOW_SIZE", "3")),
            translation_concurrency=int(os.getenv("TRANSLATION_CONCURRENCY", "2")),
            http_timeout=float(os.getenv("HTTP_TIMEOUT", "10")),
            keyterms=_load_keyterms_from_csv(
                os.getenv("DICTIONARY_PATH", "/app/dictionary.csv")
            ),
        )


async def _post_json(
    http_client: httpx.AsyncClient, url: str, payload: dict[str, Any]
) -> None:
    try:
        await http_client.post(url, json=payload)
    except Exception:  # noqa: BLE001
        logger.exception("Failed to POST %s", url)


async def _publish_asr(
    http_client: httpx.AsyncClient,
    ws_url: str,
    result: TranscriptionResult,
    *,
    is_final: bool,
    session_id: str | None = None,
) -> None:
    payload = {
        "type": "asr_partial",
        "text": result.text,
        "confidence": result.confidence,
        "is_final": is_final,
        "ts": time.time(),
        "session_id": session_id,
    }
    await _post_json(http_client, ws_url, payload)


async def _send_translation(
    http_client: httpx.AsyncClient,
    url: str,
    payload: dict[str, Any],
    semaphore: asyncio.Semaphore,
) -> None:
    async with semaphore:
        await _post_json(http_client, url, payload)


async def run_service() -> None:
    logging.basicConfig(level=logging.INFO)
    config = ASRServiceConfig.from_env()

    capture = FFmpegRTMPCapture(
        config.rtmp_url,
        sample_rate=config.ffmpeg_sample_rate,
        channels=config.ffmpeg_channels,
        chunk_ms=config.ffmpeg_chunk_ms,
    )

    emit_interim = config.send_interim or config.translate_interim
    transcriber = DeepgramTranscriber(
        api_key=config.deepgram_api_key,
        model=config.deepgram_model,
        interim_results=config.deepgram_interim_results,
        smart_format=config.deepgram_smart_format,
        endpointing=config.deepgram_endpointing,
        utterance_end_ms=config.deepgram_utterance_end_ms,
        vad_events=config.deepgram_vad_events,
        emit_interim=emit_interim,
        keyterms=config.keyterms,
    )

    http_client = httpx.AsyncClient(timeout=config.http_timeout)
    semaphore = asyncio.Semaphore(config.translation_concurrency)
    pending: set[asyncio.Task[None]] = set()
    context_buffer: deque[str] = deque(maxlen=config.context_window_size)

    async def _schedule_translation(payload: dict[str, Any]) -> None:
        task = asyncio.create_task(
            _send_translation(
                http_client, config.translation_api_url, payload, semaphore
            )
        )
        pending.add(task)
        task.add_done_callback(lambda t: pending.discard(t))

    async def _audio_loop() -> None:
        async for chunk in capture.stream():
            await transcriber.send_audio(chunk)

    async def _result_loop() -> None:
        last_partial_text = ""
        last_partial_at = 0.0
        min_interval = config.partial_min_interval_ms / 1000.0
        async for result in transcriber.results():
            if not result.text.strip():
                continue

            if result.is_final:
                await _publish_asr(
                    http_client, config.ws_publish_url, result, is_final=True
                )
                translation_payload = {
                    "text": result.text,
                    "context": list(context_buffer),
                    "is_final": True,
                    "ts": time.time(),
                }
                await _schedule_translation(translation_payload)
                context_buffer.append(result.text)
                continue

            if not config.send_interim and not config.translate_interim:
                continue

            now = time.monotonic()
            if (
                result.text == last_partial_text
                and now - last_partial_at < min_interval
            ):
                continue
            if now - last_partial_at < min_interval:
                continue
            last_partial_text = result.text
            last_partial_at = now

            if config.send_interim:
                await _publish_asr(
                    http_client, config.ws_publish_url, result, is_final=False
                )

            if config.translate_interim:
                translation_payload = {
                    "text": result.text,
                    "context": list(context_buffer),
                    "is_final": False,
                    "ts": time.time(),
                }
                await _schedule_translation(translation_payload)

    try:
        await transcriber.connect()
        await capture.start()
        await asyncio.gather(_audio_loop(), _result_loop())
    finally:
        await capture.stop()
        await transcriber.disconnect()
        await http_client.aclose()
        if pending:
            await asyncio.gather(*pending, return_exceptions=True)


def main() -> None:
    asyncio.run(run_service())


if __name__ == "__main__":
    main()
