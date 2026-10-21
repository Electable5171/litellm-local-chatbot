"""Cached LiteLLM health check, so a refreshing browser tab never hammers the shared model."""

import asyncio
import time

from app.services.llm import LLMClient, Probe


class HealthService:
    def __init__(self, llm: LLMClient, ttl_s: float):
        self._llm = llm
        self._ttl_s = ttl_s
        self._cached: Probe | None = None
        self._lock = asyncio.Lock()

    async def check(self) -> Probe:
        async with self._lock:
            now = time.time()
            if self._cached is None or now - self._cached.checked_at > self._ttl_s:
                self._cached = await self._llm.probe()
            return self._cached
