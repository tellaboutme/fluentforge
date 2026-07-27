# Deployment

Two images, both built from the repository root so the API can copy the
curriculum and the web app can resolve its workspace packages.

```bash
export JWT_SECRET="$(python -c 'import secrets; print(secrets.token_urlsafe(48))')"
docker compose -f docker-compose.yml -f docker-compose.app.yml up --build
```

`docker-compose.yml` on its own starts only PostgreSQL, Redis and MinIO — the
backing services a developer needs while running the app from source. The
`app` overlay adds the application itself. They are separate files so that
running the first does not also hand you a stale image of your own code.

## What the images deliberately do not do

**They carry no secrets, and no defaults that would substitute for one.**
`apps/api/app/settings.py` refuses to start in production with the
development JWT secret. A compose file supplying one "for convenience" would
defeat that check in exactly the environment it exists for, so `JWT_SECRET`
is required and the stack fails fast without it.

**They do not migrate on boot.** `migrate` is its own service that runs
`alembic upgrade head` and exits, and `api` waits for it to succeed. A
container that migrates as it starts races every other replica of itself, and
a failed migration would take the whole deployment down rather than one job.

**They do not run as root.** Both images create a `fluentforge` user. A web
process that is compromised should not also be able to rewrite the
application it is serving.

**They ship no development dependencies.** `uv sync --no-dev` for the API;
Next's standalone output for the web app, which carries the server and the
files Next traced rather than the whole workspace `node_modules`.

## The one thing that cannot be configured at run time

`NEXT_PUBLIC_API_URL` is a build argument, not an environment variable,
because that is what the `NEXT_PUBLIC_` prefix means: the value is inlined
into the client bundle when the image is built. An image built for one
deployment cannot be repointed at another, and an image that appeared to
accept a run-time override would silently talk to the wrong API.

## Health

The API image's healthcheck calls `GET /health`, which is liveness only and
never touches the database. `GET /ready` reports the database, the active
curriculum version and the provider modes, and is the right thing for a load
balancer to poll — but pointing a container healthcheck at it would restart a
perfectly healthy API every time PostgreSQL hiccuped.

## Curriculum

The API parses `curriculum/` at startup and hashes it into the version
record, so it is copied into the image rather than mounted. Loading it into a
fresh database is a separate step:

```bash
docker compose -f docker-compose.yml -f docker-compose.app.yml \
  run --rm api python scripts/load_curriculum.py --publish
```

## Status

Both images **build**, verified on the development machine. Neither has been
run against a real deployment, so the compose stack is unexercised end to
end: what is proven is that the images assemble and that the web build
produces standalone output, not that the containers talk to each other.

The web build failed on its first attempt in a way worth recording. There was
no `.dockerignore`, so the host's `apps/web/node_modules` -- a farm of pnpm
symlinks pointing at a store outside the workspace -- was copied into the
image, where the links dangled and shadowed the modules `pnpm install` had
created seconds earlier. The build died with "Cannot find module
next/dist/bin/next" from a directory where Next was installed. The
`.dockerignore` fixes that and, incidentally, stops every build uploading the
virtualenv, the git history and `local-data` to the daemon.
