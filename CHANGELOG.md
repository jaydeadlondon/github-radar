# Changelog

All notable changes to this project.

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
