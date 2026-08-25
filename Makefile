# Capstone-IDA — developer entrypoints.
#
#   make install    install every package editable, plus dev tooling
#   make test       everything that must be green before you push (no Docker)
#   make dev        bring the local stack up with docker compose
#   make tracer     the end-to-end tracer bullet against the real stack
#   make lint       ruff + frontend typecheck/lint
#
# `make test` is the commit gate and needs nothing but Python 3.12 + Node 22.
# `make tracer` additionally needs Docker.

SHELL := /bin/bash
.SHELLFLAGS := -eu -o pipefail -c
.DEFAULT_GOAL := help

PYTHON ?= python3
export IDA_REPO_ROOT := $(CURDIR)

# Everything installs into a project-local virtualenv.
#
# Ubuntu 22.04+ and Debian 12+ -- the default campus Linux -- mark the system
# interpreter as externally managed (PEP 668), so `pip install` into it fails
# outright with `externally-managed-environment`. A venv is the one approach
# that works on every supported platform without special flags, so it is the
# documented path rather than an option.
#
# Set VENV= to install into whatever interpreter is already active instead
# (a conda env, a devcontainer, CI):  make install VENV=
VENV    ?= .venv
VENV_PY  = $(if $(VENV),$(VENV)/bin/python,$(PYTHON))
PIP      = $(VENV_PY) -m pip
RUN      = $(VENV_PY)

# Absolute form, for recipes that `cd` into a package first. Must NOT be
# built by prefixing $(CURDIR) unconditionally: with VENV= the interpreter is
# the bare name `python3`, which has to stay bare so PATH resolves it.
PY_ABS   = $(if $(VENV),$(CURDIR)/$(VENV)/bin/python,$(PYTHON))

PY_PACKAGES := packages/core packages/harness
PY_SERVICES := services/api services/runner services/mock-model
PY_ALL      := $(PY_PACKAGES) $(PY_SERVICES)

COMPOSE ?= docker compose
# `--verify` makes git fail cleanly instead of printing the literal "HEAD"
# in a repository with no commits. An empty GIT_SHA is honest; "HEAD" is not.
GIT_SHA := $(shell git rev-parse --verify HEAD 2>/dev/null)

# Host ports published by docker-compose. Override any of these if a default is
# already taken on your machine (9000 clashes often):
#   MINIO_PORT=9100 MINIO_CONSOLE_PORT=9101 make dev
# Nothing inside the stack uses them -- services talk over the compose network.
export API_PORT           ?= 8000
export FRONTEND_PORT      ?= 3000
export MOCK_MODEL_PORT    ?= 8100
export POSTGRES_PORT      ?= 5432
export REDIS_PORT         ?= 6379
export MINIO_PORT         ?= 9000
export MINIO_CONSOLE_PORT ?= 9001

# ---------------------------------------------------------------- help ----

.PHONY: help
help: ## Show this help
	@echo "Capstone-IDA"; echo
	@grep -hE '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) \
	  | awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-16s\033[0m %s\n", $$1, $$2}'

# ------------------------------------------------------------- install ----

.PHONY: install
install: install-python install-frontend ## Install all dependencies

.PHONY: venv
venv: ## Create the project virtualenv (.venv) if it is missing or incomplete
	@# The guard tests that the venv WORKS, not that a file exists.
	@#
	@# A failed `python3 -m venv` (missing ensurepip, out of disk, interrupted)
	@# still leaves bin/python behind. The previous guard, `[ ! -x bin/python ]`,
	@# therefore called that half-created state "done", and every retry died with
	@# "No module named pip" -- with nothing pointing at the actual cause.
	@#
	@# Two conditions, because either alone is unsound: bin/pip must exist (an
	@# interpreter that can `import pip` may only be seeing system site-packages,
	@# e.g. through --system-site-packages), and pip must actually RUN through
	@# this interpreter (bin/pip can exist and be broken).
	@if [ -n "$(VENV)" ] && { [ ! -x "$(VENV)/bin/pip" ] \
	                          || ! $(VENV_PY) -m pip --version >/dev/null 2>&1; }; then \
	  if [ -e "$(VENV)" ]; then echo "$(VENV)/ is incomplete; recreating ..."; \
	  else echo "creating $(VENV)/ ..."; fi; \
	  $(PYTHON) -m venv --clear $(VENV) || { \
	    echo ""; \
	    echo "  python venv is unavailable. On Debian/Ubuntu install it with:"; \
	    echo "      sudo apt install python3-venv"; \
	    echo "  or install into the current interpreter instead:"; \
	    echo "      make install VENV="; \
	    echo ""; \
	    echo "  ($(VENV)/ may be left partially created; it is safe to delete,"; \
	    echo "   and it is recreated once python3-venv is present.)"; \
	    exit 1; }; \
	  $(VENV_PY) -m pip install -q --upgrade pip; \
	fi

.PHONY: install-python
install-python: venv ## Install Python packages editable + dev tooling
	$(PIP) install -r requirements-dev.txt
	$(PIP) install --no-deps $(foreach p,$(PY_ALL),-e $(p))
	@echo
	@echo "  Python deps installed into $(if $(VENV),$(VENV)/,the active interpreter)"
	@echo "  Activate with: source $(VENV)/bin/activate   (or just use make)"

.PHONY: install-frontend
install-frontend: ## Install frontend dependencies
	cd frontend && npm ci || (cd frontend && npm install)

# ---------------------------------------------------------------- test ----

.PHONY: test
test: test-python test-e2e test-frontend ## Everything that gates a commit

