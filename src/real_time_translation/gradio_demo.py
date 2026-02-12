"""Gradio demo for real-time ASR + MT."""

from __future__ import annotations

import asyncio
import contextlib
import subprocess
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

import audioop
import gradio as gr
import numpy as np

from real_time_translation.audio.capture import QueueAudioCapture
from real_time_translation.config import Config
from real_time_translation.pipeline import TranslationPipeline, TranslationResult

TARGET_SAMPLE_RATE = 16000
MAX_DISPLAY_LINES = 50


@dataclass
class DemoSession:
    """Per-user demo session state."""

    pipeline: TranslationPipeline
    capture: QueueAudioCapture
    results_queue: asyncio.Queue[TranslationResult]
    window_size: int
    transcript_lines: list[str] = field(default_factory=list)
    translation_lines: list[str] = field(default_factory=list)
    interim_transcript: str = ""  # Current interim transcript
    cancel_requested: bool = False  # Flag to cancel file processing


def _status(message: str) -> str:
    return f"Status: {message}"


def _timestamp() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _convert_file_to_pcm(file_path: str) -> bytes:
    """Convert any audio file to 16kHz mono PCM using ffmpeg."""
    import os
    if not os.path.isfile(file_path):
        raise FileNotFoundError(f"Audio file not found: {file_path}")

    cmd = [
        "ffmpeg",
        "-loglevel", "error",
        "-i", file_path,
        "-f", "s16le",
        "-ar", "16000",
        "-ac", "1",
        "-acodec", "pcm_s16le",
        "pipe:1",
    ]
    result = subprocess.run(cmd, capture_output=True, check=False)
    if result.returncode != 0:
        raise RuntimeError(f"ffmpeg error: {result.stderr.decode()}")
    return result.stdout


def _normalize_audio_chunk(chunk: Any) -> bytes | None:
    if chunk is None:
        return None

    if isinstance(chunk, tuple) and len(chunk) == 2:
        sample_rate, data = chunk
    else:
        return None

    if data is None:
        return None

    if isinstance(data, np.ndarray):
        if data.ndim > 1:
            data = data.mean(axis=1)

        if np.issubdtype(data.dtype, np.integer):
            max_val = np.iinfo(data.dtype).max
            if max_val:
                data = data.astype(np.float32) / max_val

        if data.dtype != np.float32:
            data = data.astype(np.float32)

        data = np.clip(data, -1.0, 1.0)
        data = (data * 32767).astype(np.int16)
        pcm = data.tobytes()
    else:
        return None

    if sample_rate != TARGET_SAMPLE_RATE:
        try:
            if not isinstance(sample_rate, (int, float)):
                return None
            pcm, _ = audioop.ratecv(
                pcm, 2, 1, int(sample_rate), TARGET_SAMPLE_RATE, None
            )
        except Exception:
            return None

    return pcm


async def start_session(
    state: DemoSession | None,
) -> tuple[DemoSession | None, str, str, str]:
    if state is not None:
        transcript = "\n".join(state.transcript_lines)
        translation = "\n".join(state.translation_lines)
        return state, _status("running"), transcript, translation

    try:
        config = Config.from_env(require_zoom=False)
    except Exception as exc:
        return None, _status(f"error: {exc}"), "", ""

    capture = QueueAudioCapture()
    pipeline = TranslationPipeline(config=config, audio_capture=capture)
    results_queue: asyncio.Queue[TranslationResult] = asyncio.Queue(
        maxsize=200  # Larger queue for file processing
    )

    def on_result(result: TranslationResult) -> None:
        timestamp = _timestamp()
        print(f"[{timestamp}] ASR: {result.original_text}")
        print(f"[{timestamp}] MT: {result.translated_text}")
        if result.kept_terms:
            kept = ", ".join(result.kept_terms)
            print(f"[{timestamp}] Kept terms: {kept}")
        with contextlib.suppress(asyncio.QueueFull):
            results_queue.put_nowait(result)

    pipeline.set_callback(on_result)
    try:
        await pipeline.start()
    except Exception as exc:
        with contextlib.suppress(Exception):
            await pipeline.stop()
        return None, _status(f"error: {exc}"), "", ""

    return (
        DemoSession(
            pipeline=pipeline,
            capture=capture,
            results_queue=results_queue,
            window_size=config.context_window_size,
        ),
        _status("running"),
        "",
        "",
    )


