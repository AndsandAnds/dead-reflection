.PHONY: help up down build logs ps restart clean db-shell api-shell ui-shell test test-backend test-frontend precommit-install precommit-run
.PHONY: migrate revision
.PHONY: stt-bridge tts-bridge
.PHONY: bridges-up bridges-down bridges-status stt-bridge-bg tts-bridge-bg
.PHONY: db-bench db-bench-worker db-bench-io-uring
.PHONY: db-bench-vector-setup db-bench-vector db-bench-vector-worker db-bench-vector-io-uring
.PHONY: test-backend-fast test-backend-verbose test-backend-specific test-frontend-verbose
.PHONY: bridges-preflight check-tts-piper

RUN_DIR := run
STT_PID := $(RUN_DIR)/stt-bridge.pid
TTS_PID := $(RUN_DIR)/tts-bridge.pid
STT_LOG := $(RUN_DIR)/stt-bridge.log
TTS_LOG := $(RUN_DIR)/tts-bridge.log

help:
	@echo "Targets:"
	@echo "  make up        - build & start the full stack"
	@echo "  make down      - stop the stack"
	@echo "  make build     - build images"
	@echo "  make logs      - tail logs"
	@echo "  make ps        - show containers"
	@echo "  make restart   - restart stack"
	@echo "  make clean     - stop stack and remove volumes"
	@echo "  make test      - run backend + frontend tests"
	@echo "  make test-backend  - run pytest (streams output via docker compose exec when possible)"
	@echo "  make test-backend-fast     - run pytest with minimal output"
	@echo "  make test-backend-verbose  - run pytest with max verbosity"
	@echo "  make test-backend-specific test_name=... - run a specific backend test (pytest -k)"
	@echo "  make test-frontend - run vitest in ui container"
	@echo "  make test-frontend-verbose - run vitest with reporter=verbose"
	@echo "  make precommit-install - install git pre-commit hooks (run locally)"
	@echo "  make precommit-run     - run all hooks on all files (run locally)"
	@echo "  make migrate           - apply Alembic migrations (docker compose api)"
	@echo "  make revision name=... - create new Alembic revision (docker compose api)"
	@echo "  make stt-bridge        - run host STT bridge (whisper.cpp) on :9001"
	@echo "  make tts-bridge        - run host TTS bridge (macOS say) on :9002"
	@echo "  make bridges-up        - start host STT+TTS bridges in background (PID files in ./run)"
	@echo "  make bridges-down      - stop host STT+TTS bridges"
	@echo "  make bridges-status    - show whether host bridges are running"
	@echo "  make db-bench          - run a quick pgbench baseline against the db container"
	@echo "  make db-bench-worker   - run pgbench with io_method=worker"
	@echo "  make db-bench-io-uring - run pgbench with io_method=io_uring (if supported)"
	@echo "  make db-shell  - psql shell into Postgres"
	@echo "  make api-shell - shell into API container"
	@echo "  make ui-shell  - shell into UI container"

up:
	docker compose up -d --build
	@$(MAKE) bridges-up

down:
	docker compose down

bridges-up: bridges-preflight stt-bridge-bg tts-bridge-bg
	@echo "Host bridges: up"

bridges-preflight:
	@# Validate host dependencies for bridges. Reads from .env if present.
	@set -e; \
	if [ -f .env ]; then set -a; . ./.env; set +a; fi; \
	if [ "$${TTS_ENGINE:-say}" = "piper" ]; then \
	  $(MAKE) check-tts-piper; \
	fi

check-tts-piper:
	@set -e; \
	if [ -f .env ]; then set -a; . ./.env; set +a; fi; \
	bin="$${PIPER_BIN:-piper}"; \
	model="$${PIPER_MODEL:-}"; \
	if ! command -v "$$bin" >/dev/null 2>&1; then \
	  echo "ERROR: TTS_ENGINE=piper but '$$bin' is not installed / not on PATH."; \
	  echo "Install Piper CLI (recommended):"; \
	  echo "  brew install pipx"; \
	  echo "  pipx install piper-tts"; \
	  exit 2; \
	fi; \
	if [ -z "$$model" ] || [ ! -f "$$model" ]; then \
	  echo "ERROR: TTS_ENGINE=piper but PIPER_MODEL is not set or does not exist: '$$model'"; \
	  echo "Set it to a local .onnx voice model path (and keep the matching .onnx.json nearby)."; \
	  exit 2; \
	fi

