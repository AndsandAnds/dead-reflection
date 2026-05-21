# Voice satellite protocol

**Status:** v1 spec, browser path live; satellite token mint + reference
device implementations land in v2.

A "voice satellite" is any device that wants to act as a remote mic +
speaker for the Reflections voice loop: a Raspberry Pi with a
ReSpeaker, an ESP32 with a MAX98357A, a wiped Google Home Mini running
a custom firmware, a tablet in the kitchen. The browser at
`http://localhost:3000/voice` is itself a satellite and uses this
protocol today; the v2 work is mostly auth (Bearer-on-WS instead of
session cookie) and a couple of small handshake extensions documented
below.

This document is the source of truth for what a satellite needs to
implement.

---

## 1. Transport

- **WebSocket** to `ws[s]://<api-host>/ws/voice`.
- One **session** per connection. The server runs the full
  capture → STT → LLM → TTS loop inside one connection and keeps it
  open across many user turns until the client disconnects.
- All client → server text messages are **JSON**. The current
  implementation also accepts **raw binary frames** of PCM16LE audio as
  an upgrade over base64; see §4.
- Server → client messages are **JSON** with a `type` field
  (see §5). TTS audio rides on `tts_chunk` JSON messages as base64
  WAV; binary TTS is a planned v2 optimization.

### Authentication

| Path                          | Auth                                                                          |
| ----------------------------- | ----------------------------------------------------------------------------- |
| Browser (today)               | HTTP-only `reflections_session` cookie set by `/auth/login`                   |
| Satellite (v2)                | `Authorization: Bearer <satellite token>` header on the WS upgrade request    |

Satellite tokens are minted per device and stored hashed in the
`satellite_tokens` table (migration `0012_satellite_tokens.py`). The
table is in place today; the mint endpoint and `make satellite-token`
CLI ship with v2. Tokens map 1:1 to a user; a satellite cannot belong
to no-one. Revocation is by setting `revoked_at`.

### TLS

The browser path runs cleartext on `ws://localhost:8000/ws/voice`
because everything is on `127.0.0.1`. A LAN-deployed satellite SHOULD
use `wss://` with a self-signed cert pinned on the device. Tailscale
Funnel / MagicDNS works too; the WS layer doesn't care.

---

## 2. Lifecycle

```
client                                      server
  | --- WS upgrade (Auth header for sats) ---> |
  | <----------- 101 Switching --------------- |
  | --- {"type":"hello", sample_rate:48000} -> |
  | <-------------- {"type":"ready"} --------- |
  |                                            |
  |  (USER TURN ───────────────────────────╮   |
  |                                        )   |
  | --- binary PCM16LE frames ------------> |
  | --- binary PCM16LE frames ------------> |
  |                  ...                       |
  |                              partial_transcript (best-effort)
  |                              partial_transcript
  | --- {"type":"end"} ----------------------> |
  |                              final_transcript {text, duration_s}
  |                              assistant_delta {delta:"..."}
  |                              assistant_delta {delta:"..."}
  |                              assistant_message {text:"<full>"}
  |                              tts_chunk {seq:0, wav_b64, is_last:false}
  |                              tts_chunk {seq:1, wav_b64, is_last:true}
  |                              done
  |                                            |
  |  (NEXT TURN — connection stays open)       |
  | --- binary PCM16LE frames ------------> |
  |                  ...                       |
  |
  |  (BARGE-IN)
  | --- {"type":"cancel"} -------------------> |
  |                              cancelled
  |                              (in-flight LLM/TTS aborted; queued TTS flushed)
```

A single connection handles many turns. The browser keeps the
connection open as long as the page is mounted. A satellite SHOULD do
the same: reconnect with exponential backoff (1s, 2s, 4s, 8s, 30s cap)
only on dropped connections.

---

## 3. `hello` (client → server)

```json
{
  "type": "hello",
  "sample_rate": 48000,
  "voice": "en_US-lessac-medium.onnx"
}
```

Both fields are optional. Sent **once** as the first message of the
connection.

- `sample_rate` (int, Hz): the rate of the PCM16LE frames the client
  will send. The server resamples to 16 kHz before STT. Common values:
  `16000`, `24000`, `44100`, `48000`. Defaults to 16000 if omitted.
- `voice` (string): TTS voice identifier (engine-specific —
  `en_US-lessac-medium.onnx` for Piper, `Samantha` for macOS `say`).
  Falls back to the active avatar's `voice_config.tts_voice` and then
  the bridge default.

### v2 capability extensions (forward-compatible, server ignores
unknown keys today)

```json
{
  "type": "hello",
  "sample_rate": 16000,
  "voice": "en_US-lessac-medium.onnx",
  "client": {
    "name": "kitchen-pi",
    "fw_version": "0.1.0",
    "has_mic": true,
    "has_speaker": true,
    "vad_local": true,
    "echo_cancellation": "aec3"
  }
}
```

The server will persist whatever it receives under `client` to
`satellite_tokens.capabilities` on first connect, so admins can list
known devices and their profiles. The server also uses
`vad_local=true` to skip its own server-side RMS endpointing.

The server responds with:

```json
{ "type": "ready" }
```

…immediately on success, or:

```json
{ "type": "error", "code": "unauthenticated", "message": "..." }
```

…before closing the socket on auth failure.

---

## 4. Audio in (client → server)

### Preferred: binary frames

After `hello`, the client streams raw PCM16LE mono samples as **binary
WebSocket frames**. No JSON wrapper, no base64, no framing header —
just bytes. Frame size is not prescribed; 20–40 ms (640–1280 samples
at 16 kHz, or 1920–3840 samples at 48 kHz) is a good default. The
server applies backpressure by **dropping frames silently when its
queue saturates**, so the client should not rely on every frame being
read.

