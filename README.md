# GitHub Radar

Analytics service that tracks rising stars on GitHub: it collects data about
repositories, builds star-growth history, and detects projects that are
"taking off" before everyone else.

> **Status:** version 0.2 — CLI collector + SQLite storage with Alembic migrations.

## Features

- `radar top` — the most starred repositories (optionally saved to the DB)
- `radar search` — search with filters: query, language, minimum stars
- `radar repo owner/name` — single repository card
- `radar snapshot` — record current stats for all tracked repositories
- `radar history owner/name` — star-growth history from stored snapshots
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
```

## Storage (0.2)

Data is stored in SQLite (default `radar.db`) using SQLAlchemy async.
Schema changes are managed with Alembic migrations (`alembic/versions/`).

```bash
radar init-db                    # create tables
radar top --save                 # fetch top repos and store them
radar search --language python --save
radar snapshot                   # record current stats for tracked repos
radar history psf/requests --days 30
```

Migrations can also be run explicitly:

```bash
alembic upgrade head
```

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
└── db/              # SQLAlchemy async: engine, models, db helpers
alembic/             # database migrations
```