# Changelog

All notable changes to this project.

## [0.7.0] — 2026-09-16

### Added

- Persistent `AlertRule` and `AlertEvent` models with Alembic migration `0003`,
  indexed inbox queries and retained event history when rules or repositories are deleted
- Three alert types evaluated from committed snapshots:
  - `stars_reached` for one-time star milestones
  - `velocity_above` for 7/30/90-day threshold crossings from below
  - `burst_started` for newly detected burst start dates
- Database-backed event fingerprinting and atomic duplicate suppression, making
  repeated and concurrent evaluation idempotent
- Optional generic JSON webhook delivery with configurable timeout, per-event
  `inbox_only` / `sent` / `failed` status and snapshot-failure isolation
- Alert evaluation after both manual and scheduled snapshot collection
- Alert REST API: rule CRUD, paginated/filterable event inbox, single and bulk
  acknowledgement, and summary counts under `/api/v1/alerts`
- Nested CLI commands: `radar alerts add|list|enable|disable|delete` and
  `radar alerts events|acknowledge|acknowledge-all`
- Dashboard alert bell and unread badge, inbox filters and acknowledgements,
  alert-rule editor, and visibility-aware 30-second polling
- Migration, evaluator, deduplication, webhook, snapshot, API, CLI and dashboard
  regression coverage (233 tests total)

### Changed

- Package version and GitHub client user agent are now 0.7
- Snapshot persistence is committed before isolated alert evaluation begins
- The existing 0.6 analytics, REST API and dashboard behavior remains backward compatible

### Fixed

- New burst rules use an evaluation watermark and short lookback instead of
  replaying a repository's full historical burst list
- Webhook transport errors are recorded without persisting or logging a
  potentially credential-bearing target URL

## [0.6.0] — 2026-09-15

### Added

- Comparison engine: several repositories aligned on one day grid, rebased to
  index 100 or to percent growth (`analytics/compare.py`)
- Moving-average smoothing for star series and daily deltas
- REST API:
  - `GET /analytics/series/{owner}/{name}` — daily series with `delta`,
    optional `stars_avg` / `delta_avg` (`smooth` window)
  - `GET /analytics/compare` — up to 5 repositories, `mode=absolute|indexed|percent`
  - `language` filter on `/analytics/leaderboard`
- Dashboard: chart mode switcher (stars / daily change / growth %),
  moving-average overlay, log scale, wheel zoom with a range slider,
  burst periods shaded on the chart with an "active burst" badge
- Dashboard: comparison mode — pick up to 5 repositories in the table and
  overlay their curves; PNG export of the current chart
- Dashboard: "Fastest growing" panel driven by the leaderboard endpoint —
  real stars/day and the gain over 7 / 30 / 90 days
- Tests: the original split series, velocity, bursts and analytics API suites,
  plus comparison, regression and dashboard contract coverage (140 tests total)

### Fixed

- Snapshot timestamps without a timezone were read as local time, which merged
  or shifted whole days of history outside UTC
- The repositories table showed fork counts under an "Updated" header
- Analytics dashboard code referenced four HTML elements that did not exist;
  its duplicate growth panels are now consolidated without losing velocity badges
- The injected Cloudflare challenge script was removed from the offline dashboard
- Analytics tests and API imports now pass the configured ruff checks
- `radar.db` is ignored and no longer tracked by git

## [0.5.0] — 2026-08-31

### Added

- `analytics` package: daily star series built from raw snapshots, sliding-window
  velocity, linear-regression (OLS) trend slope with R²
- Burst detection: rolling mean/std z-scores, grouping of consecutive spikes into
  events with duration, peak day and severity score
- Analytics service layer on top of the DB and a batch history query
  (`fetch_histories`) that loads several repositories in one round trip
- REST API under `/api/v1/analytics`:
  - `GET /analytics/velocity/{owner}/{name}` (custom `windows`, `days`)
  - `GET /analytics/bursts/{owner}/{name}` (`days`, active-burst flag)
  - `GET /analytics/leaderboard` (paginated, `window` 7/30/90)
- CLI commands: `radar velocity`, `radar bursts`, `radar leaderboard`
- Background APScheduler job: periodic snapshots inside the API lifespan,
  toggled by `RADAR_SCHEDULER_ENABLED` / `RADAR_SCHEDULER_INTERVAL_HOURS`
- Tunable analytics settings in `.env`: rolling window, z-threshold, minimum
  delta, minimum burst length and history depth

### Changed

- `/repos/{owner}/{name}` detail now returns `velocities` and `active_burst`
- `/trends` items now carry `stars_per_day` (new `TrendOut` schema)
- Codebase reformatted with ruff (100-column line length)

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
