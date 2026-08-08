from __future__ import annotations

import asyncio
import logging
import random
import time
from collections.abc import AsyncIterator
from typing import Any

import httpx

from config import settings
from github.errors import (
    ApiError,
    AuthenticationError,
    InvalidQueryError,
    NotFoundError,
    RateLimitError,
)
from github.models import RepoSearchResponse, RepoSummary

logger = logging.getLogger(__name__)


class GitHubClient:
    def __init__(
        self,
        token: str | None = None,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self._token = token if token is not None else settings.github_token
        self._headers = {
            "Accept": "application/vnd.github+json",
            "User-Agent": settings.user_agent,
        }
        if self._token:
            self._headers["Authorization"] = f"Bearer {self._token}"
        self._http = httpx.AsyncClient(
            base_url=settings.api_base_url,
            headers=self._headers,
            timeout=settings.request_timeout,
            transport=transport,
        )
        self._etag_cache: dict[str, tuple[str, Any]] = {}

    async def close(self) -> None:
        await self._http.aclose()

    async def __aenter__(self) -> GitHubClient:
        return self

    async def __aexit__(self, *exc: object) -> None:
        await self.close()

    async def _request(self, method: str, path: str, **kwargs: Any) -> Any:
        cache_key = f"{method} {path} {self._sorted_params(kwargs.get('params'))}"
        cached = self._etag_cache.get(cache_key)

        for attempt in range(settings.max_retries + 1):
            headers = dict(self._headers)
            if cached is not None:
                headers["If-None-Match"] = cached[0]

            try:
                response = await self._http.request(
                    method, path, headers=headers, **kwargs
                )
            except (httpx.ConnectError, httpx.ReadTimeout, httpx.WriteTimeout) as exc:
                if attempt >= settings.max_retries:
                    raise ApiError(
                        f"network error after {attempt + 1} attempts: {exc}"
                    ) from exc
                await self._backoff(attempt)
                continue

            if response.status_code == 304 and cached is not None:
                return cached[1]

            if response.status_code < 400:
                payload = response.json()
                etag = response.headers.get("ETag")
                if etag:
                    self._etag_cache[cache_key] = (etag, payload)
                return payload

            if response.status_code in (403, 429):
                retry_after = response.headers.get("Retry-After")
                if retry_after and retry_after.isdigit():
                    await asyncio.sleep(float(retry_after))
                    continue
                reset_at = response.headers.get("X-RateLimit-Reset")
                if reset_at and reset_at.isdigit():
                    wait = int(reset_at) - int(time.time())
                    if wait > 0:
                        await asyncio.sleep(wait)
                        continue
                if attempt >= settings.max_retries:
                    raise RateLimitError("GitHub API rate limit exceeded")
                await self._backoff(attempt)
                continue

            if response.status_code == 401:
                raise AuthenticationError("invalid or missing GitHub token", 401)
            if response.status_code == 404:
                raise NotFoundError(f"resource not found: {path}", 404)
            if response.status_code == 422:
                raise InvalidQueryError(f"invalid query: {response.text[:200]}", 422)
            if response.status_code >= 400:
                raise ApiError(
                    f"GitHub API error {response.status_code}: {response.text[:200]}",
                    response.status_code,
                )
            response.raise_for_status()
            return response.json()

        raise RateLimitError("GitHub API rate limit exceeded after retries")

    @staticmethod
    def _sorted_params(params: Any) -> str:
        if not params:
            return ""
        pairs = sorted((str(k), str(v)) for k, v in params.items())
        return "&".join(f"{k}={v}" for k, v in pairs)

    async def _backoff(self, attempt: int) -> None:
        delay = min(settings.backoff_base * (2**attempt), settings.backoff_max)
        delay *= random.uniform(0.5, 1.0)
        logger.info("GitHub API: retrying in %.1fs (attempt %d)", delay, attempt + 1)
        await asyncio.sleep(delay)
