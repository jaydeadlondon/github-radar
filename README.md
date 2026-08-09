# GitHub Radar

Analytics service that tracks rising stars on GitHub: it collects data about
repositories, builds star-growth history, and detects projects that are
"taking off" before everyone else.

> **Status:** version 0.1 — CLI data collector for the GitHub API.
> Next up: storage, REST API, dashboard, analytics.

## Features (0.1)

- `radar top` — the most starred repositories
- `radar search` — search with filters: query, language, minimum stars
- `radar repo owner/name` — single repository card
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
radar top --limit 10
radar search --language python --min-stars 100
radar repo psf/requests
```

Tests and linter:

```bash
pip install -e ".[dev]"
pytest
ruff check src tests
```

## Structure

```
src/
├── config.py        # settings loaded from .env
├── version.py       # package version constant
├── github/          # GitHub API client: models, errors, client
└── collector/       # CLI (typer)
```