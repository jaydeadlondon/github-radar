# Public contract audit (v1.0)

This document is the inventory that the v1.0 freeze is based on. It lists every
public surface of GitHub Radar (CLI, REST API, dashboard, database schema and
artifacts), classifies the changes that v1.0 introduces, and records what is
explicitly **not** part of the contract.

Scope of the audit: commit `v0.9.0` → `v1.0.0`.

- **Stable** — covered by the v1.0 compatibility guarantee. Removing, renaming or
  changing the meaning of these items requires `/api/v2`, a deprecation cycle, or
  a major CLI version.
- **Internal** — implementation detail. May change in any release.
- **Reserved** — accepted but only documented as best-effort.

## 1. CLI surface

Entry point: `radar` (`collector.cli:app`), installed from `pyproject.toml`.

| Command | Status | Output formats |
| --- | --- | --- |
| `radar version` | stable | text, `--output json` |
| `radar init-db` | stable (mutating) | text |
| `radar migrate` | stable (mutating) | text |
| `radar doctor` | new in v1.0 | text, `--output json` |
| `radar backup` | new in v1.0 | text, `--output json` |
| `radar restore` | new in v1.0 | text, `--output json` |
| `radar db status` | new in v1.0 | text, json, csv |
| `radar prune` | new in v1.0 (mutating) | text, json, csv |
| `radar serve` | stable (long running) | n/a |
| `radar worker` | stable (long running) | n/a |
| `radar snapshot` | stable (mutating) | text, json |
| `radar top` | stable | table, json, csv |
| `radar search` | stable | table, json, csv |
| `radar repo` | stable | table, json |
| `radar history` | stable | table, json, csv |
| `radar velocity` | stable | table, json, csv |
| `radar bursts` | stable | table, json, csv |
| `radar leaderboard` | stable | table, json, csv |
| `radar backfill` | stable (mutating) | table, json, csv |
| `radar quota` | stable | table, json, csv |
| `radar export` | stable (artifact writer) | json, csv |
| `radar repos list/add/remove/pause/resume/refresh` | stable | list: table, json, csv |
| `radar alerts add/list/enable/disable/delete/events/acknowledge/acknowledge-all` | stable | list/events: table, json, csv |
| `radar notifications add/list/enable/disable/test/deliveries` | stable | list/deliveries: table, json, csv |

Global flags (apply to every command):

- `--no-color` — disable ANSI styling and emoji-free plain output.
- `--quiet` — suppress human-friendly progress lines (`Error:` is still printed).
- `--output/-o table|json|csv` — default `table`. Commands that already own the
  `--output` flag (for example `radar export --output FILE`) keep their local
  meaning; those commands use `--format` / positional arguments as documented.

Exit codes are part of the contract:

| Code | Meaning |
| --- | --- |
| `0` | success |
| `1` | runtime failure (not found, GitHub error, failed delivery, failed job) |
| `2` | usage error (bad arguments, unsupported format, unsafe URL) |
| `3` | configuration error (unsafe production config, bad settings) |
| `4` | database error (missing/not migrated database, backup/restore failure) |
| `130` | interrupted by the user (`Ctrl+C`, aborted confirmation) |

Behavioral guarantees:

- **No database** — read-only commands exit `4` with a hint (`radar init-db`,
  `radar migrate`); they never create or mutate a database implicitly.
- **No GitHub token** — commands that call GitHub print a warning on stderr
  explaining anonymous rate limits and continue. Commands never fail because the
  token is missing; a rejected token still produces exit `1`.
- **No tracked repositories** — commands print an empty-state message on stdout
  and exit `0`, except where a specific repository is requested (exit `1`).
- **Dangerous operations** (`repos remove`, `alerts delete`, `notifications
  disable`, `restore`, `prune`) require `--yes` or an interactive confirmation.
  With `--output json`/`--quiet` (non-interactive) the confirmation is skipped
  only when `--yes` is passed; otherwise exit `2`.
- **JSON output** is a single JSON document on stdout, machine-readable, with no
  styling, no progress lines and stable key names.
- **CSV output** is RFC 4180 with a header row, `\n` line endings and the same
  column names as the table output.

## 2. REST API surface

Namespace: `/api/v1` (configurable via `RADAR_API_PREFIX`, default `/api/v1`).
Unversioned operational endpoints: `GET /health`, `GET /ready`, `GET /metrics`.

