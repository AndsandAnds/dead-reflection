---
description: "Project specs + tech stack for Reflections (local avatar AI, voice-first, offline-first)"
alwaysApply: true
---

## Project: Reflections (Local Avatar AI)

### Product goals
- **Local-only**: no user data (audio/text/memories) leaves the machine.
- **Voice-first**: prioritize realtime conversational voice with **barge-in** and streaming.
- **Character / persona**: avatar personas + configurable “voice/style”.
- **Memory**: short-term context + long-term semantic memory (vector search), inspectable and deletable.

### Hard constraints
- **Apple Silicon (macOS)** target.
- **Privacy by default**:
  - bind services to `127.0.0.1` unless explicitly requested
  - no telemetry, no external API calls for inference/STT/TTS/embeddings
- **Low latency**: treat STT/TTS and turn-taking as the core loop.

## Chosen tech stack

### Runtime / infra
- **Docker Compose** for local orchestration (`docker-compose.yml`).
- **Makefile** as the primary interface for starting/stopping the stack.
- **Ollama**: **host-installed** (Metal acceleration on macOS). Containers call it via `http://host.docker.internal:11434`.
- **Planned migration**: keep LLM provider behind an adapter so we can move to **vLLM** later.

### Backend (Python)
- **FastAPI** for HTTP + WebSockets.
- **PydanticAI** for agent orchestration with typed tools + structured outputs.
- **Pydantic** for schemas.
- **Postgres + pgvector** for relational + vector in one DB (local-first simplicity).
- **SentenceTransformers** for embeddings (decoupled from LLM runtime).

### Backend architecture pattern (required)
- **`api.py`** layer:
  - FastAPI routing/HTTP concerns only (status codes, request/response models)
  - maps service/domain exceptions → HTTP errors
- **`schemas.py`**:
  - Pydantic request/response models + DTOs shared across layers
- **`exceptions.py`**:
  - feature-level custom exceptions and constants
- **`flows.py`** (optional):
  - only when an endpoint needs to orchestrate **multiple services**
- **`service.py`** layer:
  - main business logic + orchestration
  - owns error handling, DB commits/transactions, and custom exceptions
- **`repository.py`** layer:
  - DB calls (and/or external API calls) only
  - no error handling
  - returns results and flushes as needed; no commits

### Realtime voice
- **STT**: **whisper.cpp + Metal** (Apple Silicon optimized; host-installed preferred).
- **VAD**: `silero-vad` (or `webrtcvad`) for endpointing and barge-in.
- **TTS**: evaluate low-latency streaming-friendly engines first; ensure we support:
  - start audio quickly (chunked synthesis)
  - immediate cancel on barge-in

### Frontend
- **Next.js** (App Router) for UI.
- Browser-first voice UX:
  - mic capture (Web APIs)
  - stream audio frames over **WebSocket** initially
  - upgrade to **WebRTC** if needed for best latency/echo control

## Repository conventions

### Ports / URLs (defaults)
- UI: `http://localhost:3000`
- API: `http://localhost:8000`
- DB: `localhost:5432` (Postgres)
- Ollama (host): `http://localhost:11434`

### Primary dev commands
- Start stack: `make up`
- Stop stack: `make down`
- Tail logs: `make logs`
- DB shell: `make db-shell`

### Coding guidance (for agents)
- Prefer **small, composable modules** with clear boundaries:
  - UI: presentational components + minimal state
  - Backend: `api.py` → `service.py` → `repository.py`
  - ML/providers: adapter layer so we can swap Ollama→vLLM, TTS engines, etc.
- **Streaming-first**:
  - use WebSockets for audio/text streaming
  - design APIs to support cancellation and partial results
- **Avoid blocking the voice loop**:
  - memory writes, DB operations, and embeddings should not stall realtime interactions
  - do heavy work async/background where possible


