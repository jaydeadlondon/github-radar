from api.app import create_app


def test_openapi_v09_surface_and_auth_scheme_are_stable():
    document = create_app().openapi()
    paths = document["paths"]
    required = {
        ("/health", "get"),
        ("/ready", "get"),
        ("/metrics", "get"),
        ("/api/v1/jobs", "get"),
        ("/api/v1/jobs/{job_id}", "get"),
        ("/api/v1/ops/github/rate-limit", "get"),
        ("/api/v1/ops/config", "get"),
        ("/api/v1/repos", "get"),
        ("/api/v1/repos/{owner}/{name}/tracking", "patch"),
    }
    assert required <= {
        (path, method) for path, item in paths.items() for method in item if method != "parameters"
    }
    assert "APIKeyHeader" in document["components"]["securitySchemes"]
    assert paths["/api/v1/repos"]["get"]["responses"]["200"]["description"]


async def test_api_responses_advertise_stable_version(api_client):
    # This test uses the ASGI client so it also checks the middleware contract.
    response = await api_client.get("/health")
    assert response.status_code == 200
    api_response = await api_client.get("/api/v1/repos")
    assert api_response.headers["X-API-Version"] == "v1"
    assert api_response.headers["X-API-Compatibility"] == "stable"
