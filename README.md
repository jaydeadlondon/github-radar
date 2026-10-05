# GitHub Radar

Analytics service that tracks rising stars on GitHub: it collects data about
repositories, builds star-growth history, and detects projects that are
"taking off" before everyone else.

> **Status:** version 0.9 — independently deployable API/worker services, durable jobs and
> webhook delivery, scoped API keys, operational diagnostics and structured observability.

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
- `radar notifications ...` — manage, test and inspect webhook endpoints
- `radar worker` — run the snapshot scheduler independently of the API
- `radar quota` — inspect the GitHub API rate-limit budget
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

# Notification endpoints (the secret is read from the environment when possible)
export RADAR_WEBHOOK_SIGNING_SECRET="replace-this-out-of-band"
radar notifications add primary https://hooks.example.test/radar --provider generic
radar notifications list
radar notifications test 1
radar notifications deliveries --limit 20

# Operations
radar quota
radar worker --once

## Deployment (v0.9)

### Docker Compose: documented single-command startup

The supported production baseline is Docker Compose with one migration job, one
API service, one independent worker service, and a named SQLite volume. The API
does not start the scheduler by default, so restarting either service does not
require restarting the other.

```bash
cp .env.example .env
# Set RADAR_GITHUB_TOKEN, RADAR_API_AUTH_ENABLED=true,
# RADAR_API_KEY, RADAR_ADMIN_API_KEY, and a non-wildcard RADAR_CORS_ORIGINS.
docker compose up --build -d
curl http://127.0.0.1:8000/health
curl http://127.0.0.1:8000/ready
```

`radar-migrate` runs `alembic upgrade head` before `radar-api` and
`radar-worker`. The API and worker both use `/data/radar.db` from the
`radar-data` named volume. The image binds to `0.0.0.0`, has an HTTP healthcheck,
and runs as an unprivileged user. `RADAR_DATABASE_URL` is environment-driven;
the SQLAlchemy/Alembic layer keeps the storage boundary replaceable for a future
PostgreSQL deployment rather than coupling application code to SQLite APIs.

Useful lifecycle commands:

```bash
docker compose ps
docker compose logs -f radar-api
docker compose logs -f radar-worker
docker compose restart radar-api       # worker remains running
docker compose restart radar-worker   # API remains running
docker compose run --rm radar-migrate
```

### Backup, restore and upgrade

Back up before every migration or image update. Stop writers for a simple,
consistent SQLite file copy, and keep the backup outside the repository:

```bash
docker compose stop radar-api radar-worker
mkdir -p backups
# Replace the volume name if your Compose project name is not github-radar.
docker run --rm \\
  -v github-radar_radar-data:/data \\
  -v "$PWD/backups":/backup \\
  alpine:3.20 cp /data/radar.db /backup/radar-$(date -u +%Y%m%dT%H%M%SZ).db
docker compose up -d radar-api radar-worker
```

To restore, stop API and worker, copy the chosen backup to the volume, then
start Compose and allow the migration service to complete:

```bash
docker compose stop radar-api radar-worker
# Copy the backup to /data/radar.db using the same temporary-volume pattern.
docker compose up -d
curl http://127.0.0.1:8000/ready
```

For an upgrade: create a backup, update the checkout/image, run
`docker compose build`, then run `docker compose up -d`. The migration service
is additive and is safe for a clean database and an existing v0.7 database;
the CI migration test verifies that repositories and snapshots survive the
0003 → head path. Never run destructive downgrade commands against the live
volume.

### Troubleshooting deployment

- **API is unhealthy:** inspect `docker compose logs radar-api`; then check
  `/health` (process/DB probe) and `/ready` (DB plus Alembic schema probe).
- **Readiness is 503:** run `docker compose run --rm radar-migrate` and verify
  that API and worker use the same `RADAR_DATABASE_URL` and named volume.
- **Worker does not collect:** inspect worker logs, GitHub quota at
  `/api/v1/ops/github/rate-limit`, and job state at `/api/v1/jobs`; a stale
  lease expires after `RADAR_WORKER_LOCK_TTL_SECONDS`.
- **Port or permission errors:** keep port 8000 free and do not bind the SQLite
  file from a host path with incompatible ownership; use the named volume.
- **Authentication failures:** `401` means no key was supplied and `403` means
  the supplied key is invalid or lacks the admin scope. `/health`, `/ready` and
  `/metrics` are intentionally public diagnostics.

