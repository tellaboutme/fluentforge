#!/usr/bin/env bash
# Start the API for the Playwright suite against a throwaway database.
#
# Playwright owns this process lifetime. The database is recreated on every run,
# so the suite never depends on, or damages, a developer's working data.
#
# Environment:
#   E2E_DB_PATH     where to put the SQLite file (default: local-data/e2e.db)
#   PYTHON_BIN_DIR  bin/ of an existing virtualenv, when uv cannot manage one
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"

DB_PATH="${E2E_DB_PATH:-$REPO_ROOT/local-data/e2e.db}"
mkdir -p "$(dirname "$DB_PATH")"

# A stale database is not fatal — migrations are idempotent and the suite uses
# unique emails — so a filesystem that refuses the delete must not abort the run.
rm -f "$DB_PATH" "$DB_PATH-journal" 2>/dev/null ||
  echo "warning: could not remove $DB_PATH; reusing it" >&2

export DATABASE_URL="sqlite+pysqlite:///$DB_PATH"
export ALLOWED_ORIGINS='["http://127.0.0.1:3001","http://localhost:3001"]'

if [ -n "${PYTHON_BIN_DIR:-}" ]; then
  ALEMBIC="$PYTHON_BIN_DIR/alembic"
  PYTHON="$PYTHON_BIN_DIR/python"
  UVICORN="$PYTHON_BIN_DIR/uvicorn"
else
  ALEMBIC="uv run alembic"
  PYTHON="uv run python"
  UVICORN="uv run uvicorn"
fi

$ALEMBIC upgrade head >/dev/null
$PYTHON scripts/load_curriculum.py --publish >/dev/null

exec $UVICORN apps.api.app.main:app --host 127.0.0.1 --port 8001
