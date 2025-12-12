# Reflections — Local Avatar AI (Voice-First, Offline-First)

Runs a character.ai-style “avatar AI” locally on Apple Silicon. **No data leaves your machine** by default.

## Stack (current)
- **Frontend**: Next.js (App Router)
- **Backend**: FastAPI + PydanticAI (agent orchestration)
- **DB**: Postgres + pgvector (Docker)
- **Embeddings**: SentenceTransformers
- **LLM runtime**: Ollama (**host-installed on macOS for Metal**; containers call `host.docker.internal`)
- **STT**: whisper.cpp + Metal (host-installed; planned integration)
- **Tests**: pytest (backend), Vitest + Testing Library (frontend)
- **Code cleanliness**: pre-commit (Ruff + Prettier + basic hooks)

Architecture notes live in `docs/local-avatar-ai-stack.md`.

## Prerequisites
- Docker Desktop (Apple Silicon)
- Poetry 2.x
- Ollama installed on the host (macOS)
  - Ensure it’s reachable at `http://localhost:11434`

Optional (voice):
- `whisper.cpp` built with Metal support (we’ll wire it in soon)

## Quickstart
1) (Optional) create a local env file:

```bash
cp env.example .env
```

`.env` is **gitignored** (do not commit secrets).

2) Start the stack:

```bash
make up
```

3) Open:
- UI: `http://localhost:3000`
- API health: `http://localhost:8000/health`

Stop it:

```bash
make down
```

## Tests
Run everything:

```bash
make test
```

Backend only:

```bash
make test-backend
```

Frontend only:

```bash
make test-frontend
```

## Pre-commit hooks
Install hooks (runs on your host machine):

```bash
poetry install
make precommit-install
```

Run on all files:

```bash
make precommit-run
```

## Notes (Apple Silicon)
- Docker on macOS **does not provide Metal acceleration** inside containers.
- For best performance we run **Ollama on the host** and point containers at:
  - `OLLAMA_BASE_URL=http://host.docker.internal:11434`

