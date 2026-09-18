# Commit 21 — chore: release version 0.7.0

Reference implementation commit: `2c49a7946e11d2f48d1076cc1c2642c483b295e5`
Apply after: `Commit 20`

## Goal

Release version 0.7.0 with updated metadata, user agent, dashboard headers, README, and changelog.

## Files

### `CHANGELOG.md`

Replace this file with the complete post-commit content below.

````markdown
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
````

### `README.md`

Replace this file with the complete post-commit content below.

````markdown
# GitHub Radar

Analytics service that tracks rising stars on GitHub: it collects data about
repositories, builds star-growth history, and detects projects that are
"taking off" before everyone else.

> **Status:** version 0.7 — CLI collector, storage, REST API, analytics engine,
> background scheduler, persistent alerts, optional webhooks and a web dashboard.

## Features

- `radar top` — the most starred repositories (optionally saved to the DB)
- `radar search` — search with filters: query, language, minimum stars
- `radar repo owner/name` — single repository card
- `radar snapshot` — record current stats for all tracked repositories
- `radar history owner/name` — star-growth history from stored snapshots
- `radar velocity owner/name` — stars/day over 7/30/90 days plus an OLS trend
- `radar bursts owner/name` — detected star bursts with severity scores
- `radar leaderboard` — the fastest growing tracked repositories
- `radar alerts ...` — create and manage rules, inspect and acknowledge events
- `radar serve` — REST API server
- REST API: repositories, history, trends, languages, analytics, alerts, health
- Analytics engine: daily star series, sliding-window velocity, trend slope,
  z-score burst detection and multi-repository comparison
- Persistent alert engine for new bursts, velocity crossings and star milestones
- Alert inbox in the dashboard plus optional generic JSON webhook delivery
- Background snapshots on a schedule (APScheduler, opt-in)
- Smart GitHub API client: rate-limit retries, pagination, ETag request caching

## Installation

Requires Python 3.11+.

```bash
python -m venv .venv && source .venv/bin/activate
pip install -e .
```

Create `.env` from the template and set your token:

```bash
cp .env.example .env
# edit .env and fill in RADAR_GITHUB_TOKEN
```

Token: GitHub → Settings → Developer settings → Personal access tokens →
Generate new token (the `public_repo` scope is enough).

Create a new database with `radar init-db`. When upgrading an existing checkout,
apply all migrations before starting the application:

```bash
alembic upgrade head
```

The 0.7 migration creates `alert_rules` and `alert_events`; it does not modify
stored repositories or snapshot history.

## Usage

```bash
radar version

# Query GitHub
radar top --limit 10
radar search --language python --min-stars 100
radar repo psf/requests

# Storage
radar init-db
radar top --save
radar snapshot
radar history psf/requests --days 30

# Analytics
radar velocity psf/requests --history-days 180
radar bursts psf/requests --days 90
radar leaderboard --window 7 --limit 20

# Alerts (the repository must already be tracked)
radar alerts add psf/requests --type milestone --threshold 100000
radar alerts add psf/requests --type velocity --threshold 100 --window 7
radar alerts add psf/requests --type burst
radar alerts list
radar alerts events --unread
radar alerts acknowledge 1
radar alerts acknowledge-all --yes
```

## REST API

Start the server:

```bash
radar serve --host 0.0.0.0 --port 8000
```

Interactive docs: <http://127.0.0.1:8000/docs> (OpenAPI).

| Method | Path | Description |
|---|---|---|
| GET | `/health` | Service health (incl. DB check) |
| GET | `/api/v1/repos` | List tracked repos (`language`, `sort`, `limit`, `offset`) |
| GET | `/api/v1/repos/{owner}/{name}` | Repo detail with latest snapshot |
| GET | `/api/v1/repos/{owner}/{name}/history` | Snapshot history (`since`, `until`, `limit`) |
| GET | `/api/v1/trends` | Top repos by star growth (`window` 7/30/90) |
| GET | `/api/v1/languages` | Per-language aggregates |
| GET | `/api/v1/analytics/velocity/{owner}/{name}` | Stars/day per window + OLS trend (`windows`, `days`) |
| GET | `/api/v1/analytics/bursts/{owner}/{name}` | Detected bursts and the active-burst flag (`days`) |
| GET | `/api/v1/analytics/leaderboard` | Fastest growing repos (`window` 7/30/90, `language`, `limit`, `offset`) |
| GET | `/api/v1/analytics/series/{owner}/{name}` | Daily star series with deltas (`days`, `smooth`) |
| GET | `/api/v1/analytics/compare` | Up to 5 repositories on one grid (`repos`, `window`, `mode`) |
| GET, POST | `/api/v1/alerts/rules` | List or create alert rules |
| GET, PATCH, DELETE | `/api/v1/alerts/rules/{rule_id}` | Inspect, update or delete one rule |
| GET | `/api/v1/alerts/events` | Paginated inbox (`acknowledged`, `kind`) |
| GET, PATCH | `/api/v1/alerts/events/{event_id}` | Inspect or acknowledge one event |
| POST | `/api/v1/alerts/events/acknowledge-all` | Acknowledge all unread events |
| GET | `/api/v1/alerts/summary` | Unread, event and enabled-rule counts |