async def stop_session(state: DemoSession | None) -> tuple[DemoSession | None, str]:
    if state is None:
        return None, _status("stopped")

    await state.pipeline.stop()
    return None, _status("stopped")


async def clear_logs(state: DemoSession | None) -> tuple[str, str]:
    if state is None:
        return "", ""

    state.transcript_lines.clear()
    state.translation_lines.clear()
    state.pipeline.clear_context()
    return "", ""


def cancel_processing(state: DemoSession | None) -> tuple[DemoSession | None, str]:
    """Cancel ongoing file processing."""
    if state is None:
        return None, _status("stopped")

    state.cancel_requested = True
    return state, _status("Cancelling...")


async def process_audio_file(
    file_path: str | None, state: DemoSession | None
) -> tuple[DemoSession | None, str, str, str]:
    """Process an uploaded audio file through the pipeline."""
    if file_path is None:
        return state, _status("No file selected"), "", ""

    # Start session if not already running
    if state is None:
        state, status, _, _ = await start_session(None)
        if state is None:
            return None, status, "", ""

    # Clear previous results
    state.transcript_lines.clear()
    state.translation_lines.clear()
    state.interim_transcript = ""

    try:
        audio_data = _convert_file_to_pcm(file_path)
        duration = len(audio_data) / (16000 * 2)
    except Exception as e:
        return state, _status(f"Error: {e}"), "", ""

    # Reset cancel flag
    state.cancel_requested = False

    # Stream audio in chunks
    chunk_size = 16000 * 2  # 1 second of audio

    for offset in range(0, len(audio_data), chunk_size):
        if state.cancel_requested:
            break

        chunk = audio_data[offset : offset + chunk_size]
        state.capture.push_audio(chunk)

        # Sleep in shorter intervals to respond more quickly to cancellation
        for _ in range(5):  # 5 x 0.1s = 0.5s total
            if state.cancel_requested:
                break
            await asyncio.sleep(0.1)

        # Drain results queue periodically
        while True:
            try:
                result = state.results_queue.get_nowait()
                if result.is_final and result.translated_text:
                    state.transcript_lines.append(result.original_text)
                    state.translation_lines.append(result.translated_text)
            except asyncio.QueueEmpty:
                break

    if state.cancel_requested:
        transcript = "\n".join(state.transcript_lines)
        translation = "\n".join(state.translation_lines)
        return state, _status("Cancelled"), transcript, translation

    # Wait longer for processing to complete (based on audio duration)
    # Base time of 5 seconds plus 20% of audio duration, minimum 10 seconds
    wait_seconds = max(10, 5 + int(duration * 0.2))

    last_count = 0
    stable_count = 0
    for i in range(wait_seconds * 10):  # Check every 0.1 seconds
        if state.cancel_requested:
            break

        await asyncio.sleep(0.1)

        # Drain results queue
        while True:
            try:
                result = state.results_queue.get_nowait()
                if result.is_final and result.translated_text:
                    state.transcript_lines.append(result.original_text)
                    state.translation_lines.append(result.translated_text)
            except asyncio.QueueEmpty:
                break

        # Check if results have stabilized
        current_count = len(state.transcript_lines)
        if current_count == last_count:
            stable_count += 1
            if stable_count > 30:  # No new results for 3 seconds
                break
        else:
            stable_count = 0
            last_count = current_count

    transcript = "\n".join(state.transcript_lines)
    translation = "\n".join(state.translation_lines)

    if state.cancel_requested:
        status_text = f"Cancelled ({len(state.transcript_lines)} segments)"
    else:
        status_text = f"Done ({len(state.transcript_lines)} segments)"

    return state, _status(status_text), transcript, translation


