# Next Steps — Voice-First Local Avatar AI

This is the punch list of what we still need to implement after getting:
- browser mic → FastAPI WS → **whisper.cpp STT** (host bridge)
- Ollama response with **multi-turn context** (via `/api/chat`)
- optional **TTS playback** (host bridge using macOS `say` or Piper)

## P0 — Make voice feel “realtime”
- **Streaming STT**
  - ✅ Emit frequent real `partial_transcript` via **small window batching** (when STT is configured)
- **VAD + endpointing**
  - ✅ Auto-send `end` via a simple **client-side silence timer** (push-to-talk still works)
  - ✅ Added **server-side** naive VAD/endpointing (RMS threshold) as a fallback
- **Barge-in**
  - When mic starts while TTS is playing:
    - ✅ stop playback immediately (UI)
    - ✅ send `cancel` to backend automatically on barge-in
    - ✅ cancel in-flight turn work (STT/LLM/TTS) server-side
- **Audio framing**
  - ✅ Moved to **binary WebSocket frames** (raw PCM16LE) with basic backpressure (drop when congested)
  - (legacy) base64 JSON frames still supported for compatibility
- **Resampling decision**
  - Standardize on **16kHz mono PCM16** for STT
  - ✅ Decision: **server-side** resample to 16kHz before STT (browser sends device-rate PCM16LE)

## P0 — TTS quality + latency
- ✅ **Piper option added** to the host TTS bridge (switch with `TTS_ENGINE=piper`)
- **Streaming TTS**
  - ✅ TTS consumes the **LLM stream**: we synthesize and play `tts_chunk` progressively while tokens arrive
  - ✅ `cancel` flushes queued audio and stops playback
- **Voice selection**
  - ✅ Optional `voice` parameter supported end-to-end (request → API → bridge)
  - ✅ Persist per-avatar voice config in DB + UI, and have `/voice` use the active avatar voice automatically
  - ⏳ Selectable voices:
    - Add an API endpoint to list available voices (e.g. Piper voices discovered from `piper-models/`)
    - UI: dropdown selector on `/avatar` (per-avatar) and/or quick switch on `/voice`
    - Persist selection in `avatars.voice_config` (already in place) and apply immediately on next turn

## P0 — Auth + user identity (signup/login/logout)
- **Users in Postgres**
  - ✅ Create `users` table (id, email, name, password_hash, created_at, last_login_at)
  - ⏳ Seed/dev convenience: optional “dev login” user creation via `make` target
- **Session management**
  - ✅ Create `sessions` table (id, user_id, token_hash, created_at, expires_at, revoked_at, user_agent/ip optional)
  - ✅ API auth: HTTP-only cookie session (opaque token stored hashed in DB)
- **Auth endpoints**
  - ✅ `POST /auth/signup`, `POST /auth/login`, `POST /auth/logout`, `GET /auth/me`
  - ✅ Protect memory endpoints with authenticated user (403 on mismatch)
- **UI flow**
  - ✅ Login/signup screens (modern “Lumina” UI)
  - ✅ Logout button + “current user” indicator
  - ✅ Memory UI uses authenticated user id (no default user id)
  - ✅ Removed default-ID plumbing:
    - Removed `DEFAULT_USER_ID`/`DEFAULT_AVATAR_ID` + `NEXT_PUBLIC_*` env vars
    - UI/WS now derive identity from `/auth/me` + `/avatars` (no hard-coded UUIDs)
  - ✅ Ensure backend tests run `make migrate` before pytest
  - ⏳ Initial assistant greeting after login (warmup):
    - Purpose: “warm” Piper/tts path to reduce first-response latency and improve flow
    - UI: show a short welcome message in `/voice` (and optionally play it via TTS)
    - Backend: optional `/voice/warmup` or WS `warmup` message to pre-initialize TTS bridge

## P1 — Conversation + memory integration
- **Persist conversations**
  - Store turns in Postgres (thread/session table)
  - ✅ Add `conversations` + `conversation_turns` tables
  - ✅ Wire voice WS to write each finalized turn (user transcript + assistant reply) to the DB (best-effort; never breaks voice loop)
  - ✅ Minimal API: list recent conversations + fetch a conversation (debug/inspect)
  - ⏳ Replay context into the voice session on reconnect (load recent turns into `state.messages` on WS connect / new turn)
  - ⏳ Daily objective + date-based recall:
    - Add a lightweight “daily objective” prompt injection (by date) and store it as a memory card + raw chunk
    - Ensure retrieval can filter/boost by date (e.g. “today”, “yesterday”, specific date)
    - UX: expose a “Today’s objective” field + quick recall by date in the Memory UI
- **Memory write policy**
  - ✅ Automatically ingest episodic memory from voice transcripts
  - (Decision) No sensitive-info filter required for local-only operation
- **“Inspect/Delete memory” UX**
  - ✅ Add a basic UI to browse and delete stored memories
  - ⏳ Remove manual avatar_id input (derive from `active_avatar_id` and/or make “scope” explicit)

## P1 — Persona / avatar system
- **Avatar profiles**
  - Create avatars (name, persona prompt, style rules, voice config)
  - Per-avatar memory scope (already designed)
