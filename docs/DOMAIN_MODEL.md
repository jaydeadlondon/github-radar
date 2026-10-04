# Stable domain model (v1.0)

This document freezes the public entities of GitHub Radar. It is the reference
for the REST API, the CLI JSON output, the export artifacts and the database.

Conventions used below:

- **required** — always present in API/export payloads;
- **optional** — may be `null` or absent when the value is unknown;
- **internal** — present in the database but not part of the public payloads;
- datetime values are UTC, RFC 3339, with an explicit offset (`...Z`);
- day values are UTC calendar days (`YYYY-MM-DD`);
- monetary/rate values are floats, counts are integers.

## 1. Repository

A GitHub project known to the system. Known does not imply tracked.

| Field | Kind | Notes |
| --- | --- | --- |
| `id` | required | local surrogate key, stable for the instance |
| `full_name` | required | `owner/name`, unique, case-insensitive lookup |
| `description` | optional | GitHub description |
| `html_url` | required | GitHub page |
| `language` | optional | primary language reported by GitHub |
| `github_created_at`, `github_pushed_at` | optional | GitHub timestamps |
| `default_branch` | optional | GitHub default branch |
| `archived_at` | optional | set when GitHub reports the repository archived |

**Internal:** `created_at`/`updated_at` (row timestamps), `latest_stargazers`,
`latest_forks` (query-side annotations).

### Tracked repository

A repository plus tracking controls and derived collection health.

| Field | Kind | Notes |
| --- | --- | --- |
| `tracking_enabled` | required | known + collected by the worker |
| `tracking_paused` | required | enabled but skipped by scheduled collection |
| `tracking_label` | optional | free-form label, max 100 chars |
| `tracking_status` | required | one of `healthy`, `stale`, `failed`, `paused`, `untracked` |
| `snapshot_count` | required | accepted + anomalous observations |
| `history_start_at` | optional | first accepted observation |
| `last_successful_snapshot_at` | optional | last accepted observation time |
| `last_snapshot_attempt_at` | optional | last attempt, successful or not |
| `last_snapshot_error` | optional | redacted error text (no URLs, no secrets) |
| `next_snapshot_at` | optional | planned next scheduled attempt |

`tracking_status` derivation (frozen):

1. `untracked` — `tracking_enabled = false`;
2. `paused` — enabled and `tracking_paused = true`;
3. `failed` — last attempt is newer than the last success and carries an error;
4. `stale` — no successful observation, or older than the staleness horizon;
5. `healthy` — a successful observation inside the horizon.

The default horizon is `2 * RADAR_SCHEDULER_INTERVAL_HOURS`, overridable with
`RADAR_TRACKING_STALE_AFTER_HOURS`.

## 2. Snapshot

One observation of a repository at a point in time.

| Field | Kind | Notes |
| --- | --- | --- |
| `stargazers_count` | required | non-negative |
| `forks_count` | required | non-negative |
| `open_issues_count` | required | non-negative |
| `observed_at` | required | UTC timestamp, unique per repository |
| `quality_status` | required (quality endpoint) | `accepted`, `anomalous`, `rejected` |
| `quality_reason` | optional | machine-readable reason (`stars_decreased`, `large_positive_jump`, ...) |

Frozen rules:

- snapshots are immutable; a repeated observation with the same
  `(repository, observed_at)` is idempotent and returns the original row;
- a rejected observation is retained for audit but excluded from analytics,
  latest-value queries and leaderboards;
- a repository that reports fewer stars than the previous accepted observation
  produces a rejected snapshot instead of a negative delta;
- commits are never synthetic: a failed GitHub request never writes a snapshot.

## 3. Time series

Daily star history derived from snapshots (UTC days, gaps forward-filled with the
last known value).

| Field | Kind | Notes |
| --- | --- | --- |
| `day` | required | `YYYY-MM-DD` |
| `stars` | required | last known star count for that day |
| `delta` | required | change versus the previous day |
| `stars_avg`, `delta_avg` | optional | moving-average values when `smooth > 1` |

## 4. Velocity

Growth rate over a window.

| Field | Kind | Notes |
| --- | --- | --- |
| `window_days` | required | one of `7`, `30`, `90` where a window parameter is used |
| `stars_per_day` | required | `stars_gained / elapsed days` |
| `stars_gained` | required | last minus first observation in the window |
| `start_day`, `end_day` | required | inclusive UTC day bounds |

A window with fewer than two observations produces no velocity item (explicit
"insufficient history" state, never `0.0`).

**Trend** (`SlopeResult`): OLS slope over the daily series with `slope`,
`intercept`, `r_squared` and `n_points` (required when a trend is emitted).

## 5. Burst

A detected period of unusually fast growth.

