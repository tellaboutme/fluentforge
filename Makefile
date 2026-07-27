.PHONY: help bootstrap dev api web up down migrate migration load-curriculum \
        format lint typecheck test test-curriculum check e2e clean

PY_SOURCES := apps/api scripts services/worker tests
UV := uv

help:
	@echo "Setup:      make bootstrap        install Python (and optionally web) dependencies"
	@echo "Run:        make api | make web | make dev"
	@echo "Database:   make migrate | make migration m=\"message\" | make load-curriculum"
	@echo "Quality:    make format | lint | typecheck | test | test-curriculum | check"
	@echo "Infra:      make up | make down   (PostgreSQL/Redis/MinIO via Docker; optional)"

# --- Setup -----------------------------------------------------------------------

bootstrap:
	$(UV) sync --extra dev
	pnpm install
	@echo "Ready. Run 'make migrate && make load-curriculum', then 'make api' and 'make web'."

# --- Run -------------------------------------------------------------------------

dev:
	@echo "Run 'make api' and 'make web' in two terminals."

api:
	$(UV) run uvicorn apps.api.app.main:app --reload --port 8000

web:
	pnpm --filter web dev

up:
	docker compose up -d

down:
	docker compose down

# --- Database --------------------------------------------------------------------

# Defaults to SQLite at local-data/fluentforge.db; set DATABASE_URL for PostgreSQL.
migrate:
	$(UV) run alembic upgrade head

migration:
	@test -n "$(m)" || (echo "Usage: make migration m=\"describe the change\"" && exit 1)
	$(UV) run alembic revision --autogenerate -m "$(m)"

load-curriculum:
	$(UV) run python scripts/load_curriculum.py --publish

# Re-capture the API payloads the web contract tests assert against.
# Run this after changing any response shape.
capture-fixtures:
	$(UV) run python scripts/capture_api_fixtures.py

# --- Quality ---------------------------------------------------------------------

format:
	$(UV) run ruff format $(PY_SOURCES)
	$(UV) run ruff check --fix $(PY_SOURCES)
	pnpm -r --if-present format:write

lint:
	$(UV) run ruff format --check $(PY_SOURCES)
	$(UV) run ruff check $(PY_SOURCES)
	pnpm -r --if-present lint

typecheck:
	$(UV) run mypy apps/api/app scripts
	pnpm -r --if-present typecheck

test:
	$(UV) run pytest
	pnpm -r --if-present test

test-curriculum:
	$(UV) run python scripts/validate_curriculum.py

build-web:
	pnpm --filter web build

# The gate referenced by docs/DEFINITION_OF_DONE.md.
check: lint typecheck test-curriculum test

# Playwright starts both servers itself against a throwaway database.
# One-time setup: make e2e-install
e2e:
	pnpm --filter web e2e

e2e-install:
	pnpm --filter web exec playwright install --with-deps chromium

clean:
	rm -rf .pytest_cache .ruff_cache .mypy_cache local-data
	find . -type d -name __pycache__ -prune -exec rm -rf {} +