- **User profile (name + preferences)**
  - Capture the user’s preferred name and make it available to prompts/tools so Lumina can address the user naturally
- **Prompting**
  - System prompt templates (persona + style + safety)
  - Tool routing via PydanticAI
  - ⏳ Domain expertise / knowledge:
    - Define what “domain pack” means (prompt-only, RAG-only, fine-tune/LoRA, or hybrid)
    - Implement a “domain pack” pipeline: curated docs → chunk → embed → pgvector → retrieval in prompts
    - Document retraining path (LoRA vs full fine-tune) and local infra expectations
- **“Lumina” assistant identity**
  - ✅ Add a default assistant persona called **Lumina** (personal assistant) via system prompt + UI copy
  - Later: fine-tune/LoRA the `llama3.2` base into a “Lumina” checkpoint once we migrate to **vLLM**

## P1 — Reliability + developer UX
- **Health checks**
  - API should report whether STT/TTS bridges are reachable and configured
  - ✅ Expand `/health` to include: DB ok, Ollama ok, STT ok (if configured), TTS ok (if configured), avatar image engine readiness
- **Optional internet search tool (opt-in)**
  - Add a PydanticAI tool that can perform web search when explicitly enabled (default remains offline-only)
  - UX: clear indicator when “internet mode” is on; log/cite sources in responses
- **Better errors**
  - Structured error codes (not string-prefixed messages)
  - Show actionable UI prompts (“Start STT bridge”, “Set STT_BASE_URL”, etc.)
  - ✅ Standardize WS `error` payloads: `{ code, message, details? }` (keep backwards-compatible `message`)
- **Performance instrumentation**
  - Log timing: capture duration → STT latency → LLM latency → TTS latency
  - ✅ Emit per-turn timing summary to logs (and optionally as a WS debug message behind a flag)
 - **Test coverage**
  - ⏳ Ensure full test coverage for FE + BE:
    - BE: add tests for conversations persistence paths + health checks + voice error codes
    - FE: add tests for auth gating + avatar voice selection + greeting flow + conversations UI (when added)
    - Add a coverage target (e.g. `make coverage`) and enforce in CI (or at least in precommit)

## P1 — Voice auth + per-user memory (critical follow-up)
- **Authenticate /ws/voice**
  - ✅ Read HTTP-only session cookie during WS upgrade and attach `user_id` to the session
  - ✅ Use authenticated `user_id` for voice memory auto-ingest (no `DEFAULT_USER_ID` writes)
  - ⏳ Decide barge-in + session expiry semantics (what happens if cookie expires mid-stream)
  - If cookie expires mid-stream: allow current turn to finish, but reject new turns (send `error` + require reconnect/login)

## P1 — Avatar v0 (“talking head”)
- **Avatar profiles**
  - ✅ Create `avatars` table (id, user_id, name, persona_prompt, image_url, voice_config, created_at, updated_at)
  - ✅ Add `users.active_avatar_id` (nullable) to pick the current avatar
- **Voice UI**
  - ✅ Show avatar image + name in `/voice`
  - ✅ Animate “talking” during playback using output level (no full lip-sync yet)
- **Image generation (local, optional)**
  - ✅ Add `/avatars/{id}/generate-image` and UI controls in `/avatar`
  - ✅ Support **Diffusers SDXL base + refiner** (quality-first; local files only)
  - ✅ Keep Automatic1111 as a fallback engine
  - Note: Docker on macOS can’t use Metal/MPS; run on CPU in-container or add a host bridge for MPS acceleration
 - **Per-avatar voice config (finish wiring)**
  - ✅ Persist per-avatar voice config in `avatars.voice_config`
  - ✅ UI on `/avatar` to set the active avatar’s voice + save
  - ✅ `/voice` automatically uses the active avatar voice config for TTS (no manual voice selection)

## P2 — Security + privacy hardening
- **No accidental network**
  - Ensure all services bind to localhost / LAN only (already mostly)
  - Disable any telemetry; document it
- **Data protection**
  - Optional encryption-at-rest for DB
  - “Forget me” / delete-all user data endpoint

## P2 — Upgrade paths
- **WebRTC transport**
  - For best echo handling, lower latency media transport
- **vLLM migration**
  - Abstract model provider and enable fine-tuned variants later
 - **Postgres extensions/plugins**
  - ⏳ Evaluate Postgres extensions that help local RAG + analytics (within privacy constraints):
    - `pg_stat_statements` for query insights (local-only)
    - `pg_trgm` for fuzzy keyword search on logs/memories
    - pgvector tuning (HNSW params, `vector_ip_ops`, maintenance)
    - Consider time-series friendly indexing/partitioning for conversations/turns

## Now / Next (re-prioritized)
- **P0 (next)**: Greeting warmup + selectable voices (high UX impact, low risk)
- **P1 (next)**: Daily objective + date-based recall and conversation replay on reconnect
- **P1 (after)**: Domain expertise via “domain packs” (RAG first; LoRA later)
- **P2 (later)**: Postgres extensions/plugins exploration + hardening test coverage enforcement/CI


