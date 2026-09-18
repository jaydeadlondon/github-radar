# Commit guide: collection pipeline, backfill and export

## Scope

This commit makes collection operationally explicit and adds automation
surfaces:

- scheduler collection only considers enabled, non-paused repositories;
- every attempt is persisted before the GitHub request and each result is
  committed independently;
- GitHub failures are sanitized and never create a fake zero-growth snapshot;
- `radar backfill` reconstructs available daily points from paginated GitHub
  stargazer timestamps, supports `--all`, `--dry-run`, `--limit`, page limits,
  safe concurrency and resumable existing-day checks;
- `radar export` and analytics export helpers provide stable JSON/CSV output.

## Safety notes

GitHub does not expose arbitrary historical repository snapshots. Backfill only
uses timestamps available from the stargazer API and retains quality metadata;
it does not claim precision that the upstream API cannot provide. A partial
failure is reported per repository and a later run skips already persisted days.

## Validation

```bash
pytest -q tests/test_backfill_v08.py tests/test_exports_v08.py tests/test_tracking_v08.py
ruff check src tests conftest.py alembic
node --check web/app.js
```
