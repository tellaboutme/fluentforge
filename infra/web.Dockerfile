# The web image.
#
# Next's standalone output, so the runtime layer carries the server and the
# traced dependencies rather than the whole `node_modules` tree -- which for
# this workspace is most of the image.
#
# `NEXT_PUBLIC_API_URL` is baked at build time, because that is what
# `NEXT_PUBLIC_` means: it is inlined into the client bundle and cannot be
# changed by an environment variable at run time. An image built for one
# deployment cannot be pointed at another, and pretending otherwise would
# produce a container that silently talked to the wrong API.

FROM node:22-slim AS build

ENV PNPM_HOME=/pnpm \
    PATH="/pnpm:$PATH" \
    NEXT_TELEMETRY_DISABLED=1
RUN corepack enable

WORKDIR /repo

# Manifests first, so a change to application code does not re-resolve the
# whole dependency graph.
COPY package.json pnpm-lock.yaml pnpm-workspace.yaml ./
COPY apps/web/package.json apps/web/
COPY packages ./packages
RUN pnpm install --frozen-lockfile

COPY apps/web ./apps/web

ARG NEXT_PUBLIC_API_URL=http://localhost:8000
ENV NEXT_PUBLIC_API_URL=$NEXT_PUBLIC_API_URL
RUN pnpm --filter web build


FROM node:22-slim AS runtime

ENV NODE_ENV=production \
    NEXT_TELEMETRY_DISABLED=1 \
    PORT=3000

RUN useradd --create-home --uid 10001 fluentforge
WORKDIR /app

# Standalone bundles the server and only the files it actually traced.
COPY --from=build /repo/apps/web/.next/standalone ./
COPY --from=build /repo/apps/web/.next/static ./apps/web/.next/static
COPY --from=build /repo/apps/web/public ./apps/web/public

USER fluentforge
EXPOSE 3000

CMD ["node", "apps/web/server.js"]
