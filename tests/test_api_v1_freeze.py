"""v1.0 API contract freeze tests.

These tests pin the public REST surface: the OpenAPI snapshot, the error
envelope, pagination semantics, datetime format and version headers. A failure
here means a documented v1 guarantee changed and the snapshot/documentation
must be updated deliberately (or the change moved to /api/v2).
"""

from __future__ import annotations

import json
import re
import sqlite3
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from db.repositories import create_snapshot, upsert_repository
from github.models import RepoSummary

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from export_openapi import (  # noqa: E402
    SNAPSHOT,
    build_document,
    canonical,
    first_difference,
    render,
)

NOW = datetime.now(UTC)
DAY = timedelta(days=1)
UTC_TIMESTAMP = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(\.\d+)?(Z|\+00:00)$")


async def _seed(db_session) -> None:
    for index, (full_name, stars) in enumerate(
        [("psf/requests", 500), ("pallets/flask", 900), ("golang/go", 700)]
    ):
        repo = await upsert_repository(
            db_session,
            RepoSummary(
                id=index,
                full_name=full_name,
                description=f"About {full_name}",
                html_url=f"https://github.com/{full_name}",
                language="Python" if index < 2 else "Go",
                stargazers_count=stars,
                forks_count=10,
                created_at="2020-01-01T00:00:00Z",
                pushed_at="2024-01-01T00:00:00Z",
            ),
        )
        for offset, delta in [(2, 40), (1, 0)]:
            await create_snapshot(
                db_session,
                repo.id,
                stargazers=stars - delta,
                forks=10,
                observed_at=NOW - DAY * offset,
            )
    await db_session.commit()


def test_openapi_snapshot_is_current() -> None:
    """The committed snapshot describes the live API.

    The comparison is by content, not by bytes: the file is generated, so a
    reflowed copy (an editor, a JSON formatter) must not fail the contract test.
    Formatting drift is reported separately by
    ``python scripts/export_openapi.py --check --strict``.
    """

    assert SNAPSHOT.is_file(), "docs/openapi-v1.json must be committed"
    live = build_document()
    try:
        stored = json.loads(SNAPSHOT.read_text())
    except json.JSONDecodeError as exc:  # pragma: no cover - corrupt snapshot
        pytest.fail(f"docs/openapi-v1.json is not valid JSON: {exc}")

    assert stored == live, (
        "docs/openapi-v1.json describes a different API: "
        f"{first_difference(stored, live)}. A documented v1 guarantee changed, "
        "so update docs/API_V1.md and run `python scripts/export_openapi.py`; if "
        "only the generated document moved, reinstall the pinned dependencies "
        'with `pip install -e ".[dev]"`.'
    )


def test_openapi_snapshot_survives_reformatting() -> None:
    """Any whitespace-only rewrite of the file keeps the same contract."""

    document = build_document()
    reformatted = json.dumps(document, indent=4, separators=(",", ": "))
    assert canonical(reformatted) == render(document)


def test_canonical_rendering_is_idempotent() -> None:
    rendered = render(build_document())
    assert canonical(rendered) == rendered


def test_first_difference_names_the_changed_part_of_the_contract() -> None:
    left = {"paths": {"/api/v1/repos": {"get": {"summary": "List"}}}}
    right = {"paths": {"/api/v1/repos": {"get": {"summary": "List repositories"}}}}
    difference = first_difference(left, right) or ""
    assert difference.startswith("$.paths./api/v1/repos.get.summary"), difference
    assert "'List'" in difference and "'List repositories'" in difference
    assert first_difference(left, left) is None
    assert "missing from the snapshot" in first_difference({}, {"a": 1})
    assert "1 item(s)" in first_difference({"a": [1]}, {"a": [1, 2]})


def test_openapi_namespace_and_version() -> None:
    from version import __version__

    document = build_document()
    assert document["info"]["version"] == __version__
    assert all(
        path.startswith("/api/v1") or path in {"/health", "/ready", "/metrics"}
        for path in document["paths"]
    )


async def test_error_envelope_shape(api_client) -> None:
    response = await api_client.get("/api/v1/repos/no/such")
    assert response.status_code == 404
    body = response.json()
    assert {"detail", "code"} <= set(body)
    assert body["code"] == 404
    assert body["type"] == "not_found"
    assert body["request_id"] == response.headers["X-Request-ID"]

    validation = await api_client.get("/api/v1/repos", params={"limit": 0})
    assert validation.status_code == 422
    assert validation.json()["type"] == "validation_error"


