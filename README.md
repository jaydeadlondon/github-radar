# GitHub Radar

Analytics service that tracks rising stars on GitHub: it collects data about
repositories, builds star-growth history, and detects projects that are
"taking off" before everyone else.

> **Status:** version 0.8 — managed repository tracking, data-quality-aware
> snapshots, CLI/API exports, background scheduler, persistent alerts and a web dashboard.

## Features

- `radar top` — the most starred repositories (optionally saved to the DB)
- `radar search` — search with filters: query, language, minimum stars
- `radar repo owner/name` — single repository card
- `radar repos add|remove|list|pause|resume|refresh` — explicitly manage tracked projects
- `radar snapshot` — record current stats for active tracked repositories
- `radar backfill owner/name --days 30` — safely fill missing daily history with dry-run support
- `radar history owner/name` — star-growth history from accepted stored snapshots
- `radar export owner/name --format json|csv` — stable analytics export
- `radar velocity owner/name` — stars/day over 7/30/90 days plus an OLS trend
- `radar bursts owner/name` — detected star bursts with severity scores
- `radar leaderboard` — the fastest growing tracked repositories
- `radar alerts ...` — create and manage rules, inspect and acknowledge events
- `radar serve` — REST API server
- REST API: repositories, tracking state, collection health, history, trends,
  languages, analytics, exports, alerts and health
- Analytics engine: daily star series, sliding-window velocity, trend slope,
  z-score burst detection and multi-repository comparison
- Snapshot data-quality layer: UTC normalization, duplicate suppression, explicit
  rejected observations, negative-star protection and anomaly reasons
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

The 0.8 migration (`0004`) adds tracking controls, collection-health timestamps
and snapshot quality metadata. It keeps existing repositories tracked, marks
existing snapshots accepted, and seeds status timestamps from existing history.
It does not delete repositories or snapshot history.

## Usage

```bash
radar version

# Query GitHub
radar top --limit 10
radar search --language python --min-stars 100
radar repo psf/requests

# Storage and managed tracking
radar init-db
radar repos add psf/requests --label "core"
radar repos list
radar repos pause psf/requests
radar repos resume psf/requests
radar repos refresh psf/requests
radar snapshot
radar history psf/requests --days 30
radar backfill psf/requests --days 30 --dry-run
radar backfill psf/requests --days 30

# Analytics
radar velocity psf/requests --history-days 180
radar bursts psf/requests --days 90
radar leaderboard --window 7 --limit 20
radar export psf/requests --format json
radar export psf/requests --format csv
radar export leaderboard --window 30 --format csv

# Alerts (the repository must already be tracked)
radar alerts add psf/requests --type milestone --threshold 100000
radar alerts add psf/requests --type velocity --threshold 100 --window 7
radar alerts add psf/requests --type burst
radar alerts list
radar alerts events --unread
radar alerts acknowledge 1
radar alerts acknowledge-all --yes

## REST API

Start the server:

```bash
radar serve --host 0.0.0.0 --port 8000
```

Interactive docs: <http://127.0.0.1:8000/docs> (OpenAPI).

| Method | Path | Description |
|---|---|---|
| GET | `/health` | Service health (incl. DB check) |
| GET | `/api/v1/repos` | List known/tracked repos (`language`, `tracking`, `status`, `label`, `sort`, `limit`, `offset`) |
| GET | `/api/v1/repos/{owner}/{name}` | Repo detail with latest snapshot and tracking state |
| POST, DELETE | `/api/v1/repos/{owner}/{name}/track` | Start/stop tracking without deleting history |
| PATCH | `/api/v1/repos/{owner}/{name}/tracking` | Enable, pause, resume or label a repository |
| GET | `/api/v1/repos/{owner}/{name}/status` | Collection health and history completeness |
| POST | `/api/v1/repos/{owner}/{name}/refresh` | Collect one snapshot immediately |
| GET | `/api/v1/repos/{owner}/{name}/history` | Accepted snapshot history (`since`, `until`, `limit`) |
| GET | `/api/v1/repos/{owner}/{name}/history/quality` | History including accepted/anomalous/rejected quality decisions |
| GET | `/api/v1/trends` | Top repos by star growth (`window` 7/30/90) |
| GET | `/api/v1/languages` | Per-language aggregates |
| GET | `/api/v1/analytics/velocity/{owner}/{name}` | Stars/day per window + OLS trend (`windows`, `days`) |
| GET | `/api/v1/analytics/bursts/{owner}/{name}` | Detected bursts and the active-burst flag (`days`) |
| GET | `/api/v1/analytics/series/{owner}/{name}` | Daily star series with deltas (`days`, `smooth`, `format=json|csv`) |
| GET | `/api/v1/analytics/leaderboard` | Fastest growing repos (`window`, `language`, `limit`, `offset`, `format=json|csv`) |
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
curl http://127.0.0.1:8000/api/v1/analytics/series/psf/requests?days=90&smooth=7
curl http://127.0.0.1:8000/api/v1/analytics/compare?repos=psf/requests,pallets/flask&mode=percent
curl -X POST http://127.0.0.1:8000/api/v1/alerts/rules \
  -H 'Content-Type: application/json' \
  -d '{"repository":"psf/requests","kind":"stars_reached","threshold":100000}'
curl http://127.0.0.1:8000/api/v1/alerts/events?acknowledged=false
curl http://127.0.0.1:8000/api/v1/repos/psf/requests/status
curl http://127.0.0.1:8000/api/v1/analytics/series/psf/requests?format=csv
curl http://127.0.0.1:8000/api/v1/analytics/leaderboard?window=30&format=csv
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
machine's timezone. Missing days are forward-filled for analytics rather than
being treated as a real zero-growth observation.

## Data quality and tracking health

Every repository has an explicit tracking state. `tracked` repositories are
collected by `radar snapshot`; `paused` repositories stay known but are skipped;
`untracked` repositories retain their history and can be re-enabled later. The
status endpoint reports `healthy`, `stale`, `failed`, `paused`, or `untracked`,
along with last attempt/success timestamps, sanitized error text, snapshot count,
and the first day of available history.

Incoming observations are normalized to UTC and deduplicated by repository and
observation timestamp. A star decrease or invalid negative count is retained as
a rejected quality record and excluded from analytics. Large positive jumps are
marked anomalous rather than silently corrected. A GitHub request failure records
an error and never creates a zero-valued snapshot.

JSON exports have a `format_version` and stable repository/series/velocity/trend/
burst keys. CSV exports use stable headers (`day,stars,delta` for a series and
`rank,owner,name,full_name,language,stars,stars_per_day,stars_gained` for the
leaderboard).

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

- Managed repository table with sorting, live search, language/label/status filters
- Track, pause, resume and manually refresh repositories from the dashboard
- Healthy, stale, failed, paused and insufficient-history states with last-error details
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

The test suite preserves the 0.5–0.7 analytics/API/alert coverage and adds
tracking migrations, data-quality validation, collection status, backfill,
export, tracking API/CLI and dashboard regression tests.

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
├── tracking/        # managed tracking state and collection-health derivation
├── data_quality.py  # UTC normalization and snapshot validation
├── db/              # SQLAlchemy async: engine, models, db helpers
└── api/             # FastAPI: app, deps, schemas, routes/
web/                 # dashboard: index.html, app.js, charts.js, styles.css
alembic/             # database migrations
```