Examples:

```bash
curl http://127.0.0.1:8000/api/v1/repos?language=python&limit=5
curl http://127.0.0.1:8000/api/v1/trends?window=7
curl http://127.0.0.1:8000/api/v1/repos/psf/requests/history?days=30
curl http://127.0.0.1:8000/api/v1/analytics/velocity/psf/requests?windows=7,30
curl http://127.0.0.1:8000/api/v1/analytics/leaderboard?window=30&limit=10
curl "http://127.0.0.1:8000/api/v1/analytics/series/psf/requests?days=90&smooth=7"
curl "http://127.0.0.1:8000/api/v1/analytics/compare?repos=psf/requests,pallets/flask&mode=percent"
curl -X POST http://127.0.0.1:8000/api/v1/alerts/rules \
  -H 'Content-Type: application/json' \
  -d '{"repository":"psf/requests","kind":"stars_reached","threshold":100000}'
curl "http://127.0.0.1:8000/api/v1/alerts/events?acknowledged=false"
```

Error responses use a consistent shape: `{"detail": "...", "code": 404}`.
List endpoints return a paginated envelope: `{total, offset, limit, next_offset, items}`.
`/trends` items include `stars_per_day`; the repo detail also returns
`velocities` and `active_burst`.

## Analytics

Snapshots are folded into a daily star series (one point per day, forward-filled
gaps), and everything else is derived from it:

- **Velocity** — stars gained per day over 7 / 30 / 90-day sliding windows
- **Trend** — least-squares slope over the loaded history window, with R² as a
  measure of how well the line fits
- **Bursts** — days whose delta exceeds `mean + z * std` of a rolling window are
  flagged, glued into events and scored by severity (peak over baseline)
- **Comparison** — several repositories put on one day grid and rebased:
  raw stars, index 100 at the start of the window, or percent growth
- **Smoothing** — a moving average over stars or daily deltas (`smooth=7`)

Snapshot timestamps are always read as UTC, so day buckets do not shift with the
machine's timezone.

Thresholds are configurable through `.env`:

```bash
RADAR_ANALYTICS_ROLLING_WINDOW=14   # baseline window for z-scores, days
RADAR_ANALYTICS_BURST_Z=2.5         # how many sigmas make a spike
RADAR_ANALYTICS_BURST_MIN_DELTA=5   # ignore noise below this daily gain
RADAR_ANALYTICS_BURST_MIN_DAYS=2    # minimum burst length, days
RADAR_ANALYTICS_HISTORY_DAYS=180    # how deep analytics reads history
```

## Alerts and webhooks

Alert rules are evaluated after each successful manual or scheduled snapshot:

- `stars_reached` fires once when stars reach a configured milestone
- `velocity_above` fires when a 7/30/90-day velocity crosses its threshold from below
- `burst_started` fires once for each newly detected burst start

Each event is stored in the inbox before delivery. A unique rule/fingerprint key
makes evaluation idempotent across retries, and deleting a rule or repository
retains its denormalized event history. Delivery failures are recorded on the
event and never fail the snapshot job.

Webhooks are optional and use one generic JSON target:

```bash
RADAR_ALERTS_ENABLED=true
RADAR_ALERT_WEBHOOK_URL=https://example.com/hooks/github-radar
RADAR_ALERT_WEBHOOK_TIMEOUT_SECONDS=10
```

Leave `RADAR_ALERT_WEBHOOK_URL` empty for inbox-only operation. The configured URL
is never exposed by the API; use HTTPS and treat embedded webhook credentials as
secrets.

## Background snapshots

The API can refresh snapshots on its own — the scheduler starts with the app and
shuts down with it:

```bash
RADAR_SCHEDULER_ENABLED=true
RADAR_SCHEDULER_INTERVAL_HOURS=24
```

The job runs once at startup and then every `RADAR_SCHEDULER_INTERVAL_HOURS`
hours; overlapping runs are coalesced, and failures are logged without taking
the server down.

## Dashboard

The dashboard is served by the API at <http://127.0.0.1:8000/> — start it with
`radar serve` and open the address.

- Table of tracked repositories with sorting, language filter and live search
- Three chart modes: stars, daily change (bars) and growth % from the window start
- Moving-average overlay (SMA 7), log scale, wheel zoom with a range slider
- Burst periods shaded right on the chart, with a timeline and active-burst badge
- Velocity and OLS-trend badges alongside repository details and table rows
- Comparison mode: tick up to 5 repositories and overlay their curves —
  absolute, indexed to 100, or percent growth
- "Fastest growing" panel — real stars/day over 7 / 30 / 90 days
- Alert bell with unread count, filterable inbox and read acknowledgements
- Alert-rule editor for burst, velocity and milestone rules
- Visibility-aware 30-second alert polling (no WebSocket or external service needed)
- PNG export of the current chart
- Dark / light theme (remembered in localStorage), mobile-friendly layout

The frontend is plain HTML/CSS/JS with ECharts bundled locally in
`web/vendor/` — no external CDN, works fully offline.

## Tests and linter

