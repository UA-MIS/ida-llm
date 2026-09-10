# syntax=docker/dockerfile:1
#
# ⚠ BASE IMAGES COME THROUGH THE PLATFORM'S HARBOR PULL-THROUGH CACHE
# (`dockerhub-proxy`), not straight from Docker Hub. Two reasons, both load-bearing
# on this platform:
#   1. Docker Hub anonymous rate limits are shared across the whole cluster's
#      egress, so a direct `node:24.16-alpine` pull fails intermittently under
#      load -- and it fails INSIDE Kaniko, where the error reads as a build
#      problem rather than a registry quota.
#   2. Every other image in this repo is already pulled this way, so leaving one
#      component on the direct path makes the build's reliability depend on which
#      component happens to build first.
# Pinned via ARG so a local `docker build --build-arg NODE_IMAGE=node:24.16-alpine`
# still works off-cluster with no edit.
ARG NODE_IMAGE=harbor.capstone.uamishub.com/base-images/library/node:24.16-alpine
#
# Build context is the REPO ROOT (matches .devops/components.yaml `context: .`),
# so every path below is repo-relative. Build locally with:
#   docker build -f apps/agile/Dockerfile -t ida-llm-agile .

FROM ${NODE_IMAGE} AS deps
WORKDIR /app
COPY apps/agile/package.json apps/agile/package-lock.json ./
# ⚠ RETRIED, and deliberately not left to npm. This install runs inside the
# image build, so the retry wrapped around the CI workflow's own `npm ci` does
# not cover it -- a registry timeout here fails the BUILD, which fails the push,
# which skips the dev bump. That is exactly how a green merge left dev serving
# a stale commit. npm's `fetch-retries` was tried first and does not catch the
# socket-read timeout this egress path produces.
RUN n=1; until npm ci --no-audit --no-fund; do \
      if [ "$n" -ge 4 ]; then echo "npm ci failed 4 times -- not a blip" >&2; exit 1; fi; \
      echo "npm ci failed (attempt $n/4) -- retrying in $((n * 15))s" >&2; \
      sleep $((n * 15)); n=$((n + 1)); \
    done

FROM ${NODE_IMAGE} AS builder
WORKDIR /app
COPY --from=deps /app/node_modules ./node_modules
COPY apps/agile/ ./
ENV NEXT_TELEMETRY_DISABLED=1
RUN npm run build

FROM ${NODE_IMAGE} AS runner
WORKDIR /app
ENV NODE_ENV=production \
    NEXT_TELEMETRY_DISABLED=1 \
    PORT=8080 \
    HOSTNAME=0.0.0.0

# 65532 ("nonroot") is the uid the platform chart pins via runAsUser.
RUN addgroup -g 65532 -S nonroot && adduser -S -u 65532 -G nonroot nonroot

# `output: 'standalone'` emits a minimal server plus only the deps it needs.
COPY --from=builder --chown=65532:65532 /app/.next/standalone ./
COPY --from=builder --chown=65532:65532 /app/.next/static ./.next/static
# Migrations are read from disk at startup, so they must ship in the image.
COPY --from=builder --chown=65532:65532 /app/src/lib/db/migrations ./src/lib/db/migrations
# The in-app API reference reads this at request time.
COPY --from=builder --chown=65532:65532 /app/docs ./docs
# `output: 'standalone'` does NOT bundle public/ -- it is served from disk at
# runtime, so it has to be copied explicitly or every static asset 404s.
COPY --from=builder --chown=65532:65532 /app/public ./public

USER 65532:65532
EXPOSE 8080

# No writable state on the filesystem: everything durable is in Postgres, and
# uploads go to object storage. The container can run with a read-only rootfs.
CMD ["node", "server.js"]
