import api.routes.alerts as alerts_routes


async def test_notification_endpoint_crud_redacts_secrets(api_client, monkeypatch):
    created = await api_client.post(
        "/api/v1/alerts/endpoints",
        json={
            "name": "primary",
            "provider": "generic",
            "url": "https://hooks.example.test/radar",
            "signing_secret": "top-secret",
        },
    )
    assert created.status_code == 201
    body = created.json()
    assert body["name"] == "primary"
    assert body["url_configured"] is True
    assert "top-secret" not in created.text
    assert "url" not in body

    listed = await api_client.get("/api/v1/alerts/endpoints")
    assert listed.status_code == 200
    assert listed.json()["total"] == 1

    unsafe = await api_client.post(
        "/api/v1/alerts/endpoints",
        json={
            "name": "local",
            "url": "http://127.0.0.1:8080/hook",
        },
    )
    assert unsafe.status_code == 422

    async def fake_test(*_args, **_kwargs):
        return True, None

    monkeypatch.setattr(alerts_routes, "deliver_test_endpoint", fake_test)
    tested = await api_client.post("/api/v1/alerts/endpoints/1/test")
    assert tested.status_code == 200
    assert tested.json() == {"sent": True, "error": None}

    disabled = await api_client.patch(
        "/api/v1/alerts/endpoints/1",
        json={"enabled": False},
    )
    assert disabled.status_code == 200
    assert disabled.json()["enabled"] is False

    deleted = await api_client.delete("/api/v1/alerts/endpoints/1")
    assert deleted.status_code == 204
