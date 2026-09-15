# GitHub Radar

Analytics service that tracks rising stars on GitHub: it collects data about
repositories, builds star-growth history, and detects projects that are
"taking off" before everyone else.

> **Status:** version 0.6 — CLI collector, storage, REST API, analytics engine,
> background scheduler and a web dashboard with comparison charts.

## Features

- `radar top` — the most starred repositories (optionally saved to the DB)
- `radar search` — search with filters: query, language, minimum stars
- `radar repo owner/name` — single repository card
- `radar snapshot` — record current stats for all tracked repositories
- `radar history owner/name` — star-growth history from stored snapshots
- `radar velocity owner/name` — stars/day over 7/30/90 days plus an OLS trend
- `radar bursts owner/name` — detected star bursts with severity scores
- `radar leaderboard` — the fastest growing tracked repositories
- `radar serve` — REST API server
- REST API: repositories, history, trends, languages, analytics, health
- Analytics engine: daily star series, sliding-window velocity, trend slope,
  z-score burst detection and multi-repository comparison
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

Examples:

```bash
curl http://127.0.0.1:8000/api/v1/repos?language=python&limit=5
curl http://127.0.0.1:8000/api/v1/trends?window=7
curl http://127.0.0.1:8000/api/v1/repos/psf/requests/history?days=30
curl http://127.0.0.1:8000/api/v1/analytics/velocity/psf/requests?windows=7,30
curl http://127.0.0.1:8000/api/v1/analytics/leaderboard?window=30&limit=10
curl "http://127.0.0.1:8000/api/v1/analytics/series/psf/requests?days=90&smooth=7"
curl "http://127.0.0.1:8000/api/v1/analytics/compare?repos=psf/requests,pallets/flask&mode=percent"
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
- PNG export of the current chart
- Dark / light theme (remembered in localStorage), mobile-friendly layout

The frontend is plain HTML/CSS/JS with ECharts bundled locally in
`web/vendor/` — no external CDN, works fully offline.

## Tests and linter

The 140-test suite includes the original split analytics tests for series,
velocity, bursts and API behavior, plus the 0.6 comparison and regression cases.

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
├── db/              # SQLAlchemy async: engine, models, db helpers
└── api/             # FastAPI: app, deps, schemas, routes/
web/                 # dashboard: index.html, app.js, charts.js, styles.css
alembic/             # database migrations
```