### Legacy: base64 in JSON

Still supported for browsers that can't send binary easily:

```json
{
  "type": "audio_frame",
  "pcm16le_b64": "<base64 of raw PCM16LE>",
  "sample_rate": 48000
}
```

Per-frame `sample_rate` may differ from the `hello` value; the server
resamples each frame independently. Prefer binary frames in new
clients.

### `cancel` (barge-in)

```json
{ "type": "cancel" }
```

Sent when the user starts speaking again while the assistant is
talking, or to abort an in-flight turn. The server aborts STT/LLM/TTS
in flight, flushes queued `tts_chunk` audio, and responds with
`cancelled`. The connection stays open; the next turn begins as soon
as audio arrives.

### `end` (endpoint)

```json
{ "type": "end" }
```

Tells the server "I'm done speaking, transcribe what you have and
respond." The browser sends this automatically via a client-side
silence timer (or push-to-talk release). A satellite with local VAD
(`vad_local: true` in `hello`) decides when to send `end`; without
local VAD the server's RMS-threshold endpointing also fires `end`
automatically after a short silence.

---

## 5. Server → client messages

All messages have a `type` field. New fields may be added without
notice; clients MUST ignore unknown fields and unknown message types.

| `type`                | When                                  | Fields                                                          |
| --------------------- | ------------------------------------- | --------------------------------------------------------------- |
| `ready`               | Right after `hello`                   | —                                                               |
| `partial_transcript`  | While STT is running (best-effort)    | `text`, `bytes_received`                                        |
| `final_transcript`    | After `end`, before LLM call          | `text`, `bytes_received`, `duration_s`                          |
| `assistant_delta`     | Streaming LLM tokens                  | `delta` (incremental text)                                      |
| `assistant_message`   | LLM stream complete                   | `text` (full assistant reply)                                   |
| `tts_chunk`           | TTS audio is ready, possibly chunked  | `seq` (int), `wav_b64` (16 kHz PCM16 WAV), `is_last` (bool)     |
| `tts_audio` (legacy)  | Single-shot TTS (non-chunked)         | `wav_b64`                                                       |
| `cancelled`           | After processing a `cancel`           | —                                                               |
| `done`                | Turn complete; ready for next audio   | —                                                               |
| `error`               | Anything went wrong this turn         | `message`, `code?`, `details?` (see §6)                         |

The `tts_chunk` WAV is always **16 kHz mono PCM16** so the client
playback path is uniform regardless of which TTS engine produced it.
Concatenate by `seq` order (gaps are bugs); play each chunk through a
WebAudio buffer or, on embedded, write it straight to an I2S DAC.

---

## 6. Errors

```json
{
  "type": "error",
  "code": "stt_error",
  "message": "whisper.cpp returned rc=1",
  "details": { "rc": 1 }
}
```

Codes shipped today:

- `unauthenticated` — invalid / missing bearer (v2) or session cookie expired mid-stream
- `stt_error:<reason>` — STT bridge unreachable or returned an error
- `ollama_error:<reason>` — LLM call failed
- `tts_error:<reason>` — TTS bridge unreachable or failed
- `bad_message` — couldn't parse a client JSON message

`code` is stable; `message` and `details` are not. Clients should
key off `code` when branching.

Session expiry mid-stream: the current turn is allowed to finish; new
audio frames will receive an `error` with `code: unauthenticated` and
the server will close the socket. Reconnect to continue.

---

## 7. Reference implementations (v2)

To ship along with the satellite-token mint endpoint:

### 7a. Raspberry Pi 4/5 + ReSpeaker 2-Mics HAT

- Python with `sounddevice` (PortAudio) for I/O
- `webrtcvad` or `silero-vad` for `vad_local`
- `websockets` for the WS client
- TTS playback via ALSA → ReSpeaker speaker out
- Wake-word optional; for v2 we ship push-to-talk via the HAT's button.
  Wake-word likely Porcupine (free for personal use) or
  [`openWakeWord`](https://github.com/dscripka/openWakeWord) (Apache 2.0).

### 7b. ESP32 (lowest-cost option)

- I2S mic (INMP441 / SPH0645) + I2S DAC (MAX98357A)
- Arduino ESP32 + `ArduinoWebsockets` (or ESP-IDF)
- Compressed WAV decode is heavier than the chip likes; v2 may add
  an Opus chunk variant of `tts_chunk` specifically for embedded
  satellites that can't decode arbitrary WAV fast enough.

### 7c. Wiped Google Home Mini

- Hardware support is fragmented across generations. Confirm
  flashability before sinking time. Likely path: install a custom
  Linux distro (Ubuntu Server arm64 + alsa) on devices with
  documented bootloader unlocks, then run the Pi client unchanged.

---

## 8. Out of scope (today)

- **Multi-user**: a single connection is single-user. Multiple
  satellites can connect to the same user, each with its own token.
- **Echo cancellation on the server side**: hardware-level AEC on
  the satellite (mic array DSP or `aec3` in WebRTC) is the right
  layer for this. Server-side AEC is a v2+ research item.
- **End-to-end encryption of audio over a hostile network**: the
  spec assumes LAN or a trusted tunnel (Tailscale, WireGuard).
  Public-internet voice will want WebRTC with DTLS-SRTP, which is a
  larger protocol change.

---

## 9. Versioning

This spec describes **protocol v1**. Future versions will:

- bump `hello` capability fields
- possibly add binary TTS frames as an opt-in (`tts_chunk_bin`)
- add server-side metrics on the `ready` response

Clients MUST ignore unknown fields and unknown message types so old
satellites keep working when the server is upgraded.
