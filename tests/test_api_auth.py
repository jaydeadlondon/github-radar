from config import settings
from db.repositories import upsert_repository
from github.models import RepoSummary


async def test_read_api_key_and_admin_mutation_scopes(
    api_client, db_session, monkeypatch
):
    monkeypatch.setattr(settings, "api_auth_enabled", True)
    monkeypatch.setattr(settings, "api_key", "read-key")
    monkeypatch.setattr(settings, "admin_api_key", "admin-key")
    await upsert_repository(
        db_session,
        RepoSummary(
            id=1,
            full_name="acme/rocket",
            html_url="https://github.com/acme/rocket",
            stargazers_count=10,
            forks_count=1,
        ),
    )
    await db_session.commit()

    missing = await api_client.get("/api/v1/repos")
    assert missing.status_code == 401
    assert (
        await api_client.get("/api/v1/repos", headers={"X-API-Key": "bad"})
    ).status_code == 403
    assert (
        await api_client.get("/api/v1/repos", headers={"X-API-Key": "read-key"})
    ).status_code == 200

    read_mutation = await api_client.patch(
        "/api/v1/repos/acme/rocket/tracking",
        headers={"X-API-Key": "read-key"},
        json={"paused": True},
    )
    assert read_mutation.status_code == 403

    admin_mutation = await api_client.patch(
        "/api/v1/repos/acme/rocket/tracking",
        headers={"X-API-Key": "admin-key"},
        json={"paused": True},
    )
    assert admin_mutation.status_code == 200
    assert admin_mutation.json()["status"] == "paused"


async def test_health_is_public_when_api_auth_is_enabled(api_client, monkeypatch):
    monkeypatch.setattr(settings, "api_auth_enabled", True)
    monkeypatch.setattr(settings, "api_key", "read-key")
    monkeypatch.setattr(settings, "admin_api_key", "admin-key")

    response = await api_client.get("/health")

    assert response.status_code == 200
    assert response.json()["status"] == "ok"
