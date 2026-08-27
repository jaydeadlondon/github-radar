import asyncio

import httpx
import pytest

from config import settings
from github.errors import RateLimitError


def test_retry_on_429_then_success(client_factory):
    calls = {"count": 0}

    def handler(_: httpx.Request) -> httpx.Response:
        calls["count"] += 1
        if calls["count"] == 1:
            return httpx.Response(429, headers={"Retry-After": "0"}, json={})
        return httpx.Response(200, json={"total_count": 0, "items": []})

    client = client_factory(handler)
    result = asyncio.run(client.search_repos("stars:>1"))

    assert calls["count"] == 2
    assert result == []


def test_rate_limit_exhausted_raises(client_factory, monkeypatch):
    monkeypatch.setattr(settings, "max_retries", 1)

    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(403, json={"message": "API rate limit exceeded"})

    client = client_factory(handler)
    with pytest.raises(RateLimitError):
        asyncio.run(client.search_repos("stars:>1"))


def test_etag_cache_returns_cached_payload(client_factory):
    calls = {"count": 0, "first_had_etag_header": None}
    payload = {"total_count": 0, "items": []}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["count"] += 1
        if calls["count"] == 1:
            calls["first_had_etag_header"] = request.headers.get("If-None-Match")
        if request.headers.get("If-None-Match") == '"abc"':
            return httpx.Response(304)
        return httpx.Response(200, headers={"ETag": '"abc"'}, json=payload)

    client = client_factory(handler)
    first = asyncio.run(client.search_repos("stars:>1"))
    second = asyncio.run(client.search_repos("stars:>1"))

    assert calls["count"] == 2
    assert calls["first_had_etag_header"] is None
    assert first == []
    assert second == []
