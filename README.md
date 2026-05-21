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

## Optional: Create a “Lumina” model in Ollama (Modelfile)
Ollama supports lightweight customization via a `Modelfile` (system prompt + parameters + optional exemplars). See the upstream reference: [`Modelfile` docs](https://raw.githubusercontent.com/ollama/ollama/main/docs/modelfile.mdx).

This repo includes `ollama/Modelfile.lumina`, which defines **Lumina** as a personal assistant identity.

Create the model on your host:

```bash
ollama create lumina -f ollama/Modelfile.lumina
```

Then set your `.env` to use it:

```bash
OLLAMA_MODEL=lumina
```

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

If you’re using `make up` (which starts bridges automatically), put these in `.env`
instead so the background bridge process can read them:

```bash
WHISPER_CPP_BIN=/opt/homebrew/bin/whisper-cli
WHISPER_CPP_MODEL=/Users/once/whisper-models/ggml-base.en.bin
```

4) Configure `.env` so the API uses the bridge:

```bash
# If the API runs in Docker (default), use host.docker.internal:
STT_BASE_URL=http://host.docker.internal:9001
STT_TIMEOUT_S=120
```

Then in the UI:
- Start mic (or **hold Space**) → speak → Stop (transcribe) (or **release Space**)
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
- Start mic (or **hold Space**) → speak → Stop (transcribe) (or **release Space**)
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
export PIPER_MODELS_DIR="$HOME/piper-models"
export PIPER_BIN=piper          # optional if it's on PATH
export PIPER_SPEAKER=0          # optional (multi-speaker models)
make tts-bridge
```

Stop it:

```bash
make down
```

## MCP server (Claude Desktop, local LLMs)

The FastAPI app exposes a [Model Context Protocol](https://modelcontextprotocol.io)
server at `http://localhost:8000/mcp/` (Streamable HTTP transport). It is
authenticated with per-user bearer tokens stored in the `mcp_tokens` table.

Tools available in v1 (curated, not auto-generated from REST routes):

- **Memory**: `record_memory`, `recall_memory`, `inspect_memories`, `delete_memory`
- **Entities** (people / places / events / topics): `list_entities`,
  `get_entity`, `add_entity`, `update_entity`, `delete_entity`,
  `merge_entities`, `list_entity_memories`, `link_memory_to_entity`

### Mint a token

```bash
make mcp-token email=you@example.com name="Claude Desktop"
```

The raw token (looks like `ref_mcp_…`) is printed once to **stdout** and is
not recoverable from the DB afterwards — store it immediately. Token metadata
can be listed via `GET /mcp/tokens` (authenticated session cookie required)
and revoked via `DELETE /mcp/tokens/{id}`.

### Wire into Claude Desktop

Edit `~/Library/Application Support/Claude/claude_desktop_config.json`:

```json
{
  "mcpServers": {
    "reflections": {
      "url": "http://localhost:8000/mcp/",
      "headers": {
        "Authorization": "Bearer ref_mcp_PASTE_YOUR_TOKEN_HERE"
      }
    }
  }
}
```

Restart Claude Desktop; the `reflections` server should appear in the
Settings → Developer panel and its tools (`recall_memory`, `add_entity`,
etc.) become callable in conversations.

### Wire into a local LLM (LM Studio, Ollama OpenWebUI, etc.)

Any client that supports MCP over HTTP/SSE can point at the same URL with the
same `Authorization: Bearer` header. The session-id handshake is standard MCP.

### Verify by hand

```bash
TOK=$(make -s mcp-token email=you@example.com name="curl")
SID=$(curl -si -X POST http://localhost:8000/mcp/ \
  -H "authorization: Bearer $TOK" \
  -H 'content-type: application/json' \
  -H 'accept: application/json, text/event-stream' \
  -d '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2025-06-18","capabilities":{},"clientInfo":{"name":"curl","version":"0"}}}' \
  | awk -F': ' 'tolower($1)=="mcp-session-id"{print $2}' | tr -d '\r')

curl -s -X POST http://localhost:8000/mcp/ \
  -H "authorization: Bearer $TOK" -H "mcp-session-id: $SID" \
  -H 'content-type: application/json' \
  -H 'accept: application/json, text/event-stream' \
  -d '{"jsonrpc":"2.0","method":"notifications/initialized"}'

curl -s -X POST http://localhost:8000/mcp/ \
  -H "authorization: Bearer $TOK" -H "mcp-session-id: $SID" \
  -H 'content-type: application/json' \
  -H 'accept: application/json, text/event-stream' \
  -d '{"jsonrpc":"2.0","id":2,"method":"tools/list"}'
```

## Internet egress (admin only)

Reflections is local-first. Outbound HTTP calls on behalf of a user are
**denied** by default and only allowed for users where `is_admin=true`. Every
attempt — successful, denied, or errored — is recorded in
`outbound_audit_log` for review.

