# Commit guide: tracking API and dashboard

## Scope

This commit exposes managed tracking to clients:

- `POST`/`DELETE /api/v1/repos/{owner}/{name}/track`;
- `PATCH /api/v1/repos/{owner}/{name}/tracking`;
- `GET /api/v1/repos/{owner}/{name}/status`;
- manual `POST /api/v1/repos/{owner}/{name}/refresh`;
- repository list filters for tracking scope, health status and label;
- dashboard controls for track, stop, pause, resume and refresh;
- status badges, last-error visibility, label/status filters and explicit
  insufficient-history messaging.

Mutation endpoints preserve snapshot history. The API never returns the
configured webhook or GitHub token, and tracking error messages are sanitized
at the collection boundary.

## Validation

```bash
pytest -q tests/test_tracking_v08.py tests/test_exports_v08.py tests/test_dashboard_alerts.py
ruff check src tests conftest.py alembic
node --check web/app.js
node --check web/charts.js
```
