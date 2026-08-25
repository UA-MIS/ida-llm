# syntax=docker/dockerfile:1
# ida-llm-frontend — Next.js 15 standalone, multi-stage.
#
# ⚠ CONTEXT IS THE REPO ROOT (`.`), not frontend/. See .devops/components.yaml:
# every component builds from the root so one .dockerignore governs them all and
# a future shared package is reachable. Paths below are therefore repo-relative.
#
# ⚠ NODE 24.16, PINNED, NOT `24` OR `latest`. Node 24.17 shipped a keepAlive
# regression that broke in-cluster loopback HTTP on this platform (it cost a day
# on a previous tenant). Digest-free but minor-pinned is the deliberate middle
# ground: reproducible enough to avoid that class of surprise, cheap enough to
# patch. Pulled through the platform's Harbor pull-through cache so Docker Hub
# rate limits and the runners' :443-only egress stay out of the build path.
ARG NODE_IMAGE=harbor.capstone.uamishub.com/dockerhub-proxy/library/node:24.16-trixie-slim

# ---- deps: install once, cached on the lockfile alone ----------------------
FROM ${NODE_IMAGE} AS deps
WORKDIR /app
# Copy ONLY the manifests first. This layer is invalidated by a dependency
# change, not by every source edit — the single biggest lever on build time.
COPY frontend/package.json frontend/package-lock.json* ./
RUN npm ci --no-audit --no-fund

# ---- build ----------------------------------------------------------------
FROM ${NODE_IMAGE} AS build
WORKDIR /app
ENV NEXT_TELEMETRY_DISABLED=1
COPY --from=deps /app/node_modules ./node_modules
COPY frontend/ ./
RUN npm run build

# ---- runtime: no npm, no sources, no node_modules --------------------------
# `.next/standalone` already contains the traced subset of node_modules the
# server actually needs, which is why the final image carries neither the build
# toolchain nor the full dependency tree.
FROM ${NODE_IMAGE} AS runtime
WORKDIR /app
ENV NODE_ENV=production \
    NEXT_TELEMETRY_DISABLED=1 \
    PORT=3000 \
    HOSTNAME=0.0.0.0

# 65532 is the same non-root UID the chart's securityContext pins
# (runAsUser: 65532). The two MUST agree: a mismatch means files copied here as
# root are unreadable by the process that actually runs.
RUN groupadd --gid 65532 nonroot && useradd --uid 65532 --gid 65532 --no-create-home nonroot

COPY --from=build --chown=65532:65532 /app/.next/standalone ./
COPY --from=build --chown=65532:65532 /app/.next/static ./.next/static
COPY --from=build --chown=65532:65532 /app/public ./public

USER 65532:65532
EXPOSE 3000
CMD ["node", "server.js"]