| Field | Kind | Notes |
| --- | --- | --- |
| `start_day`, `end_day` | required | inclusive UTC days |
| `duration_days` | required | `end_day - start_day + 1` |
| `peak_day` | required | day with the largest `delta` |
| `peak_delta` | required | largest daily delta inside the burst |
| `total_gained` | required | sum of daily deltas inside the burst |
| `severity` | required | peak z-score ratio, `>= 1.0` |

`active_burst` (boolean) is true when the newest day of the series is at most two
days after the last burst end. Detection parameters (`RADAR_ANALYTICS_*`) tune
sensitivity and are not part of the payload contract.

## 6. Leaderboard item

One ranked repository for a window.

| Field | Kind | Notes |
| --- | --- | --- |
| `rank` | required | 1-based, dense, ordered by `stars_per_day` desc |
| `owner`, `name`, `full_name` | required | repository identity |
| `language` | optional | primary language |
| `stars` | required | latest accepted star count |
| `stars_per_day` | required | velocity in the window |
| `stars_gained` | required | stars gained in the window |

Leaderboards only include tracked repositories with enough history for the
requested window.

## 7. Alert rule

| Field | Kind | Notes |
| --- | --- | --- |
| `id` | required | local key |
| `repository` | required | `owner/name` |
| `kind` | required | `burst_started`, `velocity_above`, `stars_reached` |
| `threshold` | conditional | required for `velocity_above` / `stars_reached`, null for `burst_started` |
| `window_days` | conditional | required for `velocity_above` (7, 30 or 90) |
| `enabled` | required | disabled rules keep their history |
| `last_value` | optional | last evaluated value |
| `last_evaluated_at` | optional | last evaluation time |
| `created_at`, `updated_at` | required | row timestamps |

## 8. Alert event

| Field | Kind | Notes |
| --- | --- | --- |
| `id` | required | local key |
| `rule_id` | optional | null after the rule is deleted |
| `repository` | required | copied at creation, survives repository deletion |
| `kind` | required | same values as rules |
| `title`, `message` | required | human-readable, no secrets |
| `current_value`, `threshold` | optional | values at trigger time |
| `acknowledged_at` | optional | read state |
| `delivery_status` | required | `inbox_only`, `sent`, `failed` |
| `delivery_error` | optional | redacted transport error |
| `created_at` | required | row timestamp |

Events are deduplicated by `(rule_id, fingerprint)`; repeated evaluation is
idempotent.

## 9. Delivery

One webhook delivery attempt for an event.

| Field | Kind | Notes |
| --- | --- | --- |
| `id` | required | local key |
| `event_id` | required | owning event |
| `endpoint_id` | optional | null after the endpoint is deleted |
| `attempt` | required | 1-based attempt number |
| `status` | required | `pending`, `sent`, `failed` |
| `response_status` | optional | HTTP status when the peer answered |
| `error` | optional | redacted error, never contains the target URL |
| `attempted_at` | required | attempt start |
| `delivered_at` | optional | success time |
| `next_attempt_at` | optional | scheduled retry |

## 10. Notification endpoint

| Field | Kind | Notes |
| --- | --- | --- |
| `id` | required | local key |
| `name` | required | unique, `[A-Za-z0-9_.-]+` |
| `provider` | required | `generic`, `slack`, `discord` |
| `url_configured` | required (public) | boolean; the URL itself is never returned |
| `enabled` | required | disabled after repeated failures or manually |
| `failure_count` | required | consecutive failures |
| `disabled_at`, `last_delivery_at`, `last_error` | optional | observability |
| `created_at`, `updated_at` | required | row timestamps |

**Internal:** `url`, `signing_secret` — never serialized by the API and never
logged.

## 11. Job status

| Field | Kind | Notes |
| --- | --- | --- |
| `id` | required | UUID string |
| `job_type` | required | e.g. `snapshot` |
| `status` | required | `running`, `succeeded`, `failed`, `skipped` |
| `started_at` | required | UTC |
| `finished_at` | optional | UTC |
| `total_repositories` | required | planned work |
| `succeeded_repositories`, `failed_repositories` | required | outcome counters |
| `error` | optional | redacted failure summary |
| `created_at`, `updated_at` | required | row timestamps |

`job_locks` is internal coordination state and is never exposed by the API.

## 12. Cross-entity compatibility rules

1. Unknown JSON fields must be ignored by clients (additive evolution).
2. Enum values are closed sets; new values require `/api/v2` or a deprecation
   notice for CLI/export consumers.
3. Deleting a repository or a rule never deletes alert events; deleting an event
   cascades to its deliveries.
4. All public timestamps are UTC with an explicit offset.
5. Errors carry `detail` (human text) and `code` (HTTP status); `type` and
   `request_id` are additive diagnostics.