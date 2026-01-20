"""Audio capture utilities for the ASR service."""

from __future__ import annotations

import asyncio
import contextlib
import subprocess
from collections.abc import AsyncIterator


class FFmpegRTMPCapture:
    """Audio capture from an RTMP source via ffmpeg."""

    def __init__(
        self,
        rtmp_url: str,
        *,
        sample_rate: int = 16000,
        channels: int = 1,
        chunk_ms: int = 20,
        ffmpeg_path: str = "ffmpeg",
    ) -> None:
        self._rtmp_url = rtmp_url
        self._sample_rate = sample_rate
        self._channels = channels
        self._chunk_ms = chunk_ms
        self._ffmpeg_path = ffmpeg_path
        self._process: asyncio.subprocess.Process | None = None
        self._running = False

    async def start(self) -> None:
        """Start capturing audio by spawning ffmpeg."""
        cmd = [
            self._ffmpeg_path,
            "-fflags",
            "nobuffer",
            "-flags",
            "low_delay",
            "-i",
            self._rtmp_url,
            "-f",
            "s16le",
            "-ar",
            str(self._sample_rate),
            "-ac",
            str(self._channels),
            "pipe:1",
        ]
        self._process = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=subprocess.DEVNULL,
        )
        self._running = True

    async def stop(self) -> None:
        """Stop capturing audio and terminate ffmpeg."""
        self._running = False
        if not self._process:
            return
        self._process.terminate()
        with contextlib.suppress(ProcessLookupError):
            await self._process.wait()
        self._process = None

    async def stream(self) -> AsyncIterator[bytes]:
        """Stream audio data from ffmpeg stdout."""
        if not self._process or not self._process.stdout:
            return

        bytes_per_sample = 2
        chunk_size = int(
            self._sample_rate
            * self._channels
            * bytes_per_sample
            * self._chunk_ms
            / 1000
        )

        while self._running and self._process.stdout:
            try:
                data = await self._process.stdout.read(chunk_size)
            except asyncio.CancelledError:
                break
            if not data:
                break
            yield data