async def handle_audio(chunk: Any, state: DemoSession | None) -> tuple[str, str, str]:
    if state is None:
        return "", "", _status("click Start to initialize")

    audio_bytes = _normalize_audio_chunk(chunk)
    if audio_bytes:
        state.capture.push_audio(audio_bytes)

    latest_slide_window: list[str] | None = None
    while True:
        try:
            result = state.results_queue.get_nowait()
        except asyncio.QueueEmpty:
            break

        if not result.is_final:
            # Update interim transcript (shown in real-time)
            state.interim_transcript = result.original_text
            continue

        # Final result - add to history and clear interim
        state.transcript_lines.append(result.original_text)
        state.translation_lines.append(result.translated_text)
        state.interim_transcript = ""
        if result.slide_window:
            latest_slide_window = result.slide_window

        if len(state.transcript_lines) > MAX_DISPLAY_LINES:
            state.transcript_lines = state.transcript_lines[-MAX_DISPLAY_LINES:]
        if len(state.translation_lines) > MAX_DISPLAY_LINES:
            state.translation_lines = state.translation_lines[-MAX_DISPLAY_LINES:]

    # Show finalized lines + current interim transcript
    finalized = "\n".join(state.transcript_lines[-state.window_size :])
    if state.interim_transcript:
        interim_display = f"[interim] {state.interim_transcript}"
        transcript = f"{finalized}\n{interim_display}" if finalized else interim_display
    else:
        transcript = finalized

    if latest_slide_window is not None:
        translation = "\n".join(latest_slide_window)
    else:
        translation = "\n".join(state.translation_lines[-state.window_size :])

    return transcript, translation, _status("running")


def build_demo() -> gr.Blocks:
    with gr.Blocks(title="Real-time Translation Demo") as demo:
        gr.Markdown("# Real-time ASR + MT Demo")
        gr.Markdown(
            "Stream microphone audio to Deepgram and translate with Gemini/OpenAI."
        )

        state = gr.State(None)
        status = gr.Markdown(_status("stopped"))

        with gr.Row():
            start_button = gr.Button("Start", variant="primary")
            stop_button = gr.Button("Stop")
            clear_button = gr.Button("Clear")

        with gr.Tabs():
            with gr.TabItem("🎤 Microphone"):
                audio = gr.Audio(
                    sources=["microphone"],
                    streaming=True,
                    type="numpy",
                    label="Microphone",
                )

            with gr.TabItem("📁 Audio File"):
                audio_file = gr.Audio(
                    sources=["upload"],
                    type="filepath",
                    label="Upload audio file (WAV, FLAC, MP3, etc.)",
                )
                with gr.Row():
                    process_button = gr.Button("Process File", variant="primary")
                    cancel_button = gr.Button("Cancel", variant="stop")

        with gr.Row():
            transcript_box = gr.Textbox(
                label="Transcription (source)",
                lines=12,
                interactive=False,
            )
            translation_box = gr.Textbox(
                label="Translation",
                lines=12,
                interactive=False,
            )

        start_button.click(
            start_session,
            inputs=[state],
            outputs=[state, status, transcript_box, translation_box],
        )
        stop_button.click(
            stop_session,
            inputs=[state],
            outputs=[state, status],
        )
        clear_button.click(
            clear_logs,
            inputs=[state],
            outputs=[transcript_box, translation_box],
        )

        audio.stream(
            handle_audio,
            inputs=[audio, state],
            outputs=[transcript_box, translation_box, status],
        )

        process_button.click(
            process_audio_file,
            inputs=[audio_file, state],
            outputs=[state, status, transcript_box, translation_box],
        )

        cancel_button.click(
            cancel_processing,
            inputs=[state],
            outputs=[state, status],
        )

    return demo


def main() -> None:
    demo = build_demo()
    demo.queue()
    demo.launch()


if __name__ == "__main__":
    main()
