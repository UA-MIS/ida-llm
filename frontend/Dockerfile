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
ARG NODE_IMAGE=harbor.capstone.uamishub.com/base-images/library/node:24.16-trixie-slim

# ---- deps: install once, cached on the lockfile alone ----------------------
FROM ${NODE_IMAGE} AS deps
WORKDIR /app
# Copy ONLY the manifests first. This layer is invalidated by a dependency
# change, not by every source edit — the single biggest lever on build time.
COPY frontend/package.json frontend/package-lock.json* ./
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

# ---- build ----------------------------------------------------------------
FROM ${NODE_IMAGE} AS build
WORKDIR /app

# RELEASE IDENTITY -- the OTHER half of the header's version badge, and it is a
# BOTH-HALVES wiring exactly like Dockerfile.python's IDA_VERSION.
#
# ⚠ NEXT_PUBLIC_* IS INLINED AT BUILD TIME, WHICH IS WHY IT HAS TO BE HERE AND
# NOT IN THE RUNTIME STAGE. Setting it below `npm run build` would set an
# environment variable nothing ever reads: the substitution has already happened.
# One image is built and promoted byte-identically through dev, staging and prod,
# so a per-environment value is structurally impossible here anyway -- and it is
# not wanted: the badge names the BUILD, and the build is the thing that is the
# same in all three.
#
# The value is the resolved image TAG, passed by build-and-push.yaml as
# `--build-arg=IDA_VERSION` to every matrix leg. The overlays pin `newTag: <TAG>`,
# so "what does the header say" and "what does the overlay say" name the same
# string.
#
# ⚠ DEFAULTS TO EMPTY, ON PURPOSE, and src/lib/version.ts is where that is made
# safe. A release-shaped literal here would be the `0.1.0` regression the
# platform's build-provenance suite pins by value: an image confidently naming a
# release it is not. Empty reaches version.ts, which renders the package version
# with a `-dev` suffix and says in the tooltip that the build-arg was missing --
# non-empty, obviously not a release, and visibly broken rather than silently so.
ARG IDA_VERSION=""

ENV NEXT_TELEMETRY_DISABLED=1 \
    NEXT_PUBLIC_APP_VERSION=${IDA_VERSION}
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
