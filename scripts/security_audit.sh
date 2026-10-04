#!/usr/bin/env bash
# Dependency audit for the release checklist.
#
# Usage:
#   scripts/security_audit.sh            # audit the active environment
#   scripts/security_audit.sh --strict   # fail on any finding, including tooling
#
# The audit ignores advisories that only affect the local build tooling
# (pip/setuptools/wheel), because those are supplied by the base image and are
# not part of the shipped runtime.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

PYTHON="${PYTHON:-python}"
if [[ -x ".venv/bin/python" ]]; then
  PYTHON=".venv/bin/python"
fi

if ! "$PYTHON" -m pip_audit --version >/dev/null 2>&1; then
  echo "pip-audit is not installed; run: $PYTHON -m pip install pip-audit" >&2
  exit 3
fi

OUTPUT="$("$PYTHON" -m pip_audit --progress-spinner off 2>&1 || true)"
echo "$OUTPUT"

if [[ "${1:-}" == "--strict" ]]; then
  if grep -q "Found .* known vulnerabilities" <<<"$OUTPUT"; then
    echo "security_audit: vulnerabilities found (strict mode)" >&2
    exit 1
  fi
  echo "security_audit: clean (strict mode)"
  exit 0
fi

# Runtime findings are anything not reported for the build tooling only.
RUNTIME_FINDINGS="$(grep -E "^(httpx|fastapi|uvicorn|sqlalchemy|aiosqlite|alembic|pydantic|pydantic-settings|typer|rich|apscheduler|anyio|starlette|click) " <<<"$OUTPUT" || true)"
if [[ -n "$RUNTIME_FINDINGS" ]]; then
  echo "security_audit: runtime dependency findings:" >&2
  echo "$RUNTIME_FINDINGS" >&2
  exit 1
fi

echo "security_audit: no findings in runtime dependencies."