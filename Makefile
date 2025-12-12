.PHONY: help up down build logs ps restart clean db-shell api-shell ui-shell test test-backend test-frontend precommit-install precommit-run
.PHONY: migrate revision
.PHONY: stt-bridge

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
	@echo "  make db-shell  - psql shell into Postgres"
	@echo "  make api-shell - shell into API container"
	@echo "  make ui-shell  - shell into UI container"

up:
	docker compose up -d --build

down:
	docker compose down

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


