# Next Steps — Voice-First Local Avatar AI

This is the punch list of what we still need to implement after getting:
- browser mic → FastAPI WS → **whisper.cpp STT** (host bridge)
- Ollama response with **multi-turn context** (via `/api/chat`)
- optional **TTS playback** (host bridge using macOS `say`)

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

## P1 — Conversation + memory integration
- **Persist conversations**
  - Store turns in Postgres (thread/session table)
  - Replay context into the voice session on reconnect
- **Memory write policy**
  - Automatically ingest episodic memory from voice transcripts
  - Add guardrails for sensitive info (do-not-store filter)
- **“Inspect/Delete memory” UX**
  - Add a basic UI to browse and delete stored memories

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
  - Add a default assistant persona called **Lumina** (personal assistant) via system prompt + UI copy
  - Later: fine-tune/LoRA the `llama3.2` base into a “Lumina” checkpoint once we migrate to **vLLM**

## P1 — Reliability + developer UX
- **Health checks**
  - API should report whether STT/TTS bridges are reachable and configured
- **Optional internet search tool (opt-in)**
  - Add a PydanticAI tool that can perform web search when explicitly enabled (default remains offline-only)
  - UX: clear indicator when “internet mode” is on; log/cite sources in responses
- **Better errors**
  - Structured error codes (not string-prefixed messages)
  - Show actionable UI prompts (“Start STT bridge”, “Set STT_BASE_URL”, etc.)
- **Performance instrumentation**
  - Log timing: capture duration → STT latency → LLM latency → TTS latency

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


