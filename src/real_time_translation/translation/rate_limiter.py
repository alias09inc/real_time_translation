"""Async token-bucket rate limiter for pacing outbound API calls."""

from __future__ import annotations

import asyncio
import time


class RateLimiter:
    """Caps calls to at most `rate` per `period` seconds.

    Shared across concurrent callers via `acquire()`, which blocks until
    a token is available. Used to stay under provider RPM quotas (e.g.
    Gemini free-tier ~10-15 RPM) instead of firing requests that will
    just 429.
    """

    def __init__(self, rate: int, period: float = 60.0) -> None:
        self._rate = max(1, rate)
        self._period = period
        self._tokens = float(self._rate)
        self._updated_at = time.monotonic()
        self._lock = asyncio.Lock()

    async def acquire(self) -> None:
        while True:
            async with self._lock:
                now = time.monotonic()
                elapsed = now - self._updated_at
                self._updated_at = now
                self._tokens = min(
                    float(self._rate),
                    self._tokens + elapsed * (self._rate / self._period),
                )
                if self._tokens >= 1:
                    self._tokens -= 1
                    return
                wait = (1 - self._tokens) * (self._period / self._rate)
            await asyncio.sleep(wait)
