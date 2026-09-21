# Commit guide: tracking domain and data quality

## Scope

This commit introduces the v0.8 tracking domain without deleting any v0.7
repository or snapshot data:

- managed `tracking_enabled` / `tracking_paused` state and one user label;
- collection attempt, success, next-run and sanitized-error timestamps;
- archived/default-branch metadata;
- snapshot quality status and reason;
- UTC normalization, duplicate suppression and explicit rejection of invalid
  or decreasing star counts;
- Alembic migration `0004`.

## Migration contract

`0004` is additive. Existing repositories remain tracked, existing snapshots
are marked `accepted`, and operational timestamps are seeded from history. The
migration must work on both an empty database and a v0.7 database. It must not
be replaced by `create_all` in application startup.

## Validation

```bash
pytest -q tests/test_tracking_migration_v08.py tests/test_data_quality_v08.py
ruff check src tests conftest.py alembic
alembic upgrade head
```

## Rollback

Use `alembic downgrade 0003` only after taking a database backup. Downgrade
removes v0.8 tracking/quality columns but leaves the v0.7 alert schema intact.
