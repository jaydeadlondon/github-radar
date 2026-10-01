# Security review for v1.0

Scope: the single-node deployment described in the README (one API process, one
worker process, SQLite database, optional outbound webhooks). The review covers
the checklist required for the v1.0 release and records residual risks.

## 1. API authentication

- `X-API-Key` header with two scopes, compared in constant time
  (`hmac.compare_digest`): `RADAR_API_KEY` (read) and `RADAR_ADMIN_API_KEY`
  (read + mutations).
- `RADAR_ENVIRONMENT=production` refuses to start unless authentication is
  enabled and both keys are set.
- Mutating endpoints carry `Depends(require_admin_api_key)` individually, so
  adding a route cannot accidentally inherit read-only access to a write path.
- `/health`, `/ready` and `/metrics` are intentionally unauthenticated: they
  expose liveness and aggregate counters only, no repository data. Put them
  behind a private network or a gateway ACL if that is not acceptable.
- Keys are read from the environment (or `.env`, which is git-ignored). They are
  never logged, never echoed by `radar doctor`, and `/api/v1/ops/config` reports
  only whether a key is configured.
- **Residual risk:** no per-client rate limiting and no user accounts. Deploy
  behind a gateway that enforces authentication and quotas if the API is
  internet-facing.

## 2. Secret redaction

- `data_quality.sanitize_error` strips bearer tokens, `token=`,
  `password=`, `secret=`, `api_key=` and all URLs from errors persisted on
  repository/job rows.
- `security.redact_secret` masks GitHub token shapes (`ghp_`, `github_pat_`),
  `sk-` API keys and `X-API-Key` values before they are stored or printed.
- Notification endpoints are serialized with `url_configured: true/false` only;
  the URL and the HMAC signing secret never leave the process.
- Webhook delivery errors are summarized (`HTTP 503`,
  `ConnectError: webhook request failed`) and never include the target URL.
- **Verified by** `tests/test_security_hardening.py`,
  `tests/test_alert_webhook.py`, `tests/test_data_quality.py`.

## 3. Webhook SSRF considerations

- `validate_webhook_url` rejects non-HTTP schemes, embedded credentials,
  `localhost`/`.localhost`, cloud metadata hostnames, and any URL whose host is a
  literal private, loopback, link-local, reserved, multicast or IPv4-mapped
  address.
- `validate_outbound_url` re-validates and re-resolves the host immediately
  before every request, so a DNS record that starts pointing at a private
  address after configuration (DNS rebinding) is refused.
- Requests set `follow_redirects=False`, so a public endpoint cannot redirect
  the delivery into the internal network.
- Names that fail to resolve are left to the HTTP client, which fails closed
  with a transport error.
- **Residual risk:** a resolution race between the check and the connection is
  possible in theory (TOCTOU); the redirect ban and the address re-check reduce
  the practical window. For hard isolation, run the worker in a network
  namespace without access to internal ranges.

## 4. URL validation and request timeouts

- GitHub API base URL comes from `RADAR_API_BASE_URL` (operator-controlled), not
  from user input.
- Outbound timeouts: `RADAR_REQUEST_TIMEOUT` (default 30 s) for GitHub,
  `RADAR_ALERT_WEBHOOK_TIMEOUT_SECONDS` (default 10 s) for webhooks.
- Retries are bounded (`RADAR_MAX_RETRIES`, `RADAR_WEBHOOK_MAX_ATTEMPTS`) with
  exponential backoff and a cap (`RADAR_WEBHOOK_BACKOFF_BASE_SECONDS`).
- GitHub response bodies are parsed into a small pydantic model; unexpected
  fields are ignored rather than trusted.

## 5. Payload size limits

- `RADAR_MAX_REQUEST_BYTES` (default 262144) rejects oversized request bodies
  with `413` and `type: payload_too_large` before any handler runs.
- Snapshot values and alert thresholds are validated by pydantic
  (`ge`/`le`/`max_length`) at the edge.
- The database stores only bounded strings: labels (100), full names (255),
  errors (500 via `sanitize_error`), webhook errors (200).

## 6. CORS

- Default development value is `*`, which is incompatible with credentials;
  the middleware therefore sets `allow_credentials=False` whenever the origin
  list contains `*`.
- Production rejects wildcard CORS at startup, so an explicit origin list is
  mandatory.
- Allowed methods/headers remain wildcards; the API is header-authenticated and
  does not use cookies, so `*` does not enable ambient credential abuse.

## 7. Debug information in responses

- The application is created with FastAPI defaults (no `debug=True`), so
  unhandled exceptions return `{"detail": "Internal server error", ...}` while
  the traceback is written to the server log only.
- Request validation errors return a generic message; the offending field values
  are not echoed.
- `radar serve --reload` is refused in production (`validate_runtime_configuration`
  runs before uvicorn starts and the reloader is documented as development-only).
- **Verified by** `tests/test_security_hardening.py::test_errors_do_not_expose_tracebacks`.

## 8. Dependency audit

`pip install pip-audit && pip-audit` was run against the release environment.
Result for v1.0.0:

- no known vulnerabilities in the runtime dependencies (fastapi, uvicorn,
  sqlalchemy, aiosqlite, alembic, httpx, pydantic-settings, typer, rich,
  apscheduler);
- advisories reported for the sandbox's build tooling (`pip`, `setuptools`,
  which are not runtime dependencies and are pinned by the base image);
- `scripts/security_audit.sh` runs the audit and fails the release on findings
  that affect runtime packages.

Dependency ranges in `pyproject.toml` are lower-bounded; patch and minor
upgrades are expected to be installable without code changes.

## 9. Safe API key storage

- Keys live in the process environment or a local `.env` file that is listed in
  `.gitignore` (the repository tracks `.env.example` only).
- `Dockerfile` runs as an unprivileged user (`uid 10001`) and Compose passes the
  environment through `env_file`, so keys are not baked into images.
- `radar notifications add --signing-secret` supports
  `RADAR_WEBHOOK_SIGNING_SECRET` to keep secrets out of shell history.
- Recommendation for operators: `chmod 600 .env`, or supply secrets through your
  orchestrator's secret store; rotate GitHub tokens on suspicion of exposure.

## 10. Database lifecycle safety

- The API and the worker never run migrations. Schema creation and upgrades are
  explicit commands (`radar init-db`, `radar migrate`), verified by
  `tests/test_security_hardening.py::test_startup_never_runs_migrations`.
- `radar backup` uses SQLite's online backup API and validates the copy before
  atomically publishing it.
- `radar restore` validates the source (integrity check + required tables),
  keeps a pre-restore copy by default and refuses to overwrite without `--force`.
- `radar prune` is the only command that deletes observations and it always
  keeps the newest snapshot of every repository.

## Residual risks and accepted gaps for v1.0

| Risk | Mitigation / status |
| --- | --- |
| No API rate limiting | Documented; deploy behind a gateway |
| No multi-user accounts or RBAC | Out of scope until after v1.0 |
| SQLite single-writer limits | Documented operational constraint |
| DNS TOCTOU for webhooks | Redirect ban + per-request validation |
| Metrics/health unauthenticated | Aggregate data only; restrict at the gateway |
| No encrypted-at-rest database | Operator responsibility (disk encryption) |
