# syntax=docker/dockerfile:1
#
# Build context is the REPO ROOT (matches .devops/components.yaml `context: .`),
# so every path below is repo-relative. Build locally with:
#   docker build -f apps/agile/Dockerfile -t ida-llm-agile .

FROM node:24.16-alpine AS deps
WORKDIR /app
COPY apps/agile/package.json apps/agile/package-lock.json ./
RUN npm ci --no-audit --no-fund

FROM node:24.16-alpine AS builder
WORKDIR /app
COPY --from=deps /app/node_modules ./node_modules
COPY apps/agile/ ./
ENV NEXT_TELEMETRY_DISABLED=1
RUN npm run build

FROM node:24.16-alpine AS runner
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

USER 65532:65532
EXPOSE 8080

# No writable state on the filesystem: everything durable is in Postgres, and
# uploads go to object storage. The container can run with a read-only rootfs.
CMD ["node", "server.js"]