bridges-status:
	@mkdir -p "$(RUN_DIR)"
	@set -e; \
	for n in stt tts; do \
	  pidfile="$(RUN_DIR)/$$n-bridge.pid"; \
	  if [ -f "$$pidfile" ] && kill -0 "$$(cat "$$pidfile")" 2>/dev/null; then \
	    echo "$$n: running (pid $$(cat "$$pidfile"))"; \
	  else \
	    echo "$$n: not running"; \
	  fi; \
	done

bridges-down:
	@set -e; \
	for n in stt tts; do \
	  pidfile="$(RUN_DIR)/$$n-bridge.pid"; \
	  if [ -f "$$pidfile" ]; then \
	    pid="$$(cat "$$pidfile")"; \
	    if kill -0 "$$pid" 2>/dev/null; then \
	      echo "Stopping $$n bridge (pid $$pid)"; \
	      kill "$$pid" 2>/dev/null || true; \
	    fi; \
	    rm -f "$$pidfile"; \
	  fi; \
	done

build:
	docker compose build

logs:
	docker compose logs -f --tail=200

ps:
	docker compose ps

restart:
	docker compose restart

clean:
	docker compose down -v

db-shell:
	docker compose exec db psql -U $${POSTGRES_USER:-reflections} -d $${POSTGRES_DB:-reflections}

api-shell:
	docker compose exec api bash

ui-shell:
	docker compose exec ui sh

test: test-backend test-frontend

test-backend:
	@# Prefer exec so output streams and we avoid recreating one-off containers.
	@# Fallback to run --rm when api is not running.
	@set -e; \
	if docker compose ps -q api | grep -q .; then \
	  docker compose exec -T api poetry run pytest -vv -s; \
	else \
	  docker compose run --rm api poetry run pytest -vv -s; \
	fi

test-frontend:
	@set -e; \
	if docker compose ps -q ui | grep -q .; then \
	  docker compose exec -T ui npm test; \
	else \
	  docker compose run --rm ui npm test; \
	fi

test-backend-fast:
	@set -e; \
	if docker compose ps -q api | grep -q .; then \
	  docker compose exec -T api poetry run pytest -q; \
	else \
	  docker compose run --rm api poetry run pytest -q; \
	fi

test-backend-verbose:
	@set -e; \
	if docker compose ps -q api | grep -q .; then \
	  docker compose exec -T api poetry run pytest -vvv -s --tb=long; \
	else \
	  docker compose run --rm api poetry run pytest -vvv -s --tb=long; \
	fi

test-backend-specific:
	@set -e; \
	if [ -z "$(test_name)" ]; then \
	  echo "Usage: make test-backend-specific test_name=<pattern>"; \
	  exit 2; \
	fi; \
	if docker compose ps -q api | grep -q .; then \
	  docker compose exec -T api poetry run pytest -k "$(test_name)" -vv -s -ra; \
	else \
	  docker compose run --rm api poetry run pytest -k "$(test_name)" -vv -s -ra; \
	fi

test-frontend-verbose:
	@set -e; \
	if docker compose ps -q ui | grep -q .; then \
	  docker compose exec -T ui npm test -- --reporter=verbose; \
	else \
	  docker compose run --rm ui npm test -- --reporter=verbose; \
	fi

# NOTE: These run on your host (not in Docker), because git hooks run locally.
precommit-install:
	poetry run pre-commit install

precommit-run:
	poetry run pre-commit run -a

# Alembic (runs in the API container so it uses the same environment as the app)
migrate:
	docker compose run --rm api poetry run alembic upgrade head

revision:
	docker compose run --rm api poetry run alembic revision -m "$(name)"

stt-bridge:
	poetry run python -m uvicorn reflections.stt_bridge.main:app --host 0.0.0.0 --port 9001

tts-bridge:
	poetry run python -m uvicorn reflections.tts_bridge.main:app --host 0.0.0.0 --port 9002

