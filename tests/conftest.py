import httpx
import pytest

from config import settings
from github.client import GitHubClient


@pytest.fixture(autouse=True)
def fast_retry_settings(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "max_retries", 2)
    monkeypatch.setattr(settings, "backoff_base", 0.01)


@pytest.fixture
def client_factory():
    def _make(handler) -> GitHubClient:
        return GitHubClient(token="test-token", transport=httpx.MockTransport(handler))

    return _make