The 233-test suite preserves the 0.6 analytics and API coverage and adds alert
migration, evaluation, deduplication, webhook, snapshot, API, CLI and dashboard
regression tests.

```bash
pip install -e ".[dev]"
pytest
ruff check src tests conftest.py alembic
```

## Structure

```
src/
├── config.py        # settings loaded from .env
├── version.py       # package version constant
├── github/          # GitHub API client: models, errors, client
├── collector/       # CLI (typer), store, snapshot pipeline and scheduler
├── analytics/       # star series, velocity, trend slope, bursts, comparison
├── alerts/          # rule validation, evaluators, orchestration and webhooks
├── db/              # SQLAlchemy async: engine, models, db helpers
└── api/             # FastAPI: app, deps, schemas, routes/
web/                 # dashboard: index.html, app.js, charts.js, styles.css
alembic/             # database migrations
```
````

### `pyproject.toml`

Replace this file with the complete post-commit content below.

````toml
[project]
name = "github-radar"
version = "0.7.0"
description = "Analytics service that tracks rising stars on GitHub"
readme = "README.md"
requires-python = ">=3.11"
dependencies = [
    "httpx>=0.27",
    "typer>=0.12",
    "pydantic-settings>=2.2",
    "rich>=13.7",
    "sqlalchemy[asyncio]>=2.0",
    "aiosqlite>=0.19",
    "alembic>=1.12",
    "fastapi>=0.110",
    "uvicorn[standard]>=0.29",
    "apscheduler>=3.10,<4",
]

[project.optional-dependencies]
dev = [
    "pytest>=8.0",
    "pytest-asyncio>=0.23",
    "ruff>=0.4",
]

[project.scripts]
radar = "collector.cli:app"

[build-system]
requires = ["setuptools>=68"]
build-backend = "setuptools.build_meta"

[tool.setuptools.packages.find]
where = ["src"]

[tool.pytest.ini_options]
testpaths = ["tests"]
asyncio_mode = "auto"

[tool.ruff]
line-length = 100
target-version = "py311"
exclude = ["alembic/versions"]

[tool.ruff.lint]
select = ["E", "F", "I", "UP", "B"]
ignore = ["B008"]
````

### `src/config.py`

Replace this file with the complete post-commit content below.

````python
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_prefix="RADAR_",
        extra="ignore",
    )

    github_token: str = ""
    api_base_url: str = "https://api.github.com"
    request_timeout: float = 30.0
    user_agent: str = "github-radar/0.7"
    max_retries: int = 3
    backoff_base: float = 1.0
    backoff_max: float = 60.0
    database_url: str = "sqlite+aiosqlite:///./radar.db"
    api_prefix: str = "/api/v1"
    cors_origins: list[str] = ["*"]

    analytics_rolling_window: int = 14
    analytics_burst_z: float = 2.5
    analytics_burst_min_delta: int = 5
    analytics_burst_min_days: int = 2
    analytics_history_days: int = 180

    scheduler_enabled: bool = False
    scheduler_interval_hours: int = 24

    alerts_enabled: bool = True
    alert_webhook_url: str = ""
    alert_webhook_timeout_seconds: float = 10.0


settings = Settings()
````

### `src/version.py`

Replace this file with the complete post-commit content below.

````python
__version__ = "0.7.0"
````

### `web/charts.js`

Replace this file with the complete post-commit content below.

````javascript
/* GitHub Radar dashboard — ECharts helpers (v0.7). */
/* Global state shared with app.js (defined in app.js). */
/* eslint-disable no-undef */
const chart = echarts.init(document.getElementById("chart"));
const AXIS_TEXT_COLOR = getComputedStyle(document.body)
  .getPropertyValue("--text-muted")
  .trim();
