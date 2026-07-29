"""Start the API for the Playwright suite against a throwaway database.

Playwright owns this process's lifetime. The database is recreated on every
run, so the suite never depends on, or damages, a developer's working data.

Python rather than bash on purpose: the previous `e2e-api.sh` needed a `bash`
on PATH, which on a Windows development machine resolves to WSL — and a broken
or absent WSL made the whole suite fail before a single test ran. Python is
already a hard requirement of this repository on every platform, so the
launcher now has no dependencies the project does not.

Environment:
    E2E_DB_PATH   where to put the SQLite file (default: local-data/e2e.db)
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
API_PORT = "8001"


def main() -> int:
    os.chdir(REPO_ROOT)

    db_path = Path(os.environ.get("E2E_DB_PATH", REPO_ROOT / "local-data" / "e2e.db"))
    db_path.parent.mkdir(parents=True, exist_ok=True)

    # A stale database is not fatal — migrations are idempotent and the suite
    # uses unique emails — so a filesystem that refuses the delete must not
    # abort the run. Windows refuses while any handle is open, which is
    # exactly the case after a previous run was killed mid-flight.
    for stale in (db_path, Path(f"{db_path}-journal")):
        try:
            stale.unlink(missing_ok=True)
        except OSError as exc:
            print(f"warning: could not remove {stale}: {exc}; reusing it", file=sys.stderr)

    env = {
        **os.environ,
        "DATABASE_URL": f"sqlite+pysqlite:///{db_path.as_posix()}",
        "ALLOWED_ORIGINS": '["http://127.0.0.1:3001","http://localhost:3001"]',
        # The suite registers dozens of accounts from one address in a few
        # minutes, which is exactly the shape the auth limiter exists to
        # stop. Left on, the browser tests would spend their time proving the
        # limiter works rather than proving the product does -- and the
        # limiter has its own tests, against the API directly, where the
        # clock can be controlled.
        "AUTH_RATE_LIMITS_ENABLED": "false",
    }

    def run(*args: str) -> None:
        result = subprocess.run(args, env=env, cwd=REPO_ROOT)
        if result.returncode != 0:
            raise SystemExit(result.returncode)

    run("uv", "run", "alembic", "upgrade", "head")
    run("uv", "run", "python", "scripts/load_curriculum.py", "--publish")

    # Replace this process rather than spawning a child, so the PID Playwright
    # holds is the server itself and its shutdown signal lands on uvicorn.
    # os.exec* does not search PATH the same way on Windows, so uvicorn runs
    # as a subprocess there and the exit code is forwarded instead.
    uvicorn = [
        "uv",
        "run",
        "uvicorn",
        "apps.api.app.main:app",
        "--host",
        "127.0.0.1",
        "--port",
        API_PORT,
    ]
    if os.name == "nt":
        return subprocess.run(uvicorn, env=env, cwd=REPO_ROOT).returncode
    os.execvpe(uvicorn[0], uvicorn, env)
    return 0  # unreachable


if __name__ == "__main__":
    raise SystemExit(main())
