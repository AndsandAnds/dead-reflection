---
description: "Frontend (Next.js) conventions for voice-first UI: audio capture, streaming, WebSocket patterns"
globs:
  - "apps/web/**"
alwaysApply: false
---

## Frontend scope
Applies to `apps/web/**` (Next.js App Router).

## Principles (voice-first)
- **Streaming-first UX**: show partial transcripts, partial assistant text, and “speaking” state.
- **Low-latency over cleverness**: prefer simple, reliable patterns that keep audio moving.
- **Barge-in is mandatory**: user speech should immediately stop TTS playback and cancel in-flight generation.
- **Privacy by default**: no third-party telemetry; do not send audio/text anywhere except our local API.

## Audio capture (browser)
- Prefer **AudioWorklet** for low-latency mic capture; fall back to ScriptProcessorNode only if needed.
- Normalize capture to **16kHz mono PCM** frames (e.g., 20ms frames).
  - If the device rate is 44.1k/48k, resample client-side (or send raw and resample server-side—decide once and keep consistent).
- Use **push-to-talk** as a fallback UX option if echo/endpointing is tricky.

## Transport
- **WebSocket first** for MVP.
  - Send small binary frames (PCM) with lightweight metadata.
  - Keep payloads compact; avoid JSON per-audio-frame if possible.
- Plan for **upgrade to WebRTC** later if we need best-in-class echo handling and media transport.

## WebSocket patterns
- Centralize connection logic in a small module/hook (e.g., `useVoiceSocket()`).
- Support:
  - **reconnect** with backoff
  - **explicit close** on route change/unmount
  - **backpressure**: drop/queue frames if socket is congested; never freeze UI thread
- Keep a stable message protocol:
  - `audio_frame` (binary)
  - `partial_transcript`
  - `final_transcript`
  - `assistant_message` (or token streaming later)
  - `error` (surface STT/LLM failures explicitly)
  - `cancel` / `barge_in`

## Protocol + serialization
- Prefer **typed message shapes** and schema validation:
  - backend uses Pydantic `model_validate(...)` / `TypeAdapter(...).validate_python(...)`
  - backend emits `send_json(model.model_dump())`
- Client should:
  - send JSON objects (not pre-stringified JSON) when possible
  - keep message schema stable and versionable (additive changes first)

## Playback + cancellation
- Use Web Audio API for playback where practical (fine control, quick stop).
- On barge-in:
  - **stop playback immediately**
  - send a **cancel** message to API (so backend cancels LLM/TTS)
  - clear any buffered audio chunks

## State management
- Keep UI state minimal and explicit:
  - `isRecording`, `isSpeaking`, `isConnecting`
  - `partialTranscript`, `finalTranscript`
  - `assistantText` (streaming)
- Avoid global state until needed; prefer component-local state + small hooks.

## Environment/config
- Only expose frontend-safe env vars with `NEXT_PUBLIC_*`.
- Use `NEXT_PUBLIC_API_BASE_URL` to talk to FastAPI.
- Do not call Ollama/whisper/TTS directly from the browser.

## Code style
- TypeScript for new code.
- Prefer small, testable modules:
  - `audio/` (capture/resample/encode)
  - `ws/` (protocol + connection)
  - `ui/` (components)


