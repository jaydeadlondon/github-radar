# Commit guide: v0.8 release integration

## Scope

This release commit updates the package version to `0.8.0`, user agent,
README, changelog, environment template and release notes. It includes the
full v0.8 regression suite and keeps all changes on the Arena feature branch;
`main` is not modified by this release.

## Release checklist

```bash
alembic upgrade head
pytest -q
ruff check src tests conftest.py alembic
node --check web/app.js
node --check web/charts.js
git diff --check
git status --short
```

Run the migration against a copy of a real v0.7 database before production
use. Do not commit a local `radar.db` generated while testing migrations.