const CHART_COLORS = {
  line: getComputedStyle(document.body).getPropertyValue("--accent").trim(),
  accentStrong: getComputedStyle(document.body)
    .getPropertyValue("--accent-strong")
    .trim(),
  average: getComputedStyle(document.body).getPropertyValue("--yellow").trim(),
  split: getComputedStyle(document.body).getPropertyValue("--border").trim(),
  text: AXIS_TEXT_COLOR,
};
function baseGrid(withZoom = false) {
  return { left: 48, right: 16, top: 16, bottom: withZoom ? 62 : 36 };
}
/** Wheel zoom on the plot plus a draggable range slider underneath. */
function baseDataZoom() {
  return [
    {
      type: "inside",
      throttle: 50,
      zoomOnMouseWheel: true,
      moveOnMouseMove: true,
    },
    {
      type: "slider",
      height: 18,
      bottom: 12,
      borderColor: CHART_COLORS.split,
      fillerColor: "rgba(88,166,255,0.15)",
      handleStyle: { color: CHART_COLORS.line },
      textStyle: { color: CHART_COLORS.text, fontSize: 10 },
    },
  ];
}
function resetZoom() {
  chart.dispatchAction({ type: "dataZoom", start: 0, end: 100 });
}
function refreshChartColors() {
  CHART_COLORS.line = getComputedStyle(document.body)
    .getPropertyValue("--accent")
    .trim();
  CHART_COLORS.accentStrong = getComputedStyle(document.body)
    .getPropertyValue("--accent-strong")
    .trim();
  CHART_COLORS.average = getComputedStyle(document.body)
    .getPropertyValue("--yellow")
    .trim();
  CHART_COLORS.split = getComputedStyle(document.body)
    .getPropertyValue("--border")
    .trim();
  CHART_COLORS.text = getComputedStyle(document.body)
    .getPropertyValue("--text-muted")
    .trim();
  chart.setOption({
    xAxis: [
      {
        axisLine: { lineStyle: { color: CHART_COLORS.split } },
        axisLabel: { color: CHART_COLORS.text },
      },
    ],
    yAxis: [
      {
        axisLine: { lineStyle: { color: CHART_COLORS.split } },
        axisLabel: { color: CHART_COLORS.text },
      },
    ],
  });
}
function baseTooltip() {
  return {
    trigger: "axis",
    backgroundColor: "rgba(22,27,34,0.92)",
    borderColor: CHART_COLORS.split,
    textStyle: { color: "#e6edf3", fontSize: 12 },
    valueFormatter: (value) => new Intl.NumberFormat("en-US").format(value),
  };
}
function emptyChart(message) {
  chart.clear();
  chart.setOption({
    title: {
      text: message,
      left: "center",
      top: "middle",
      textStyle: {
        color: CHART_COLORS.text,
        fontSize: 13,
        fontWeight: "normal",
      },
    },
  });
}
/**
 * Render the daily star series produced by /api/v1/analytics/series.
 * @param {string} repoName - repository full name (for the tooltip)
 * @param {Array<{day: string, stars: number, delta: number}>} points
 * @param {{mode?: string}} options
 */
