# Changelog

All notable changes to this project.

## [0.4.0] — 2026-08-25

### Added

- Web dashboard served at `/` (HTML/CSS/vanilla JS + locally bundled ECharts)
- Repositories table with sorting, language filter and debounced search
- Star-growth line chart with 7/30/90-day/all-time period switcher
- "New this week" cards from `/trends`
- Dark/light theme toggle (persisted in localStorage)
- Loading states, empty states and error toasts
- Mobile-responsive layout and favicon
- API: `q` search parameter on `/repos`; contract tests for static assets
- Tests: dashboard contract, search query (50 tests total)

## [0.3.0] — 2026-08-20

### Added

- FastAPI application with lifespan, CORS and request logging
- `radar serve` command (uvicorn)
- REST API under `/api/v1`:
  - `GET /repos` (paginated, language filter, sort)
  - `GET /repos/{owner}/{name}` (detail + latest snapshot)
  - `GET /repos/{owner}/{name}/history` (time range, limit)
  - `GET /trends` (top star growth over 7/30/90 days)
  - `GET /languages` (per-language aggregates)
- `GET /health` and root entry point
- Consistent `ErrorOut` error payloads and `Paginated` list envelope
- Parameter validation, custom exception handlers, request-id header
- Tests: repos, trends/history, health, contract tests (48 total)

## [0.2.0] — 2026-08-13

### Added

- Async SQLAlchemy storage: `Repository` and `RepoSnapshot` models
- Timestamp mixin, named unique constraint and indexes
- Alembic migrations (baseline + composite snapshot index)
- DB helpers: repository upsert, snapshot creation, history queries
- CLI commands: `radar init-db`, `radar snapshot`, `radar history`
- `--save` flag on `radar top` / `radar search`
- Tests: database integration, collector pipeline (22 tests total)

## [0.1.0] — 2026-08-09

### Added

- CLI commands: `radar version`, `radar top`, `radar search`, `radar repo`
- Async GitHub API client (httpx): token auth, rate-limit retries with
  exponential backoff and jitter, pagination, ETag caching
- Pydantic response schemas and a client error hierarchy
- Configuration via `.env` (pydantic-settings)
- Tests: client, retry/rate-limit, CLI