.PHONY: test-python
test-python: ## pytest across packages/ and services/ -- ONE root run, exactly as CI does
	@# CI runs a single root `pytest`. Running it the same way locally is the
	@# whole point: a suite that only passes when invoked per-directory is a
	@# suite that fails in CI. `--import-mode=importlib` (pyproject) is what
	@# keeps five sibling tests/ packages from colliding.
	$(PY_ABS) -m pytest

.PHONY: test-e2e
test-e2e: ## The tracer bullet, in process (no Docker needed)
	cd e2e && $(PY_ABS) -m pytest .

.PHONY: test-frontend
test-frontend: ## Frontend typecheck + lint + build
	cd frontend && npm run test

.PHONY: coverage
coverage: ## Measure line coverage across the Python suites
	@$(RUN) -m coverage erase
	@for dir in $(PY_ALL); do \
	  echo "=== $$dir"; \
	  ( cd $$dir && $(PY_ABS) -m coverage run --parallel-mode \
	      --rcfile=$(CURDIR)/pyproject.toml -m pytest tests -q ) || exit 1; \
	done
	@$(RUN) -m coverage combine $(foreach p,$(PY_ALL),$(p)) >/dev/null
	@$(RUN) -m coverage report

# ---------------------------------------------------------------- lint ----

.PHONY: lint
lint: lint-python lint-tasks lint-frontend ## Lint everything

.PHONY: lint-python
lint-python: ## ruff check + format check
	$(RUN) -m ruff check .
	$(RUN) -m ruff format --check .

.PHONY: format
format: ## Apply ruff's autofixes and formatter
	$(RUN) -m ruff check . --fix
	$(RUN) -m ruff format .

.PHONY: lint-tasks
lint-tasks: ## Validate tasks/**.yaml + models.yaml against the JSON Schemas
	$(RUN) tools/validate_tasks.py --root .

.PHONY: lint-frontend
lint-frontend: ## Frontend typecheck + eslint
	cd frontend && npm run typecheck && npm run lint

# ----------------------------------------------------------------- dev ----

.PHONY: dev
dev: ## Bring the whole local stack up (postgres, redis, minio, mock-model, api, runner, frontend)
	GIT_SHA=$(GIT_SHA) $(COMPOSE) up -d --build --wait
	@echo
	@echo "  API       http://localhost:$(API_PORT)  (docs at /docs)"
	@echo "  Frontend  http://localhost:$(FRONTEND_PORT)"
	@echo "  MinIO     http://localhost:$(MINIO_CONSOLE_PORT)  (minioadmin / minioadmin)"
	@echo "  Mock LLM  http://localhost:$(MOCK_MODEL_PORT)/health"
	@echo
	@echo "  Next: make tracer"

.PHONY: down
down: ## Stop the stack (keeps volumes)
	$(COMPOSE) down

.PHONY: clean
clean: ## Stop the stack and delete its volumes
	$(COMPOSE) down -v

.PHONY: logs
logs: ## Tail logs from every service
	$(COMPOSE) logs -f

.PHONY: ps
ps: ## Show stack status
	$(COMPOSE) ps

# -------------------------------------------------------------- tracer ----

.PHONY: tracer
tracer: dev ## Bring the stack up, then run the tracer bullet against it
	@echo "=== tracer bullet against the live stack"
	cd e2e && IDA_E2E_API_BASE=http://localhost:$(API_PORT) \
	          IDA_E2E_FRONTEND_BASE=http://localhost:$(FRONTEND_PORT) \
	          $(PY_ABS) -m pytest test_tracer_compose.py -v

.PHONY: tracer-manual
tracer-manual: ## Fire one run by hand and print the result (needs `make dev`)
	@curl -sS -X POST localhost:$(API_PORT)/runs \
	  -H 'content-type: application/json' \
	  -d '{"task_ids":["demo/arithmetic-quiz-check"],"model_keys":["mock"],"label":"manual"}' \
	  | $(RUN) -c 'import json,sys; print(json.load(sys.stdin)["runs"][0]["id"])'
	@echo "Watch it at http://localhost:$(FRONTEND_PORT)"

# ----------------------------------------------------------- migrations ----

.PHONY: migrate
migrate: ## Apply Alembic migrations (needs DATABASE_URL)
	@# Repo ROOT, not packages/core: alembic.ini, the CI `migrations` job,
	@# Dockerfile.python and the api's migrate initContainer all point here.
	$(PY_ABS) -m alembic upgrade head

.PHONY: migration
migration: ## Autogenerate a migration: make migration m="add foo"
	@test -n "$(m)" || (echo 'usage: make migration m="describe the change"' && exit 1)
	$(PY_ABS) -m alembic revision --autogenerate -m "$(m)"

# ------------------------------------------------------------- k8s ----

.PHONY: k8s-render
k8s-render: ## Render every overlay and assert the deploy invariants (needs kubectl)
	@# `.devops/chart/` IS the deploy contract -- infra/k8s/ is a scratch
	@# directory that nothing reads (see infra/k8s/README.md). The render test
	@# checks all four overlays plus the pod-budget/TLS/safety-switch invariants,
	@# which a bare `kubectl kustomize` does not.
	bash .devops/ci/chart-render.test.sh

.PHONY: ci
ci: ## Everything CI gates on, locally: the six PR gates minus the cluster ones
	$(MAKE) lint
	$(RUN) -m pytest
	cd frontend && npm run lint && npm run typecheck && npm run build
	$(MAKE) k8s-render