function renderSeriesChart(repoName, points, options = {}) {
  if (!points.length) {
    emptyChart("No snapshots yet for this repository");
    return;
  }
  const mode = options.mode || "stars";
  const days = points.map((point) => point.day);
  const isDelta = mode === "delta";
  const isGrowth = mode === "growth";
  chart.clear();
  chart.setOption({
    tooltip: isGrowth ? percentTooltip() : baseTooltip(),
    grid: baseGrid(true),
    dataZoom: baseDataZoom(),
    xAxis: {
      type: "category",
      data: days,
      boundaryGap: isDelta,
      axisLine: { lineStyle: { color: CHART_COLORS.split } },
      axisLabel: { color: CHART_COLORS.text },
    },
    yAxis: {
      type: options.logScale && mode === "stars" ? "log" : "value",
      logBase: 10,
      min:
        options.logScale && mode === "stars"
          ? null
          : isDelta
            ? 0
            : isGrowth
              ? (value) => Math.floor(Math.min(0, value.min))
              : (value) => Math.max(0, Math.floor(value.min * 0.95)),
      axisLine: { lineStyle: { color: CHART_COLORS.split } },
      axisLabel: {
        color: CHART_COLORS.text,
        formatter: isGrowth ? "{value}%" : undefined,
      },
      splitLine: { lineStyle: { color: CHART_COLORS.split, opacity: 0.5 } },
    },
    series: [
      {
        ...modeSeries(repoName, points, mode),
        markArea: burstMarkArea(options.bursts, mode),
      },
      ...(options.smooth ? averageSeries(points, mode) : []),
    ],
  });
}
/** Shade the days that the burst detector flagged. */
function burstMarkArea(bursts, mode) {
  if (!bursts || !bursts.length) return undefined;
  const color =
    mode === "delta" ? "rgba(248,81,73,0.18)" : "rgba(210,153,34,0.16)";
  return {
    silent: true,
    itemStyle: { color },
    label: { show: false },
    data: bursts.map((event) => [
      { xAxis: event.start_day, name: "burst" },
      { xAxis: event.end_day },
    ]),
  };
}
function modeSeries(repoName, points, mode) {
  if (mode === "delta") {
    return deltaBarSeries(
      `${repoName} — daily change`,
      points.map((point) => point.delta),
    );
  }
  if (mode === "growth") {
    return starLineSeries(`${repoName} — growth`, growthValues(points));
  }
  return starLineSeries(
    repoName,
    points.map((point) => point.stars),
  );
}
/** Percent growth of every point relative to the first day of the window. */
function growthValues(points) {
  const base = Math.max(points[0].stars, 1);
  return points.map(
    (point) => Math.round((point.stars / base - 1) * 10000) / 100,
  );
}
/** Moving-average overlay; the API fills stars_avg / delta_avg. */
function averageSeries(points, mode) {
  if (mode === "growth") return [];
  const key = mode === "delta" ? "delta_avg" : "stars_avg";
  const values = points.map((point) => point[key]);
  if (values.every((value) => value === null || value === undefined)) return [];
  return [
    {
      name: "Moving average",
      type: "line",
      data: values,
      smooth: true,
      symbol: "none",
      connectNulls: false,
      z: 3,
      lineStyle: { color: CHART_COLORS.average, width: 2, type: "dashed" },
      itemStyle: { color: CHART_COLORS.average },
    },
  ];
}
function percentTooltip() {
  return {
    ...baseTooltip(),
    valueFormatter: (value) =>
      `${new Intl.NumberFormat("en-US").format(value)}%`,
  };
}
function deltaBarSeries(name, values) {
  return {
    name,
    type: "bar",
    data: values,
    barMaxWidth: 18,
    itemStyle: { color: CHART_COLORS.line, borderRadius: [2, 2, 0, 0] },
    emphasis: { itemStyle: { color: CHART_COLORS.accentStrong } },
  };
}
function starLineSeries(name, values) {
  return {
    name,
    type: "line",
    data: values,
    smooth: true,
    symbol: "circle",
    symbolSize: 5,
    lineStyle: { color: CHART_COLORS.line, width: 2 },
    itemStyle: { color: CHART_COLORS.line },
    areaStyle: {
      color: {
        type: "linear",
        x: 0,
        y: 0,
        x2: 0,
        y2: 1,
        colorStops: [
          { offset: 0, color: "rgba(88,166,255,0.25)" },
          { offset: 1, color: "rgba(88,166,255,0.02)" },
        ],
      },
    },
  };
}
const COMPARE_PALETTE = ["#58a6ff", "#3fb950", "#d29922", "#f85149", "#bc8cff"];
const COMPARE_SUFFIX = { absolute: "", indexed: "", percent: "%" };
/** Render several repositories on one shared day grid. */
function renderCompareChart(days, seriesList, mode) {
  if (!days.length || !seriesList.length) {
    emptyChart("Not enough history to compare these repositories");
    return;
  }
  const suffix = COMPARE_SUFFIX[mode] || "";
  chart.clear();
  chart.setOption({
    tooltip: {
      ...baseTooltip(),
      valueFormatter: (value) =>
        value === null || value === undefined
          ? "—"
          : `${new Intl.NumberFormat("en-US").format(value)}${suffix}`,
    },
    legend: {
      top: 0,
      textStyle: { color: CHART_COLORS.text, fontSize: 11 },
      inactiveColor: CHART_COLORS.split,
    },
    grid: { left: 56, right: 16, top: 34, bottom: 62 },
    dataZoom: baseDataZoom(),
    xAxis: {
      type: "category",
      data: days,
      boundaryGap: false,
      axisLine: { lineStyle: { color: CHART_COLORS.split } },
      axisLabel: { color: CHART_COLORS.text },
    },
    yAxis: {
      type: "value",
      scale: mode !== "absolute",
      axisLine: { lineStyle: { color: CHART_COLORS.split } },
      axisLabel: { color: CHART_COLORS.text, formatter: `{value}${suffix}` },
      splitLine: { lineStyle: { color: CHART_COLORS.split, opacity: 0.5 } },
    },
    series: seriesList.map((item, index) => {
      const color = COMPARE_PALETTE[index % COMPARE_PALETTE.length];
      return {
        name: item.full_name,
        type: "line",
        data: item.values,
        smooth: true,
        symbol: "none",
        connectNulls: false,
        lineStyle: { color, width: 2 },
        itemStyle: { color },
      };
    }),
  });
}
/** Save whatever is on the chart right now as a PNG file. */
function exportChartPng(fileName) {
  const background = getComputedStyle(document.body)
    .getPropertyValue("--bg-elevated")
    .trim();
  const url = chart.getDataURL({
    type: "png",
    pixelRatio: 2,
    backgroundColor: background || "#161b22",
  });
  const link = document.createElement("a");
  link.href = url;
  link.download = fileName;
  document.body.appendChild(link);
  link.click();
  link.remove();
}
function resizeChart() {
  chart.resize();
}
window.addEventListener("resize", resizeChart);
````

### `web/styles.css`

Replace this file with the complete post-commit content below.

