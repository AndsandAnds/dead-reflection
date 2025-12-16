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
  - ⏳ Persist per-avatar voice config in DB (move into the avatar/profile system)

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
  - ⏳ Remove remaining default-ID plumbing:
    - `DEFAULT_USER_ID`/`NEXT_PUBLIC_DEFAULT_USER_ID`
    - `DEFAULT_AVATAR_ID`/`NEXT_PUBLIC_DEFAULT_AVATAR_ID` (once avatars are real)
    - Remove these env vars from `docker-compose.yml` + `env.example` and delete the corresponding settings fields
    - Ensure all UI/WS flows derive `user_id` and `active_avatar_id` from `/auth/me` + `/avatars` (no hard-coded UUIDs)
  - ✅ Ensure backend tests run `make migrate` before pytest

## P1 — Conversation + memory integration
- **Persist conversations**
  - Store turns in Postgres (thread/session table)
  - Replay context into the voice session on reconnect
  - Add `conversations` + `conversation_turns` tables (user_id, avatar_id, created_at, role, text, timing metadata)
  - Wire voice WS to write each finalized turn (user transcript + assistant reply) to the DB
  - Add minimal API to list recent conversations + fetch a conversation (for debug/inspect UX)
- **Memory write policy**
  - ✅ Automatically ingest episodic memory from voice transcripts
  - (Decision) No sensitive-info filter required for local-only operation
- **“Inspect/Delete memory” UX**
  - ✅ Add a basic UI to browse and delete stored memories
  - ⏳ Remove manual avatar_id/user_id inputs once user/avatar profiles exist

## P1 — Persona / avatar system
- **Avatar profiles**
  - Create avatars (name, persona prompt, style rules, voice config)
  - Per-avatar memory scope (already designed)
- **User profile (name + preferences)**
  - Capture the user’s preferred name and make it available to prompts/tools so Lumina can address the user naturally
- **Prompting**
  - System prompt templates (persona + style + safety)
  - Tool routing via PydanticAI
- **“Lumina” assistant identity**
  - ✅ Add a default assistant persona called **Lumina** (personal assistant) via system prompt + UI copy
  - Later: fine-tune/LoRA the `llama3.2` base into a “Lumina” checkpoint once we migrate to **vLLM**

## P1 — Reliability + developer UX
- **Health checks**
  - API should report whether STT/TTS bridges are reachable and configured
  - Expand `/health` to include: DB ok, Ollama ok, STT ok (if configured), TTS ok (if configured), avatar image engine readiness
- **Optional internet search tool (opt-in)**
  - Add a PydanticAI tool that can perform web search when explicitly enabled (default remains offline-only)
  - UX: clear indicator when “internet mode” is on; log/cite sources in responses
- **Better errors**
  - Structured error codes (not string-prefixed messages)
  - Show actionable UI prompts (“Start STT bridge”, “Set STT_BASE_URL”, etc.)
  - Standardize WS `error` payloads: `{ code, message, details? }` (keep backwards-compatible `message`)
- **Performance instrumentation**
  - Log timing: capture duration → STT latency → LLM latency → TTS latency
  - Emit per-turn timing summary to logs (and optionally as a WS debug message behind a flag)

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
  - Persist per-avatar voice config in `avatars.voice_config`
  - Add simple UI on `/avatar` to set the active avatar’s voice (string) + save
  - Have `/voice` automatically use the active avatar voice config for TTS (no manual voice selection)

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