stt-bridge-bg:
	@mkdir -p "$(RUN_DIR)"
	@set -e; \
	if [ -f "$(STT_PID)" ] && kill -0 "$$(cat "$(STT_PID)")" 2>/dev/null; then \
	  echo "stt-bridge already running (pid $$(cat "$(STT_PID)"))"; \
	else \
	  rm -f "$(STT_PID)"; \
	  echo "Starting stt-bridge in background (logs: $(STT_LOG))"; \
	  nohup $(MAKE) stt-bridge >"$(STT_LOG)" 2>&1 & echo $$! >"$(STT_PID)"; \
	fi

tts-bridge-bg:
	@mkdir -p "$(RUN_DIR)"
	@set -e; \
	if [ -f "$(TTS_PID)" ] && kill -0 "$$(cat "$(TTS_PID)")" 2>/dev/null; then \
	  echo "tts-bridge already running (pid $$(cat "$(TTS_PID)"))"; \
	else \
	  rm -f "$(TTS_PID)"; \
	  echo "Starting tts-bridge in background (logs: $(TTS_LOG))"; \
	  nohup $(MAKE) tts-bridge >"$(TTS_LOG)" 2>&1 & echo $$! >"$(TTS_PID)"; \
	fi

# ---------------------------------------------------------------------------
# Postgres perf benchmarking (only change io_method if this shows real gains).
#
# Notes:
# - Requires the db container to be running.
# - Uses pgbench bundled in the pgvector/pgvector image.
# - io_uring support depends on the Linux kernel inside Docker; it may fail.
# ---------------------------------------------------------------------------

db-bench:
	@echo "Running pgbench baseline (current settings)..."
	@docker compose exec -T db sh -lc 'psql -U "$$POSTGRES_USER" -d "$$POSTGRES_DB" -Atc "SHOW io_method; SHOW effective_io_concurrency;"'
	@docker compose exec -T db sh -lc 'pgbench -i -s 10 -U "$$POSTGRES_USER" "$$POSTGRES_DB" >/dev/null'
	@docker compose exec -T db sh -lc 'pgbench -T 30 -c 8 -j 4 -U "$$POSTGRES_USER" "$$POSTGRES_DB"'

db-bench-worker:
	@echo "Benchmarking io_method=worker..."
	@POSTGRES_IO_METHOD=worker docker compose up -d db
	@sleep 2
	@$(MAKE) db-bench

db-bench-io-uring:
	@echo "Benchmarking io_method=io_uring (may fail if unsupported)..."
	@POSTGRES_IO_METHOD=io_uring docker compose up -d db || true
	@sleep 2
	@$(MAKE) db-bench || true

# ---------------------------------------------------------------------------
# App-like benchmark: pgvector memory retrieval (read-heavy).
#
# This simulates our "retrieve top-k memories by user+avatar" query pattern.
# ---------------------------------------------------------------------------

VEC_ROWS ?= 200000
VEC_CLIENTS ?= 8
VEC_THREADS ?= 4
VEC_SECONDS ?= 30

db-bench-vector-setup:
	@echo "Setting up bench_vectors with $(VEC_ROWS) rows..."
	@docker compose exec -T db sh -lc 'psql -U "$$POSTGRES_USER" -d "$$POSTGRES_DB" -v vec_rows=$(VEC_ROWS) -f /workspace/bench/sql/vector_setup.sql >/dev/null'
	@echo "bench_vectors ready."

db-bench-vector:
	@echo "Running pgvector read benchmark (current settings)..."
	@docker compose exec -T db sh -lc 'psql -U "$$POSTGRES_USER" -d "$$POSTGRES_DB" -Atc "SHOW io_method; SHOW effective_io_concurrency;"'
	@docker compose exec -T db sh -lc 'pgbench -n -T $(VEC_SECONDS) -c $(VEC_CLIENTS) -j $(VEC_THREADS) -U "$$POSTGRES_USER" -D max_id=$(VEC_ROWS) -f /workspace/bench/pgbench/vector_read.sql "$$POSTGRES_DB"'

db-bench-vector-worker:
	@echo "Benchmarking vector read with io_method=worker..."
	@POSTGRES_IO_METHOD=worker docker compose up -d db
	@sleep 2
	@$(MAKE) db-bench-vector

db-bench-vector-io-uring:
	@echo "Benchmarking vector read with io_method=io_uring (may fail if unsupported)..."
	@POSTGRES_IO_METHOD=io_uring docker compose up -d db || true
	@sleep 2
	@$(MAKE) db-bench-vector || true