````css
/* GitHub Radar dashboard — base styles (v0.7) */
:root {
  --bg: #0d1117;
  --bg-elevated: #161b22;
  --bg-input: #0d1117;
  --border: #30363d;
  --text: #e6edf3;
  --text-muted: #8b949e;
  --accent: #58a6ff;
  --accent-strong: #1f6feb;
  --green: #3fb950;
  --yellow: #d29922;
  --red: #f85149;
  --radius: 8px;
  --shadow: 0 2px 8px rgba(0, 0, 0, 0.35);
}
* {
  box-sizing: border-box;
}
body {
  margin: 0;
  background: var(--bg);
  color: var(--text);
  font-family:
    -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Helvetica Neue",
    Arial, sans-serif;
  line-height: 1.5;
}
/* Top bar */
.topbar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  padding: 12px 24px;
  background: var(--bg-elevated);
  border-bottom: 1px solid var(--border);
  position: sticky;
  top: 0;
  z-index: 10;
}
.brand {
  display: flex;
  align-items: center;
  gap: 10px;
}
.brand h1 {
  font-size: 1.15rem;
  margin: 0;
  letter-spacing: 0.2px;
}
.logo {
  color: var(--accent);
}
.status-badge {
  font-size: 0.8rem;
  color: var(--text-muted);
  border: 1px solid var(--border);
  border-radius: 999px;
  padding: 3px 12px;
}
.status-badge.ok {
  color: var(--green);
  border-color: var(--green);
}
[hidden] {
  display: none !important;
}
.topbar-actions {
  display: flex;
  align-items: center;
  gap: 10px;
}
.alert-bell {
  position: relative;
}
.alert-count {
  position: absolute;
  top: -6px;
  right: -7px;
  min-width: 18px;
  height: 18px;
  padding: 0 5px;
  border: 2px solid var(--bg-elevated);
  border-radius: 999px;
  background: var(--red);
  color: #fff;
  font-size: 0.65rem;
  font-weight: 700;
  line-height: 14px;
  text-align: center;
}
.icon-btn,
.btn {
  background: var(--bg-input);
  border: 1px solid var(--border);
  color: var(--text);
  border-radius: 6px;
  padding: 8px 14px;
  font-size: 0.9rem;
  cursor: pointer;
}
.icon-btn {
  padding: 6px 10px;
}
.icon-btn:hover,
.btn:hover {
  border-color: var(--accent);
  color: var(--accent);
}
.btn.small {
  padding: 5px 9px;
  font-size: 0.78rem;
}
/* Content */
.content {
  max-width: 1200px;
  margin: 0 auto;
  padding: 24px;
}
.placeholder {
  text-align: center;
  padding: 80px 20px;
  color: var(--text-muted);
}
.placeholder h2 {
  color: var(--text);
  margin-bottom: 8px;
}
/* Cards */
.card {
  background: var(--bg-elevated);
  border: 1px solid var(--border);
  border-radius: var(--radius);
  box-shadow: var(--shadow);
  padding: 16px;
}
.card h2,
.card h3 {
  margin-top: 0;
}
/* Filters row */
.filters {
  display: flex;
  flex-wrap: wrap;
  gap: 12px;
  align-items: center;
  margin-bottom: 20px;
}
.filters input,
.filters select {
  background: var(--bg-input);
  border: 1px solid var(--border);
  color: var(--text);
  border-radius: 6px;
  padding: 8px 12px;
  font-size: 0.9rem;
}
.filters input:focus,
.filters select:focus {
  outline: none;
  border-color: var(--accent);
}
/* Alert inbox */
.alerts-panel {
  margin-bottom: 20px;
  scroll-margin-top: 76px;
}
.alerts-head,
.alerts-actions,
.alerts-filters,
.alert-event-meta,
.alert-event-footer {
  display: flex;
  align-items: center;
}
.alerts-head {
  justify-content: space-between;
  gap: 16px;
}
.alerts-head h2 {
  margin-bottom: 2px;
}
.alerts-head p {
  margin: 0;
  color: var(--text-muted);
  font-size: 0.82rem;
}
.alerts-actions,
.alerts-filters {
  gap: 8px;
}
.alerts-filters {
  margin: 16px 0 10px;
  flex-wrap: wrap;
}
.alerts-filters select {
  padding: 5px 10px;
  border: 1px solid var(--border);
  border-radius: 6px;
  background: var(--bg-input);
  color: var(--text);
}
.alert-events {
  display: grid;
  gap: 8px;
}
.alert-event {
  display: grid;
  grid-template-columns: auto minmax(0, 1fr) auto;
  gap: 12px;
  align-items: start;
  padding: 12px;
  border: 1px solid var(--border);
  border-radius: var(--radius);
  background: var(--bg);
}
.alert-event.unread {
  border-left: 3px solid var(--accent);
}
.alert-event.read {
  opacity: 0.72;
}
.alert-event-icon {
  display: grid;
  place-items: center;
  width: 30px;
  height: 30px;
  border-radius: 50%;
  background: rgba(88, 166, 255, 0.14);
}
.alert-event-body {
  min-width: 0;
}
.alert-event-meta,
.alert-event-footer {
  justify-content: space-between;
  gap: 10px;
}
.alert-event-meta {
  margin-bottom: 3px;
  color: var(--text-muted);
  font-size: 0.72rem;
}
.alert-event p {
  margin: 3px 0 8px;
  color: var(--text-muted);
  font-size: 0.84rem;
}
.alert-kind,
.delivery {
  padding: 1px 7px;
  border-radius: 999px;
  background: rgba(88, 166, 255, 0.14);
  color: var(--accent);
  font-size: 0.7rem;
  text-transform: capitalize;
}
.delivery.failed {
  background: rgba(248, 81, 73, 0.14);
  color: var(--red);
}
.delivery.sent {
  background: rgba(63, 185, 80, 0.14);
  color: var(--green);
}
.link-btn {
  border: 0;
  padding: 0;
  background: transparent;
  color: var(--accent);
  font: inherit;
  cursor: pointer;
}
.link-btn:hover {
  text-decoration: underline;
}
.btn:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}
.alert-section-tabs {
  margin-top: 16px;
}
.alert-rule-form {
  display: grid;
  grid-template-columns: repeat(4, minmax(130px, 1fr)) auto;
  gap: 10px;
  align-items: end;
  margin: 14px 0;
  padding: 12px;
  border: 1px solid var(--border);
  border-radius: var(--radius);
  background: var(--bg);
}
.alert-rule-form label {
  display: grid;
  gap: 4px;
  color: var(--text-muted);
  font-size: 0.75rem;
}
.alert-rule-form input,
.alert-rule-form select {
  width: 100%;
  padding: 7px 9px;
  border: 1px solid var(--border);
  border-radius: 6px;
  background: var(--bg-input);
  color: var(--text);
}
.alert-rules {
  display: grid;
  gap: 8px;
}
.alert-rule {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  padding: 12px;
  border: 1px solid var(--border);
  border-radius: var(--radius);
  background: var(--bg);
}
.alert-rule.disabled {
  opacity: 0.65;
}
.alert-rule-title,
.alert-rule-actions {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
}
.alert-rule p {
  margin: 4px 0 0;
  color: var(--text-muted);
  font-size: 0.8rem;
}
.btn.danger {
  color: var(--red);
}
.btn.danger:hover {
  border-color: var(--red);
}
/* Layout grid */
.grid {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 20px;
}
.grid .full {
  grid-column: 1 / -1;
}
/* Table */
.table-wrap {
  overflow-x: auto;
}
table {
  width: 100%;
  border-collapse: collapse;
  font-size: 0.9rem;
}
th,
td {
  text-align: left;
  padding: 10px 12px;
  border-bottom: 1px solid var(--border);
  white-space: nowrap;
}
th {
  color: var(--text-muted);
  font-weight: 600;
  cursor: pointer;
  user-select: none;
}
th.sortable:hover {
  color: var(--accent);
}
th .arrow {
  font-size: 0.75rem;
}
tr.repo-row {
  cursor: pointer;
}
tr.repo-row:hover {
  background: rgba(88, 166, 255, 0.08);
}
tr.repo-row.selected {
  background: rgba(88, 166, 255, 0.15);
}
td.num,
th.num {
  text-align: right;
}
.lang-badge {
  display: inline-block;
  background: rgba(88, 166, 255, 0.15);
  color: var(--accent);
  border-radius: 999px;
  padding: 2px 10px;
  font-size: 0.78rem;
}
/* Chart area */
.chart-panel {
  min-height: 360px;
  display: flex;
  flex-direction: column;
}
.chart-panel .chart-title {
  font-weight: 600;
  margin-bottom: 4px;
}
.chart-panel .chart-sub {
  color: var(--text-muted);
  font-size: 0.85rem;
  margin-bottom: 12px;
}
.cmp-col {
  width: 34px;
  text-align: center;
}
.cmp-col input {
  accent-color: var(--accent);
  cursor: pointer;
}
.compare-bar {
  display: flex;
  align-items: center;
  gap: 6px;
  flex-wrap: wrap;
  margin: 0 0 12px;
}
.chip {
  display: inline-block;
  padding: 2px 8px;
  border: 1px solid var(--border);
  border-radius: 999px;
  background: var(--bg-elevated);
  color: var(--text-muted);
  font-size: 0.75rem;
}
.burst-badge {
  display: inline-block;
  padding: 1px 8px;
  border: 1px solid var(--red);
  border-radius: 999px;
  background: rgba(248, 81, 73, 0.15);
  color: var(--red);
  font-size: 0.72rem;
  font-weight: 600;
  vertical-align: middle;
}
.chart-head {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 12px;
  flex-wrap: wrap;
}
.chart-toolbar {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
  margin-bottom: 12px;
}
.seg {
  display: inline-flex;
  border: 1px solid var(--border);
  border-radius: var(--radius);
  overflow: hidden;
}
.seg button {
  padding: 5px 10px;
  border: none;
  border-right: 1px solid var(--border);
  background: var(--bg-elevated);
  color: var(--text-muted);
  font-size: 0.8rem;
  cursor: pointer;
}
.seg button:last-child {
  border-right: none;
}
.seg button.active {
  background: var(--accent-strong);
  color: #fff;
}
.seg button:disabled {
  opacity: 0.45;
  cursor: not-allowed;
}
.toggle {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  color: var(--text-muted);
  font-size: 0.78rem;
  cursor: pointer;
  white-space: nowrap;
}
.toggle input {
  accent-color: var(--accent);
}
.toggle.disabled {
  opacity: 0.45;
  cursor: not-allowed;
}
#chart {
  flex: 1;
  min-height: 300px;
}
.section-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  flex-wrap: wrap;
}
.section-head h2 {
  margin: 0;
}
.riser-card .sub {
  color: var(--text-muted);
  font-size: 0.75rem;
}
/* New-this-week cards */
.riser-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(220px, 1fr));
  gap: 12px;
  margin-top: 12px;
}
.riser-card {
  background: var(--bg-elevated);
  border: 1px solid var(--border);
  border-radius: var(--radius);
  padding: 12px;
}
.riser-card .name {
  font-weight: 600;
  margin-bottom: 4px;
}
.riser-card .delta {
  color: var(--green);
  font-weight: 600;
}
.riser-card .rank {
  color: var(--text-muted);
  font-size: 0.78rem;
  margin-bottom: 2px;
}
.riser-card .bar {
  height: 4px;
  background: var(--border);
  border-radius: 2px;
  margin-top: 8px;
  overflow: hidden;
}
.riser-card .bar-fill {
  height: 100%;
  background: var(--green);
  border-radius: 2px;
}
/* Toasts */
#toasts {
  position: fixed;
  bottom: 16px;
  right: 16px;
  display: flex;
  flex-direction: column;
  gap: 8px;
  z-index: 100;
}
.toast {
  background: var(--bg-elevated);
  border: 1px solid var(--border);
  border-left: 3px solid var(--accent);
  border-radius: 6px;
  padding: 10px 14px;
  font-size: 0.85rem;
  max-width: 340px;
  box-shadow: var(--shadow);
  animation: toast-in 0.2s ease-out;
}
.toast.error {
  border-left-color: var(--red);
}
.toast.warn {
  border-left-color: var(--yellow);
}
@keyframes toast-in {
  from {
    opacity: 0;
    transform: translateY(8px);
  }
  to {
    opacity: 1;
    transform: translateY(0);
  }
}
/* Empty state */
.empty {
  text-align: center;
  color: var(--text-muted);
  padding: 40px 20px;
}
.empty .hint {
  font-size: 0.85rem;
  margin-top: 8px;
}
/* Spinner */
.spinner {
  display: inline-block;
  width: 18px;
  height: 18px;
  border: 2px solid var(--border);
  border-top-color: var(--accent);
  border-radius: 50%;
  animation: spin 0.8s linear infinite;
  vertical-align: middle;
}
@keyframes spin {
  to {
    transform: rotate(360deg);
  }
}
.spinner-wrap {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 10px;
  padding: 40px 0;
  color: var(--text-muted);
}
/* Light theme */
body.light {
  --bg: #ffffff;
  --bg-elevated: #f6f8fa;
  --bg-input: #ffffff;
  --border: #d0d7de;
  --text: #1f2328;
  --text-muted: #656d76;
  --shadow: 0 2px 8px rgba(140, 149, 159, 0.2);
}
/* Hover effects only on devices with a pointer */
@media (hover: hover) {
  tr.repo-row:hover {
    background: rgba(88, 166, 255, 0.08);
  }
  .riser-card:hover {
    border-color: var(--accent);
  }
}
/* Mobile */
@media (max-width: 860px) {
  .grid {
    grid-template-columns: 1fr;
  }
  .alerts-head {
    align-items: flex-start;
  }
  .alert-event {
    grid-template-columns: auto minmax(0, 1fr);
  }
  .alert-ack {
    grid-column: 2;
    justify-self: start;
  }
  .alert-rule-form {
    grid-template-columns: 1fr;
  }
  .alert-rule {
    align-items: flex-start;
    flex-direction: column;
  }
  .topbar {
    padding: 10px 16px;
  }
  .content {
    padding: 16px;
  }
  .filters {
    position: sticky;
    top: 58px;
    z-index: 5;
  }
  .filters input,
  .filters select {
    flex: 1 1 40%;
  }
  table {
    font-size: 0.8rem;
  }
  th,
  td {
    padding: 8px 10px;
  }
  #chart {
    min-height: 240px;
  }
}
/* --- analytics: leaderboard, velocity badges, burst strip --- */
.badge {
  display: inline-block;
  padding: 2px 8px;
  border-radius: 999px;
  font-size: 12px;
  font-weight: 600;
  white-space: nowrap;
}
.badge-velocity {
  background: rgba(46, 160, 67, 0.15);
  color: #3fb950;
}
.badge-trend {
  background: rgba(88, 166, 255, 0.15);
  color: #58a6ff;
}
.badge-burst {
  background: rgba(255, 123, 114, 0.15);
  color: #ff7b72;
}
.badges-row {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  margin: 8px 0;
}
.mini-velocity {
  margin-left: 6px;
  padding: 1px 6px;
  border-radius: 999px;
  font-size: 11px;
  font-weight: 600;
  background: rgba(46, 160, 67, 0.15);
  color: #3fb950;
  white-space: nowrap;
}
.burst-strip-row {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 8px;
  min-height: 14px;
}
.strip-label {
  font-size: 11px;
  color: rgba(139, 148, 158, 0.9);
  white-space: nowrap;
}
.strip-track {
  position: relative;
  flex: 1;
  height: 8px;
  border-radius: 4px;
  background: rgba(139, 148, 158, 0.12);
}
.burst-segment {
  position: absolute;
  top: 0;
  height: 100%;
  border-radius: 4px;
  background: rgba(255, 123, 114, 0.55);
}
body.light .badge-velocity {
  color: #1a7f37;
}
body.light .badge-trend {
  color: #0969da;
}
body.light .badge-burst {
  color: #cf222e;
}
body.light .mini-velocity {
  color: #1a7f37;
}
body.light .burst-segment {
  background: rgba(207, 34, 46, 0.45);
}
````

## Verify

```bash
pytest -q
ruff check src tests conftest.py alembic
node --check web/app.js
node --check web/charts.js
```

## Commit

```bash
git add -- \
  CHANGELOG.md \
  README.md \
  pyproject.toml \
  src/config.py \
  src/version.py \
  web/charts.js \
  web/styles.css
git commit -m 'chore: release version 0.7.0'
```
