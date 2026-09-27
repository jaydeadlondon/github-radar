from datetime import UTC, datetime

import api.routes.operations as operations


class _QuotaClient:
    async def __aenter__(self):
        return self

    async def __aexit__(self, *_exc):
        return None

    async def get_rate_limit(self):
        return {
            "resource": "core",
            "limit": 5000,
            "remaining": 4999,
            "used": 1,
            "reset": int(datetime(2026, 9, 20, 13, tzinfo=UTC).timestamp()),
        }


async def test_rate_limit_and_safe_config_diagnostics(api_client, monkeypatch):
    monkeypatch.setattr(operations, "GitHubClient", _QuotaClient)

    quota = await api_client.get("/api/v1/ops/github/rate-limit")
    assert quota.status_code == 200
    assert quota.json()["remaining"] == 4999
    assert quota.json()["reset_at"].startswith("2026-09-20T13:00:00")

    diagnostics = await api_client.get("/api/v1/ops/config")
    assert diagnostics.status_code == 200
    body = diagnostics.json()
    assert "api_key" not in body
    assert body["admin_key_configured"] is False


async def test_metrics_and_health_endpoints_are_public(api_client):
    health = await api_client.get("/health")
    metrics = await api_client.get("/metrics")

    assert health.status_code == 200
    assert metrics.status_code == 200
    assert metrics.headers["content-type"].startswith("text/plain")
