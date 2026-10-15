"""Nazik, yeniden denemeli asenkron HTTP istemcisi.

Sağlayıcıların limitleri belgelenmemiş olduğu için: sınırlı eşzamanlılık, istekler arası minimum
aralık, jitter ve 429/5xx görüldüğünde aralığı büyüten (AIMD benzeri) bir hız denetimi kullanılır.
"""
from __future__ import annotations

import asyncio
import logging
import random
import time
from typing import Any

import httpx

from ..config import HTTP_CONCURRENCY, HTTP_MAX_RETRIES, HTTP_MIN_INTERVAL_S, USER_AGENT

log = logging.getLogger(__name__)


class FetchError(RuntimeError):
    def __init__(self, url: str, status: int | None, message: str) -> None:
        super().__init__(f"{url} -> {status}: {message}")
        self.url = url
        self.status = status


class PoliteClient:
    def __init__(
        self,
        concurrency: int = HTTP_CONCURRENCY,
        min_interval: float = HTTP_MIN_INTERVAL_S,
        timeout: float = 30.0,
    ) -> None:
        self._sem = asyncio.Semaphore(concurrency)
        self._interval = min_interval
        self._base_interval = min_interval
        self._next_slot = 0.0
        self._lock = asyncio.Lock()
        self._client = httpx.AsyncClient(
            timeout=timeout,
            headers={"User-Agent": USER_AGENT, "Accept": "application/json"},
            follow_redirects=True,
        )
        self.requests = 0
        self.failures = 0

    async def __aenter__(self) -> "PoliteClient":
        return self

    async def __aexit__(self, *exc: object) -> None:
        await self._client.aclose()

    async def _wait_slot(self) -> None:
        async with self._lock:
            now = time.monotonic()
            wait = self._next_slot - now
            self._next_slot = max(now, self._next_slot) + self._interval * random.uniform(0.85, 1.25)
        if wait > 0:
            await asyncio.sleep(wait)

    def _slow_down(self) -> None:
        self._interval = min(self._interval * 2.0, 8.0)

    def _speed_up(self) -> None:
        self._interval = max(self._base_interval, self._interval * 0.95)

    async def get_json(self, url: str, params: dict[str, str] | None = None) -> Any:
        last_err: FetchError | None = None
        for attempt in range(HTTP_MAX_RETRIES):
            async with self._sem:
                await self._wait_slot()
                self.requests += 1
                try:
                    resp = await self._client.get(url, params=params)
                except httpx.HTTPError as e:
                    last_err = FetchError(url, None, repr(e))
                    self._slow_down()
                else:
                    if resp.status_code == 200:
                        self._speed_up()
                        try:
                            return resp.json()
                        except ValueError as e:
                            raise FetchError(url, 200, f"JSON çözülemedi: {e}") from e
                    if resp.status_code in (429, 500, 502, 503, 504):
                        last_err = FetchError(url, resp.status_code, resp.text[:200])
                        self._slow_down()
                    else:
                        raise FetchError(url, resp.status_code, resp.text[:200])
            backoff = min(30.0, (2**attempt) * 0.75) * random.uniform(0.8, 1.3)
            log.warning("Tekrar denenecek (%s/%s) %s: %s", attempt + 1, HTTP_MAX_RETRIES, url, last_err)
            await asyncio.sleep(backoff)
        self.failures += 1
        assert last_err is not None
        raise last_err
