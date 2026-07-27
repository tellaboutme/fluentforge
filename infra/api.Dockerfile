# The API image.
#
# Multi-stage, so the runtime layer carries the interpreter, the application
# and the curriculum -- and not the compiler toolchain, the test suite, or
# the lockfile resolution that produced the environment.
#
# Two things are deliberately absent.
#
# **No secrets, and no defaults that would do.** `app/settings.py` already
# refuses to start in production with the development JWT secret. Baking one
# in "for convenience" would defeat that check in the one environment it
# exists for.
#
# **No migrations on boot.** A container that migrates as it starts races
# every other replica of itself, and a failed migration takes the whole
# deployment down instead of one job. `alembic upgrade head` is run as its
# own step -- see `infra/README.md`.

FROM python:3.12-slim AS build

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy

# uv, pinned. An unpinned installer makes the image non-reproducible in the
# one place reproducibility is the point.
COPY --from=ghcr.io/astral-sh/uv:0.5.11 /uv /usr/local/bin/uv

WORKDIR /app

# Dependencies first, as their own layer: they change far less often than the
# application does, so this is the difference between a 5-second rebuild and
# a 3-minute one.
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project

COPY apps/api ./apps/api
COPY services ./services
COPY alembic.ini ./
RUN uv sync --frozen --no-dev


FROM python:3.12-slim AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PATH="/app/.venv/bin:$PATH" \
    APP_ENV=production

# Not root. A web process that is compromised should not also be able to
# rewrite the application it is serving.
RUN useradd --create-home --uid 10001 fluentforge

WORKDIR /app

COPY --from=build /app/.venv /app/.venv
COPY --from=build /app/apps /app/apps
COPY --from=build /app/services /app/services
COPY --from=build /app/alembic.ini /app/alembic.ini

# Curriculum is read at runtime, not compiled in: the API parses it on start
# and hashes it into the version record. It has to be in the image.
COPY curriculum ./curriculum
# Evaluator prompts are versioned product logic and are read by the rubric
# providers at request time.
COPY prompts ./prompts

USER fluentforge
EXPOSE 8000

# Liveness only, matching `GET /health`, which never touches the database.
# Pointing a container healthcheck at readiness would restart a healthy API
# every time PostgreSQL hiccuped.
HEALTHCHECK --interval=30s --timeout=3s --start-period=10s --retries=3 \
    CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=2).status == 200 else 1)"

CMD ["uvicorn", "apps.api.app.main:app", "--host", "0.0.0.0", "--port", "8000"]
