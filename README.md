# Reflections — Local Avatar AI (Voice-First, Offline-First)

Runs a character.ai-style “avatar AI” locally on Apple Silicon. **No data leaves your machine** by default.

## Stack (current)
- **Frontend**: Next.js (App Router)
- **Backend**: FastAPI + PydanticAI (agent orchestration)
- **DB**: Postgres **18** + pgvector (Docker)
- **Embeddings**: SentenceTransformers
- **LLM runtime**: Ollama (**host-installed on macOS for Metal**; containers call `host.docker.internal`)
- **STT**: whisper.cpp + Metal (**host-installed**) via a small local STT bridge (`make stt-bridge`)
- **Tests**: pytest (backend), Vitest + Testing Library (frontend)
- **Code cleanliness**: pre-commit (Ruff + Prettier + basic hooks)

Architecture notes live in `docs/local-avatar-ai-stack.md`.

## Prerequisites
- Docker Desktop (Apple Silicon)
- Poetry 2.x
- Ollama installed on the host (macOS)
  - Ensure it’s reachable at `http://localhost:11434`

Optional (voice):
- `whisper.cpp` (Homebrew) + a Whisper model file (see “Voice (STT) setup” below)

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

If you upgraded Postgres major versions (e.g. 16 → 18) and the DB won’t start,
wipe the dev volume:

```bash
docker compose down -v
make up
make migrate
```

3) Open:
- UI: `http://localhost:3000`
- API health: `http://localhost:8000/health`

## Voice (STT) setup (whisper.cpp + Metal)
Ollama only accepts **text**, so for voice we must do **STT** first.

1) Install whisper.cpp:

```bash
brew install whisper-cpp
```

2) Download a model (English-only example):

```bash
mkdir -p ~/whisper-models
curl -L -o ~/whisper-models/ggml-base.en.bin \
  https://huggingface.co/ggerganov/whisper.cpp/resolve/main/ggml-base.en.bin
```

3) Run the STT bridge (host):

```bash
export WHISPER_CPP_BIN=/opt/homebrew/bin/whisper-cli
export WHISPER_CPP_MODEL="$HOME/whisper-models/ggml-base.en.bin"
make stt-bridge
```

4) Configure `.env` so the API uses the bridge:

```bash
# If the API runs in Docker (default), use host.docker.internal:
STT_BASE_URL=http://host.docker.internal:9001
STT_TIMEOUT_S=120
```

Then in the UI:
- Start mic → speak → Stop (transcribe)
  - backend emits `final_transcript` (real STT text when STT is configured)
  - backend calls Ollama with that text and emits `assistant_message`

## Voice (TTS) setup (macOS `say` or Piper)
We support local **TTS** by running a small host bridge that returns a **16kHz PCM WAV**
the browser can play via WebAudio.

1) Run the TTS bridge (host):

```bash
make tts-bridge
```

2) Configure `.env` so the API uses the bridge:

```bash
TTS_BASE_URL=http://host.docker.internal:9002
TTS_TIMEOUT_S=30
```

Then in the UI:
- Start mic → speak → Stop (transcribe)
  - backend emits `tts_chunk` (preferred) and the UI plays the spoken reply

### Option A: macOS `say` (default)
No extra installs needed. Optionally set a default voice for the bridge:

```bash
export TTS_ENGINE=say
export TTS_VOICE="Samantha" # optional
make tts-bridge
```

### Option B: Piper (recommended next step)
Piper is a low-latency local neural TTS. Our bridge can call Piper when enabled.

1) Install Piper (recommended: `pipx`, since this runs on your host):

```bash
brew install pipx
brew install python@3.13

# IMPORTANT: pipx uses its default Python. Piper dependencies (onnxruntime) may
# not yet support the newest Python (e.g. 3.14). Force a supported Python:
pipx install --python /opt/homebrew/opt/python@3.13/libexec/bin/python piper-tts
```

This installs the `piper` CLI via the official project ([`OHF-Voice/piper1-gpl`](https://github.com/OHF-Voice/piper1-gpl)).

Alternative (if you don’t want `pipx`): `pip install piper-tts` into a dedicated venv.

2) Download a Piper voice model (expects **two files**: `.onnx` + matching `.onnx.json`):

```bash
mkdir -p ~/piper-models
# Example filenames (pick any model you like):
#   en_US-lessac-medium.onnx
#   en_US-lessac-medium.onnx.json
```

Voice list + download links:
- Voice list: [`VOICES.md`](https://raw.githubusercontent.com/OHF-Voice/piper1-gpl/main/docs/VOICES.md)
- Downloads: `https://huggingface.co/rhasspy/piper-voices/tree/main` (linked from `VOICES.md`)

3) Run the bridge with Piper enabled:

```bash
export TTS_ENGINE=piper
export PIPER_MODEL="$HOME/piper-models/en_US-lessac-medium.onnx"
export PIPER_BIN=piper          # optional if it's on PATH
export PIPER_SPEAKER=0          # optional (multi-speaker models)
make tts-bridge
```

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

