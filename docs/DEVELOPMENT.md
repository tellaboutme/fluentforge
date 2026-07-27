# Development

## Requirements

- Python 3.10 or newer (3.12 recommended)
- [uv](https://docs.astral.sh/uv/) for Python dependency management
- Node 20+ and pnpm — only needed for `apps/web`
- Docker — **optional**, only for PostgreSQL/Redis/MinIO

## Bootstrap

A clean clone runs with no Docker, no database server, and no AI key.

```bash
make bootstrap        # uv sync + pnpm install
make migrate          # creates local-data/fluentforge.db
make load-curriculum  # loads and publishes the current curriculum version
```

Then run both services, in two terminals:

```bash
make api   # http://localhost:8000/docs
make web   # http://localhost:3000
```

Verify:

```bash
curl http://localhost:8000/ready
# {"status":"ok","database":"ok","curriculum_version":"0.2.0",...}
```

Open http://localhost:3000, create an account, and take the diagnostic. The web
app reads `NEXT_PUBLIC_API_URL` and defaults to `http://localhost:8000`.

## Databases

SQLite is the development default. To use PostgreSQL instead:

```bash
make up   # postgres, redis, minio
export DATABASE_URL=postgresql+psycopg://fluentforge:fluentforge@localhost:5432/fluentforge
make migrate && make load-curriculum
```

Models use portable column types, so the same migrations apply to both. CI runs
the PostgreSQL path on every push.

## Migrations

```bash
make migration m="add activities table"   # autogenerate from model changes
make migrate                              # apply
uv run alembic downgrade -1               # roll back one revision
```

Always review generated migrations. `alembic.ini` deliberately has no
`sqlalchemy.url`: the URL comes from application settings, so a migration cannot
target a different database than the API.

`tests/test_migrations.py` fails the build if models and migrations drift apart.

## Curriculum

Curriculum source in `curriculum/` is versioned and content-hashed.

```bash
make test-curriculum   # validate without a database
make load-curriculum   # load and publish into the database
```

Published versions are immutable. To change published curriculum, bump `version`
in `curriculum/framework.yml`; editing published source in place is rejected.

## API contract fixtures

`apps/web` has a hand-written typed client, so its types record an *assumption*
about the API. The contract tests check that assumption against payloads
captured from the real running app.

After changing any API response shape:

```bash
make capture-fixtures   # rewrites apps/web/fixtures/api-payloads.json
```

Commit the result. CI re-captures and fails if the committed fixture is stale.

The capture is deterministic on purpose: generated identifiers, timestamps and
dates are replaced with stable placeholders, and the file is written with an
explicit LF newline. Both are required for CI's re-capture-and-diff to mean
anything. Identity is preserved across the substitution — two fields holding
the same real UUID still hold the same placeholder.

## Tests

| Layer | Command | What it catches |
|---|---|---|
| Python unit/integration | `make test` | Domain logic, mastery invariants, API behaviour |
| Curriculum | `make test-curriculum` | Malformed objectives or items, unknown skill refs |
| Migrations | included in `make test` | Model/migration drift |
| Web components (jsdom) | `make test` | Labels, keyboard paths, live regions, no unearned levels |
| Web contract | `make test` | Client drifting from real API payloads |
| Browser E2E | `make e2e` | The full journey across two live servers |

E2E needs browsers once: `make e2e-install`. Playwright then starts the API and
the web server itself against a throwaway database, so no manual setup is needed.

## Before each commit

```bash
make check   # lint + typecheck + curriculum + tests, both stacks
```

`make check` deliberately excludes `make e2e`, which is slower and needs
browsers. CI runs both.

Individually: `make format`, `make lint`, `make typecheck`, `make test`,
`make test-curriculum`, `make build-web`, `make e2e`.

## Environment

Nothing is required for local development. Copy `.env.example` to `.env` only to
override a default. `JWT_SECRET` **must** be set in any shared or deployed
environment.

## Windows notes

`make` is available via Git Bash, WSL, or `choco install make`.

Without it, two PowerShell scripts stand in for the common targets.

Both are ASCII-only and saved with a UTF-8 byte-order mark, and must stay that
way. Windows PowerShell 5.1 decodes a `.ps1` without a BOM using the system
ANSI codepage, and it accepts curly quotes as string delimiters — so a stray
em dash in a string literal decodes into a quote character and breaks parsing
somewhere unrelated. Keep decoration in these two files to plain hyphens.

Run the app (migrate, seed, then both servers in their own windows):

```powershell
powershell -ExecutionPolicy Bypass -File scripts\dev.ps1
```

`-Reset` deletes the local database first, which is how you replay the
new-learner experience. `-SkipSetup` skips migration and seeding on repeat runs.

Run the full gate:

```powershell
powershell -ExecutionPolicy Bypass -File scripts\check.ps1
```

It runs bootstrap, format, fixture capture, and `make check` in order and stops
at the first failure. Windows PowerShell 5.1 has no `&&`, so chaining the
underlying commands by hand silently continues past a failure — the script
checks `$LASTEXITCODE` after every step instead.

Once dependencies are installed, `-SkipBootstrap` shortens the loop.
`-SkipFixtures` is safe only when no API response shape changed.

Each Makefile target is otherwise a single `uv run` or `pnpm` invocation and
can be run directly.