## Database lifecycle

Everything that touches the schema goes through the CLI; the API and worker
never migrate on startup (there is a test that fails if they ever try). The
supported path is **SQLite**; the schema itself is portable to PostgreSQL, but
only SQLite is part of the 1.0 compatibility promise.

### Commands

| Command | What it does |
| --- | --- |
| `radar db status` | Location, backend, schema revision vs. head, row counts and file size. Works on a missing database (reports `exists=false`). |
| `radar init-db` | Creates the SQLite file and stamps it at head. Safe on an existing database: it never drops data. |
| `radar migrate` | Runs Alembic to head. `radar migrate --check` reports drift without writing (`0` = up to date, `4` = migration needed or database missing). |
| `radar backup [DEST]` | Online SQLite backup to `radar-backup-<UTC timestamp>.db` (or a directory you name). Uses the SQLite backup API, so writers do not need to stop. |
| `radar restore FILE [--force] [--yes]` | Replaces the current database and keeps `<db>.pre-restore-<UTC timestamp>.bak`. Refuses to touch a live database without `--force`. |
| `radar prune [--dry-run] [--keep-days N] [--keep-min-per-repo N]` | Deletes **snapshots** older than the retention window, always keeping a configurable minimum per repository. Never touches repositories, alert rules, alert events or notification endpoints. |
| `radar doctor` | Read-only configuration, connectivity and schema diagnostics. |
| `radar db optimize` | Refreshes SQLite planner statistics (`PRAGMA optimize`); also runs on API/worker shutdown. |

### Supported schema versions and upgrade path

- One migration head per release; at 1.0 the head is **0007**.
- Upgrade with `radar backup`, then `radar migrate`, then `radar db status`.
  Migrations are additive: no step in the 0001 → 0007 chain deletes or rewrites
  user rows, and the test suite upgrades a populated v0.3 (0003) database and a
  v0.6 (0006) database to head and verifies that repositories and snapshots
  survive unchanged.
- `radar migrate --check` exits `4` when the database is missing or behind, so a
  deployment script can gate on it before starting the API.
- Downgrades are not part of the contract. Each migration does define
  `downgrade()` for development, but no downgrade path is validated or
  supported.

### Failed migrations

Alembic runs each migration in a transaction. If a step fails:

1. the process exits with code `4` (`ExitCode.DATABASE`) and prints the failing
   revision — no traceback;
2. the transaction rolls back, leaving the previous revision intact;
3. `radar db status` still reports the old revision, so the schema is ready to
   retry after the cause is fixed.

The API refuses to serve data from a schema that is not at head: `/ready`
returns `503` until `radar migrate` has been run.

### Data is never auto-deleted

- `init-db`, `migrate`, `backup`, `restore` and `db optimize` never delete data.
- `restore` moves the previous database aside as `.pre-restore-<timestamp>.bak`
  instead of removing it.
- `prune` is the only command that deletes anything, only snapshots, only with
  the retention window you pass, and it prints exactly what it would delete.
  `radar prune --dry-run -o json` reports the cutoff and the counts without
  writing.
- Removing a repository from tracking (`radar repos remove`, dashboard "Stop")
  keeps its snapshots; only an explicit `radar prune` ages them out.

### Snapshot retention

Snapshots are the only table that grows without bound (one row per repository
per collection run). The default retention keeps 365 days and at least 30
snapshots per repository, so charts keep working after a prune. A weekly
`radar prune` (cron, `docker compose run --rm radar-worker radar prune`) keeps a
multi-year installation around a few hundred megabytes; see
`scripts/benchmark.py` for the size of a representative dataset.

## REST API

Start the server:

```bash
radar serve --host 0.0.0.0 --port 8000
```

Interactive docs: <http://127.0.0.1:8000/docs> (OpenAPI).