The single sanctioned outbound capability today is the MCP tool
`internet_search`, which scrapes [DuckDuckGo Lite](https://lite.duckduckgo.com/lite/)
(no API key, no JavaScript, no telemetry). All outbound traffic is mediated
by [`OutboundService`](src/reflections/outbound/service.py), which:

1. Refuses non-admin calls before any network I/O happens.
2. Times every call and records the URL, HTTP status, outcome, and any error
   to `outbound_audit_log`.
3. Optionally routes through `EGRESS_PROXY_URL` (a future Squid/tinyproxy/
   etc.) when configured — this is the hook for a hardened network-level
   isolation layer.

### Promoting yourself to admin

The first signup is auto-promoted. For existing DBs:

```bash
docker compose exec db psql -U ref -d reflections \
  -c "UPDATE users SET is_admin=true WHERE email='you@example.com';"
```

### Reviewing the audit log

Admin-only, supports filters by user and outcome:

```bash
# you'll need an admin session cookie from /auth/login
curl -b your_cookie_jar.txt 'http://localhost:8000/admin/outbound-audit-log?limit=50&outcome=denied'
```

### Deferred (v2)

- **Voice integration**: the voice agent loop doesn't yet have PydanticAI
  tool wiring, so `internet_search` is currently only available via MCP
  (Claude Desktop / LM Studio). Voice "go online" toggle planned next.
- **Network-level isolation**: putting `api` on a Docker `internal: true`
  network is complicated by the STT/TTS/calendar bridges that live on
  `host.docker.internal`. A v2 setup would add a hardened egress proxy
  container and tighten container egress via iptables, with bridges either
  whitelisted or moved into Docker.

## Apple Calendar (host bridge)

Reflections can read and write your local Apple Calendar via a small
host-side FastAPI bridge (`reflections.calendar_bridge`) — the same pattern
as the STT/TTS bridges. It uses [`pyobjc-framework-EventKit`](https://pypi.org/project/pyobjc-framework-EventKit/),
which is macOS only.

### Install + start

```bash
# 1. Install macOS-only deps into the host Poetry env (once).
poetry install --extras mac

# 2. Tell the api container where the bridge will listen.
#    Add to .env:
CALENDAR_BRIDGE_URL=http://host.docker.internal:9004
# optional shared secret so other Mac apps can't poke this port:
CALENDAR_BRIDGE_SECRET=$(openssl rand -hex 24)

# 3. Start the bridge (foreground or background).
make calendar-bridge          # foreground
make calendar-bridge-bg       # background (pid in ./run, logs in ./run/)
# bridges-up also starts STT + TTS in one go:
make bridges-up
```

### One-time macOS permission grant

EventKit requires user consent. **First-time setup needs a manual step
because a CLI-launched Python process doesn't carry an Info.plist that
macOS recognizes as a Calendar-aware app.** When the bridge calls
`requestFullAccessToEventsWithCompletion_`, macOS silently denies and your
terminal won't show the dialog.

The fix is to grant access via System Settings:

1. **System Settings → Privacy & Security → Calendars**
2. Toggle on the Python binary running the bridge — typically your
   Poetry venv's `python`, your `pyenv`-managed Python, or the Terminal/
   iTerm/Cursor app that launched the bridge. On macOS 14+ choose
   **Full Access** for both read and write.
3. Restart the bridge:
   ```bash
   make bridges-down && make bridges-up
   ```
4. Verify:
   ```bash
   curl -s http://127.0.0.1:9004/health | jq .
   # → {"status":"ok","auth_status":"fullAccess","auth_status_code":5}
   ```

If you don't see Python listed at all under Privacy & Security → Calendars,
trigger the prompt-registration first by calling `POST /authorize` once:

```bash
curl -X POST http://127.0.0.1:9004/authorize
```

Even if it returns `granted:false`, macOS now knows about your process and
it'll appear in the Calendars permission list.

### What you can do once granted

REST (authenticated session cookie required):

```bash
curl -b cookie.txt http://localhost:8000/calendar/health      # bridge state
curl -b cookie.txt http://localhost:8000/calendar/calendars   # list calendars
curl -b cookie.txt 'http://localhost:8000/calendar/events?start=2026-05-21T00:00:00Z&end=2026-05-22T00:00:00Z'
```

MCP (from Claude Desktop / LM Studio): new tools `list_calendars`,
`list_calendar_events`, `create_calendar_event`, `update_calendar_event`,
`delete_calendar_event` (all timestamps ISO 8601 with timezone offset).

### Deferred (v2)

- **Bundle as a proper .app** so EventKit prompts the user instead of needing
  the manual System Settings step. Could ship as `.venv/Calendar Bridge.app`
  with `py2app` / `briefcase`, or wrap with a small Swift launcher.
- **Web UI `/calendar` page** — today + upcoming, quick-create form.
- **Voice integration** — "what's on my calendar today?" / "schedule X
  tomorrow at 3" via the voice agent loop (needs PydanticAI tool wiring).
- **Daily-note folding** — surface that day's calendar events in the
  Explore page and markdown export.

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

