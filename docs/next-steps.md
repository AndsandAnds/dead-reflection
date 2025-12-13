# Next Steps — Voice-First Local Avatar AI

This is the punch list of what we still need to implement after getting:
- browser mic → FastAPI WS → **whisper.cpp STT** (host bridge)
- Ollama response with **multi-turn context** (via `/api/chat`)
- optional **TTS playback** (host bridge using macOS `say`)

## P0 — Make voice feel “realtime”
- **Streaming STT**
  - Emit real `partial_transcript` from STT (not “listening…”)
  - Decide whether to do: streaming Whisper (incremental decoding) vs small window batching
- **VAD + endpointing**
  - Add VAD (silero-vad or webrtcvad) server-side or client-side
  - Auto-send `end` when silence threshold triggers (push-to-talk optional fallback)
- **Barge-in**
  - When mic starts while TTS is playing:
    - stop playback immediately (UI already does)
    - send `cancel` to backend
    - cancel any in-flight LLM/TTS work
- **Audio framing**
  - ✅ Moved to **binary WebSocket frames** (raw PCM16LE) with basic backpressure (drop when congested)
  - (legacy) base64 JSON frames still supported for compatibility
- **Resampling decision**
  - Standardize on **16kHz mono PCM16** for STT
  - ✅ Decision: **server-side** resample to 16kHz before STT (browser sends device-rate PCM16LE)

## P0 — TTS quality + latency
- **Replace macOS `say`** with a low-latency local model TTS (Piper first)
- **Streaming TTS**
  - Change `tts_audio` from a full WAV to chunked audio messages
  - Add `tts_cancel` semantics and flushing
- **Voice selection**
  - Voice profiles per avatar
  - Store voice config in DB (not env vars)

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
- **Prompting**
  - System prompt templates (persona + style + safety)
  - Tool routing via PydanticAI

## P1 — Reliability + developer UX
- **Health checks**
  - API should report whether STT/TTS bridges are reachable and configured
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