| Method | Path | Description |
|---|---|---|
| GET | `/health` | Public liveness and DB probe |
| GET | `/ready` | Public readiness: DB and Alembic schema probe |
| GET | `/metrics` | Public Prometheus-compatible in-process metrics |
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
| GET, POST | `/api/v1/alerts/endpoints` | List or create redacted notification endpoints |
| PATCH, DELETE, POST | `/api/v1/alerts/endpoints/{id}` | Rotate, enable/disable, delete or test an endpoint |
| GET | `/api/v1/alerts/deliveries` | Paginated delivery history and retry state |
| POST | `/api/v1/alerts/deliveries/{id}/retry` | Retry one failed delivery (admin scope) |
| GET | `/api/v1/jobs` | Paginated snapshot job status (`running`, `succeeded`, `failed`, `skipped`) |
| GET | `/api/v1/jobs/{job_id}` | Snapshot job detail and repository counters |
| GET | `/api/v1/ops/github/rate-limit` | Current GitHub quota and reset time |
| GET | `/api/v1/ops/config` | Safe configuration diagnostics; never secrets |

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
Datetime values are ISO-8601 UTC strings, nullable fields are explicit `null`,
and enum values are documented in the generated OpenAPI document at `/docs` and
`/openapi.json`. Every `/api/v1` response includes `X-API-Version: v1` and
`X-API-Compatibility: stable`.

When `RADAR_API_AUTH_ENABLED=true`, send `X-API-Key`. A read key is required for
read endpoints and the admin key is required for mutations; missing and invalid
keys return `401` and `403` respectively. `/health`, `/ready` and `/metrics`
remain public. Secrets are write-only for notification management and are never
returned in API errors, structured logs or configuration diagnostics.

The v1 compatibility policy is additive within a minor release: new fields and
endpoints are allowed, existing fields keep their type/nullable/enum semantics,
and pagination/sorting parameters remain stable. A breaking change requires a
new API prefix. A deprecated field or endpoint is documented for at least one
release and may emit a deprecation notice before removal. The OpenAPI surface is
checked by `tests/test_api_contract_v09.py`.
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

Webhook delivery is optional and supports durable, independently inspectable
notification endpoints. Each attempt is stored in `alert_deliveries`, includes
HTTP/error/timing state, uses bounded exponential backoff, and can be retried
from the API or CLI. A generic JSON payload is signed with
`X-GitHub-Radar-Signature-256: sha256=<digest>` when a signing secret is set.
Slack and Discord providers use their compatible `text`/`content` payloads.
After the configured consecutive failure threshold an endpoint is disabled;
re-enabling it resets the failure counter. A successful delivery resets the
counter as well.

```bash
RADAR_ALERTS_ENABLED=true
RADAR_WEBHOOK_MAX_ATTEMPTS=5
RADAR_WEBHOOK_BACKOFF_BASE_SECONDS=1
RADAR_WEBHOOK_DISABLE_AFTER_FAILURES=5
RADAR_GITHUB_RATE_LIMIT_WARNING_REMAINING=100
# Optional legacy single target; endpoint management is preferred:
RADAR_ALERT_WEBHOOK_URL=https://example.com/hooks/github-radar
```

## Background snapshots and worker lifecycle

The production API is intentionally scheduler-free. Run the scheduler in the
separate worker service:

```bash
radar serve --host 0.0.0.0 --port 8000
radar worker
# one controlled run:
radar worker --once
```

Each snapshot job has durable status and retry state. A database lease prevents
two workers from running the global snapshot job simultaneously, and a
per-repository lease prevents overlap with a manual refresh. Leases renew while
a job runs and expire after `RADAR_WORKER_LOCK_TTL_SECONDS`; SIGINT/SIGTERM
causes graceful scheduler shutdown. GitHub transient failures are retried with
backoff and are recorded as failures rather than zero-valued snapshots.

For local development only, `radar serve --with-scheduler` or
`RADAR_SCHEDULER_ENABLED=true` keeps the legacy in-process scheduler available.
Do not enable it alongside `radar worker` for the same database.

## Security and observability

Production startup rejects insecure configuration: API auth must be enabled,
read/admin keys must be present, CORS must be explicit, and log format must be
`text` or `json`. Generate and rotate keys outside Git and shell history. JSON
logs contain request ID, repository, operation, duration, result, error category,
snapshot/job ID and delivery identifiers; webhook URLs, API keys and signing
secrets are redacted or omitted.

The metrics endpoint exposes HTTP request counts/durations, GitHub request
success/failure and quota gauges, tracked/stale repositories, snapshot/job
outcomes, alert events and webhook deliveries. GitHub rate-limit headers are
captured without logging the token; inspect quota with `radar quota` or the
operations endpoint before a worker run.

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

The test suite preserves the 0.5–0.8 analytics/API/alert coverage and adds
tracking migrations, data-quality validation, collection status, backfill,
export, tracking API/CLI, worker locking, job lifecycle, notification delivery,
authentication, operational endpoints, OpenAPI contract checks and v0.7→v0.9
upgrade coverage.

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