async def test_pagination_and_sorting_contract(api_client, db_session) -> None:
    await _seed(db_session)

    first = (await api_client.get("/api/v1/repos", params={"limit": 2})).json()
    assert set(first) == {"total", "offset", "limit", "next_offset", "items"}
    assert (first["total"], first["offset"], first["limit"]) == (3, 0, 2)
    assert first["next_offset"] == 2
    assert [item["full_name"] for item in first["items"]] == [
        "pallets/flask",
        "golang/go",
    ]

    second = (
        await api_client.get("/api/v1/repos", params={"limit": 2, "offset": 2})
    ).json()
    assert second["next_offset"] is None
    assert len(second["items"]) == 1

    by_name = (
        await api_client.get("/api/v1/repos", params={"sort": "name", "limit": 5})
    ).json()
    names = [item["full_name"] for item in by_name["items"]]
    assert names == sorted(names)

    filtered = (
        await api_client.get("/api/v1/repos", params={"language": "Go"})
    ).json()
    assert filtered["total"] == 1
    assert filtered["items"][0]["full_name"] == "golang/go"


async def test_datetimes_are_explicit_utc(api_client, db_session) -> None:
    await _seed(db_session)
    payload = (await api_client.get("/api/v1/repos/psf/requests")).json()
    for field in ("created_at", "updated_at"):
        assert UTC_TIMESTAMP.match(payload[field]), (field, payload[field])
    snapshot = payload["latest_snapshot"]
    assert UTC_TIMESTAMP.match(snapshot["observed_at"])


async def test_naive_database_values_are_read_as_utc(api_client, db_session) -> None:
    """Rows written before v1 stored naive UTC; they must not shift timezones."""

    await _seed(db_session)
    from config import settings
    from db.lifecycle import database_path

    path = database_path(settings.database_url)
    assert path is not None

    connection = sqlite3.connect(path)
    try:
        connection.execute(
            "INSERT INTO repositories "
            "(full_name, html_url, language, tracking_enabled, tracking_paused, "
            " created_at, updated_at) "
            "VALUES ('legacy/naive', 'https://github.com/legacy/naive', 'Go', 1, 0, "
            "'2024-01-01 10:00:00.000000', '2024-01-01 10:00:00.000000')"
        )
        connection.commit()
    finally:
        connection.close()

    response = await api_client.get("/api/v1/repos/legacy/naive")
    assert response.status_code == 200
    assert UTC_TIMESTAMP.match(response.json()["created_at"])


async def test_version_headers_and_request_id(api_client) -> None:
    response = await api_client.get("/api/v1/repos", headers={"X-Request-ID": "abc123"})
    assert response.headers["X-API-Version"] == "v1"
    assert response.headers["X-API-Compatibility"] == "stable"
    assert response.headers["X-Request-ID"] == "abc123"


async def test_unknown_request_fields_are_ignored(api_client, db_session) -> None:
    """Additive evolution: unknown JSON fields must not break clients."""

    await _seed(db_session)
    response = await api_client.post(
        "/api/v1/alerts/rules",
        json={
            "repository": "psf/requests",
            "kind": "stars_reached",
            "threshold": 1000,
            "future_field": {"anything": True},
        },
    )
    assert response.status_code == 201
    assert response.json()["kind"] == "stars_reached"
    assert "future_field" not in response.json()


def test_documented_paths_are_present() -> None:
    document = build_document()
    documented = json.loads(SNAPSHOT.read_text())
    expected = {
        "/api/v1/repos",
        "/api/v1/repos/{owner}/{name}",
        "/api/v1/repos/{owner}/{name}/history",
        "/api/v1/repos/{owner}/{name}/status",
        "/api/v1/trends",
        "/api/v1/languages",
        "/api/v1/analytics/velocity/{owner}/{name}",
        "/api/v1/analytics/series/{owner}/{name}",
        "/api/v1/analytics/bursts/{owner}/{name}",
        "/api/v1/analytics/compare",
        "/api/v1/analytics/leaderboard",
        "/api/v1/alerts/rules",
        "/api/v1/alerts/events",
        "/api/v1/alerts/endpoints",
        "/api/v1/jobs",
        "/api/v1/ops/config",
        "/health",
        "/ready",
        "/metrics",
    }
    assert expected <= set(document["paths"])
    assert expected <= set(documented["paths"])