| Method | Path | Status |
| --- | --- | --- |
| GET | `/api/v1/repos` | stable |
| GET | `/api/v1/repos/{owner}/{name}` | stable |
| GET | `/api/v1/repos/{owner}/{name}/history` | stable |
| GET | `/api/v1/repos/{owner}/{name}/history/quality` | stable |
| GET | `/api/v1/repos/{owner}/{name}/status` | stable |
| POST/DELETE | `/api/v1/repos/{owner}/{name}/track` | stable (admin) |
| PATCH | `/api/v1/repos/{owner}/{name}/tracking` | stable (admin) |
| POST | `/api/v1/repos/{owner}/{name}/refresh` | stable (admin) |
| GET | `/api/v1/trends` | stable |
| GET | `/api/v1/languages` | stable |
| GET | `/api/v1/analytics/velocity/{owner}/{name}` | stable |
| GET | `/api/v1/analytics/series/{owner}/{name}` | stable |
| GET | `/api/v1/analytics/bursts/{owner}/{name}` | stable |
| GET | `/api/v1/analytics/compare` | stable |
| GET | `/api/v1/analytics/leaderboard` | stable |
| GET/POST | `/api/v1/alerts/rules` | stable |
| GET/PATCH/DELETE | `/api/v1/alerts/rules/{rule_id}` | stable |
| GET | `/api/v1/alerts/events` | stable |
| GET/PATCH | `/api/v1/alerts/events/{event_id}` | stable |
| POST | `/api/v1/alerts/events/acknowledge-all` | stable |
| GET | `/api/v1/alerts/summary` | stable |
| GET/POST | `/api/v1/alerts/endpoints` | stable |
| PATCH/DELETE | `/api/v1/alerts/endpoints/{endpoint_id}` | stable |
| POST | `/api/v1/alerts/endpoints/{endpoint_id}/test` | stable |
| GET | `/api/v1/alerts/deliveries` | stable |
| POST | `/api/v1/alerts/deliveries/{delivery_id}/retry` | stable |
| GET | `/api/v1/ops/github/rate-limit` | stable |
| GET | `/api/v1/ops/config` | stable (admin) |
| GET | `/api/v1/jobs`, `/api/v1/jobs/{job_id}` | stable |

Cross-cutting contract (frozen, see `docs/API_V1.md`):

- pagination envelope `{total, offset, limit, next_offset, items}`;
- error envelope `{detail, code, request_id, type}` with `detail`/`code`
  guaranteed and extra fields explicitly allowed;
- datetimes in RFC 3339 UTC (`...Z` or `+00:00`), dates as `YYYY-MM-DD`;
- authentication via `X-API-Key` (`read` and `admin` scopes);
- response headers `X-Request-ID`, `X-API-Version: v1`, `X-API-Compatibility: stable`;
- rate limiting: none built in (single-node SQLite deployment); documented
  protections are request size limits and outbound timeouts.

## 3. Dashboard (UI) surface

Static single-page app served by the API from `/`:

- `web/index.html`, `web/styles.css`, `web/app.js`, `web/charts.js`,
  `web/favicon.svg`, `web/vendor/echarts.min.js` (offline, no CDN).
- Consumed endpoints: `/health`, `/api/v1/repos`, `/api/v1/repos/{owner}/{name}`,
  `/api/v1/repos/{owner}/{name}/series`-style analytics endpoints,
  `/api/v1/languages`, `/api/v1/analytics/leaderboard`,
  `/api/v1/analytics/compare`, `/api/v1/alerts/*`.
- Local storage keys `radar-theme`, `radar-smooth` (reserved; unknown keys are
  ignored).
- Deep links: `?repo=owner/name` selects a repository when present.
- Idempotent refresh: `Refresh` re-reads every visible panel; polling only runs
  while the alerts panel is open and the tab is visible.

The UI is a visual client of the stable API. DOM structure and CSS class names
are **internal**; only the documented endpoints and `radar-*` storage keys are
reserved.

## 4. Database and artifacts

Stable schema objects (see `docs/DOMAIN_MODEL.md` and
`docs/DATABASE_LIFECYCLE.md`): `repositories`, `repo_snapshots`, `alert_rules`,
`alert_events`, `alert_deliveries`, `notification_endpoints`, `snapshot_jobs`,
`job_locks`, `alembic_version`.

Stable artifacts:

- OpenAPI document (`docs/openapi-v1.json`, also served at `/openapi.json`);
- CLI export format (`radar export`), `format_version` bumped to `1.0`;
- backup archives produced by `radar backup` (single SQLite file copy);
- Alembic revision identifiers accepted by `radar migrate --revision`.

Never deleted automatically: repositories, snapshots, alert rules, alert events
and delivery history. `radar prune` is the only command that removes observation
history and it never runs implicitly.

## 5. Changes introduced by v1.0

### Non-breaking (additive)

| Change | Surface |
| --- | --- |
| `--output json\|csv` added to read commands | CLI |
| `--no-color`, `--quiet` global flags | CLI |
| `radar doctor`, `radar backup`, `radar restore`, `radar db status`, `radar prune` | CLI |
| `error.type` and `error.request_id` fields in error payloads | API |
| `X-Request-ID` on every response, `X-API-Version`/`X-API-Compatibility` already present | API |
| Naive datetimes now serialize with an explicit UTC offset (same instant) | API |
| `docs/openapi-v1.json` contract snapshot and compatibility test suite | API |
| Security headers, request size limit, DNS-resolved SSRF checks | API/security |
| Index migration `0007_performance_indexes` | database |
| Dashboard loading/error/empty states, keyboard navigation, mobile layout | UI |

### Breaking (must not happen inside `/api/v1` after the freeze)

- removing or renaming any stable endpoint, field, query parameter or CLI flag;
- changing pagination semantics (`total`/`offset`/`limit`/`next_offset`);
- changing error status codes for existing conditions;
- changing the meaning of `tracking_status`, `quality_status`, alert `kind`,
  `delivery_status` or job `status` values;
- switching datetimes from UTC to local time;
- changing exit codes of documented CLI failures.

## 6. Follow-up list

Items discovered during the audit but intentionally left for a later version
(they are not contract-breaking):

1. Rate limiting middleware for the API (currently deployment-level only).
2. Per-endpoint OpenAPI examples for the dashboard-facing analytics endpoints.
3. Postgres support for non-SQLite deployments (backup/restore is SQLite-only).
4. Alert delivery retry scheduling as an explicit worker queue.