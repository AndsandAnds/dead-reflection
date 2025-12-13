.PHONY: help up down build logs ps restart clean db-shell api-shell ui-shell test test-backend test-frontend precommit-install precommit-run
.PHONY: migrate revision
.PHONY: stt-bridge tts-bridge
.PHONY: bridges-up bridges-down bridges-status stt-bridge-bg tts-bridge-bg

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
	@echo "  make test-backend  - run pytest in api container"
	@echo "  make test-frontend - run vitest in ui container"
	@echo "  make precommit-install - install git pre-commit hooks (run locally)"
	@echo "  make precommit-run     - run all hooks on all files (run locally)"
	@echo "  make migrate           - apply Alembic migrations (docker compose api)"
	@echo "  make revision name=... - create new Alembic revision (docker compose api)"
	@echo "  make stt-bridge        - run host STT bridge (whisper.cpp) on :9001"
	@echo "  make tts-bridge        - run host TTS bridge (macOS say) on :9002"
	@echo "  make bridges-up        - start host STT+TTS bridges in background (PID files in ./run)"
	@echo "  make bridges-down      - stop host STT+TTS bridges"
	@echo "  make bridges-status    - show whether host bridges are running"
	@echo "  make db-shell  - psql shell into Postgres"
	@echo "  make api-shell - shell into API container"
	@echo "  make ui-shell  - shell into UI container"

up:
	docker compose up -d --build
	@$(MAKE) bridges-up

down:
	docker compose down

bridges-up: stt-bridge-bg tts-bridge-bg
	@echo "Host bridges: up"

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
	docker compose run --rm api poetry run pytest

test-frontend:
	docker compose run --rm ui npm test

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


