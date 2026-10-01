# REST API v1 contract

`/api/v1` is the stable namespace for GitHub Radar 1.x. The machine-readable
schema is committed at [`docs/openapi-v1.json`](openapi-v1.json) and served at
`GET /openapi.json`; the interactive documentation is at `/docs`.

Compatibility guarantees for 1.x:

- endpoints, methods, response fields and query parameters listed here are
  additive-only; new optional fields may appear at any time;
- clients **must** ignore unknown fields and unknown enum members they do not
  handle;
- removing or renaming anything, changing a status code for an existing
  condition, or changing the meaning of an existing field requires `/api/v2` or
  a documented deprecation window of at least one minor release;
- remediation for a broken contract is a code change plus a new snapshot in
  `docs/openapi-v1.json` (checked by `tests/test_api_v1_freeze.py`).

## Authentication

`X-API-Key` header. Two scopes:

| Scope | Configuration | Allows |
| --- | --- | --- |
| read | `RADAR_API_KEY` | every `GET` endpoint |
| admin | `RADAR_ADMIN_API_KEY` | read endpoints plus all mutations |

When `RADAR_API_AUTH_ENABLED=false` (development default) the API is open and
prints a startup warning. In production (`RADAR_ENVIRONMENT=production`) the
process refuses to start without both keys, auth enabled and a non-wildcard
`RADAR_CORS_ORIGINS`.

Failures: `401` (`type: auth_required`, `WWW-Authenticate: ApiKey`) when the key
is missing, `403` (`type: forbidden`) when the key is not valid for the scope.
`/health`, `/ready` and `/metrics` are intentionally unauthenticated for
orchestrators; they expose no repository data.

## Error envelope

Every error response is JSON:

```json
{
  "detail": "Repository not tracked: psf/requests.",
  "code": 404,
  "type": "not_found",
  "request_id": "0f2c9a1b7d34"
}
```

- `detail` (string) and `code` (integer HTTP status) are guaranteed;
- `type` is a stable machine-readable class: `bad_request`, `auth_required`,
  `forbidden`, `not_found`, `method_not_allowed`, `conflict`,
  `payload_too_large`, `validation_error`, `rate_limited`, `unavailable`,
  `upstream_error`, `internal_error`;
- `request_id` mirrors the `X-Request-ID` response header (send your own header
  to correlate logs);
- `500` responses never contain a traceback; the traceback is only in the
  server log.

## Datetimes

- All timestamps are UTC and RFC 3339: `2026-10-01T09:15:30.123456Z` (an
  explicit `+00:00` offset is equally valid).
- All days are `YYYY-MM-DD` UTC calendar days.
- Clients must not assume a local timezone: convert explicitly.

## Pagination

List endpoints return:

```json
{ "total": 42, "offset": 0, "limit": 20, "next_offset": 20, "items": [] }
```

- `limit` defaults to 20 (50 for alerts/jobs endpoints) and is capped at 100;
- `offset` must be `>= 0`;
- `next_offset` is `null` on the last page; `total` is the unfiltered-by-page
  count of matching rows.

Endpoints: `/repos`, `/alerts/events`, `/alerts/rules`, `/alerts/endpoints`,
`/alerts/deliveries`, `/jobs`, `/analytics/leaderboard`.

## Filtering and sorting

| Endpoint | Parameters |
| --- | --- |
| `/repos` | `language`, `q` (substring, case-insensitive), `tracking` (`tracked`, `active`, `paused`, `untracked`, `all`), `status` (`healthy`, `stale`, `failed`, `paused`, `untracked`), `label`, `sort` (`stars`, `name`, `updated`) |
| `/repos/{owner}/{name}/history` | `since`, `until`, `limit` (1..1000) |
| `/alerts/events` | `acknowledged`, `unacknowledged`, `kind` |
| `/alerts/rules` | `enabled`, `repository` |
| `/jobs` | `status` |
| `/analytics/leaderboard` | `window` (7, 30, 90), `language` |
| `/analytics/series`, `/analytics/velocity`, `/analytics/bursts` | `days`, `smooth`/`windows` where applicable |

Unknown query parameters are ignored; invalid enum values return `422`
(`type: validation_error`).

## Endpoint groups

- **Repositories** — `/repos`, `/repos/{owner}/{name}`,
  `/repos/{owner}/{name}/history`, `/history/quality`, `/status`, `/track`,
  `/tracking`, `/refresh`.
- **Analytics** — `/analytics/velocity`, `/analytics/series`,
  `/analytics/bursts`, `/analytics/compare`, `/analytics/leaderboard`,
  `/trends`, `/languages`.
- **Alerts** — `/alerts/rules`, `/alerts/events`, `/alerts/summary`,
  `/alerts/endpoints`, `/alerts/deliveries`.
- **Operations** — `/ops/github/rate-limit`, `/ops/config`, `/jobs`.
- **Health** — `/health`, `/ready`, `/metrics` (Prometheus text format).

Response headers on every request: `X-Request-ID` and, under `/api/v1`,
`X-API-Version: v1` and `X-API-Compatibility: stable`.

## Rate limits and payload limits

GitHub Radar does not implement per-client rate limiting; it is designed for a
single trusted consumer behind your own gateway. Protections in place:

- request bodies larger than `RADAR_MAX_REQUEST_BYTES` (default 262144) are
  rejected with `413` and `type: payload_too_large`;
- GitHub calls use `RADAR_REQUEST_TIMEOUT` (default 30 s) and bounded retries;
- webhook deliveries use a configurable timeout and retry budget;
- `/ops/github/rate-limit` reports the GitHub quota used by the instance.

## Caching and conditional requests

Responses are not cached server-side and no `ETag`/`Last-Modified` headers are
emitted in 1.x. Clients that poll should use `/alerts/summary` and
`/analytics/leaderboard` rather than re-reading history.

## Compatibility test suite

`tests/test_api_v1_freeze.py` pins the OpenAPI snapshot, the error envelope,
pagination and sorting semantics, UTC formatting and version headers.
`tests/test_api_contract.py` covers the field-level payload contracts.
