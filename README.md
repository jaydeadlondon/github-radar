# GitHub Radar

Analytics service that tracks rising stars on GitHub: it collects data about
repositories, builds star-growth history, and detects projects that are
"taking off" before everyone else.

> **Status:** version 0.3 — CLI collector, SQLite storage and a REST API.

## Features

- `radar top` — the most starred repositories (optionally saved to the DB)
- `radar search` — search with filters: query, language, minimum stars
- `radar repo owner/name` — single repository card
- `radar snapshot` — record current stats for all tracked repositories
- `radar history owner/name` — star-growth history from stored snapshots
- `radar serve` — REST API server
- REST API: repositories, history, trends, languages, health
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

Examples:

```bash
curl http://127.0.0.1:8000/api/v1/repos?language=python&limit=5
curl http://127.0.0.1:8000/api/v1/trends?window=7
curl http://127.0.0.1:8000/api/v1/repos/psf/requests/history?days=30
```

Error responses use a consistent shape: `{"detail": "...", "code": 404}`.
List endpoints return a paginated envelope: `{total, offset, limit, next_offset, items}`.

## Tests and linter

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
├── collector/       # CLI (typer), store and snapshot pipeline
├── db/              # SQLAlchemy async: engine, models, db helpers
└── api/             # FastAPI: app, deps, schemas, routes/
alembic/             # database migrations
```