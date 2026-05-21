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

Tools available today (curated, not auto-generated from REST routes):

- **Memory**: `record_memory`, `recall_memory`, `inspect_memories`, `delete_memory`
- **Entities** (people / places / events / topics): `list_entities`,
  `get_entity`, `add_entity`, `update_entity`, `delete_entity`,
  `merge_entities`, `list_entity_memories`, `link_memory_to_entity`
- **Calendar** (Apple Calendar via host bridge): `list_calendars`,
  `list_calendar_events`, `create_calendar_event`,
  `update_calendar_event`, `delete_calendar_event`
- **Vault** (markdown export / import): `export_vault`, `import_vault`
- **Artifacts** (in-place catalog of external drives): `register_volume`,
  `list_volumes`, `catalog_volume`, `list_artifacts`,
  `set_extraction_policy`, `apply_extraction_policies`,
  `extract_artifact`, `delete_artifact`
- **Web** (admin only, audited): `internet_search`

### Mint a token

Two scope flavors:

```bash
# Default — read + write public content; no access to "private" rows.
make mcp-token email=you@example.com name="Claude Desktop"

# Trusted client — also includes private content.
# Note: mcp:read_private only takes effect for an ADMIN user.
# A non-admin with the scope still gets the public view.
make mcp-token email=admin@example.com name="trusted" \
  scopes="mcp:read,mcp:write,mcp:read_private"
```

The raw token (looks like `ref_mcp_…`) is printed once to **stdout** and is
not recoverable from the DB afterwards — store it immediately. Token metadata
can be listed via `GET /mcp/tokens` (authenticated session cookie required)
and revoked via `DELETE /mcp/tokens/{id}`.

### Privacy model

Memory rows can be flagged `private = true`. The MCP `recall_memory` and
`inspect_memories` tools exclude private rows unless **both** conditions
hold for the caller's token:

1. The token carries the `mcp:read_private` scope (opt-in at mint time).
2. The user the token belongs to is currently `is_admin = true`.

Admin status is re-checked at token verification (every MCP request), so
demoting a user immediately revokes private-content access from every
token they hold — no need to revoke each token individually. The web UI
(session-cookie auth) always shows the signed-in user their own private
content; the privacy gate only governs the MCP recall surface.

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

### One-time macOS permission grant (use the .app launcher)

EventKit requires user consent. A plain `python -m uvicorn ...` process
has no Info.plist that macOS recognizes for TCC, so the permission
prompt is silently denied AND the process never appears in System
Settings → Privacy & Security → Calendars. The fix is a minimal `.app`
bundle that declares `NSCalendarsFullAccessUsageDescription`.

```bash
# Build the bundle (idempotent; rebuild any time).
make calendar-bridge-app

# Launch it — this is the moment macOS prompts you.
open apps/macos/ReflectionsCalendarBridge.app

# Trigger the EventKit request to show the dialog.
curl -X POST http://127.0.0.1:9004/authorize
# → click Allow on the macOS prompt

# Verify.
curl -s http://127.0.0.1:9004/health | jq .
# → {"status":"ok","auth_status":"authorized","auth_status_code":3}
#   (or "fullAccess"/5 on macOS 14+)
```

The bundle re-execs `poetry run python -m uvicorn ...` from your
project root, so all existing deps work. Logs land in
`run/calendar-bridge.app.log`. The bundle is gitignored — the build
is reproducible via `make calendar-bridge-app`.

`make calendar-bridge` (terminal foreground) also works once
permission has been granted to the bundle; TCC keys the entry by
bundle id, so System Settings → Privacy & Security → Calendars shows
a single "Reflections Calendar Bridge" entry instead of a confusing
"Python".

To stop:

```bash
make bridges-down   # also stops STT/TTS if running
# or:
pkill -f reflections.calendar_bridge
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

## Vault (markdown export / import)

The DB is canonical; the **vault** is a human-readable interop layer.
Export renders every memory + entity as markdown for backup, grep, git,
or editing in Obsidian / any text editor. Import reads an edited vault
back and updates existing rows (re-embedding any memory whose content
changed).

Layout written on export:

```
vault/
  .reflections-version
  daily/YYYY-MM-DD.md       — every memory that day, in time order
  people/<slug>.md          — one note per person entity
  places/<slug>.md
  events/<slug>.md
  topics/<slug>.md
```

Each note carries enough metadata (YAML frontmatter + HTML-comment
markers for memory blocks) that the importer finds rows by id.

### REST

```bash
# Export (downloads a tar.gz). Header X-Vault-Stats has the counts.
curl -b cookie.txt -X POST http://localhost:8000/vault/export -o vault.tar.gz

# Import (uploads a tar.gz of the same shape; dry_run=true to preview).
curl -b cookie.txt -X POST 'http://localhost:8000/vault/import?dry_run=true' \
  -F 'file=@vault.tar.gz'
```

### MCP

From Claude Desktop / LM Studio:

- `export_vault(target_path="/abs/path/vault.tar.gz")` — writes the
  archive to disk, returns `{path, bytes, daily_notes, entity_notes,
  memories, entities}`.
- `import_vault(source_path="/abs/path/vault.tar.gz", dry_run=false)` —
  applies edits, returns `{memories_updated, memories_reembedded,
  entities_updated, skipped, errors}`.

### What import will and won't do (v1)

| Change                          | Honored? |
| ------------------------------- | -------- |
| Edit a memory's body            | Yes — re-embeds the new content. |
| Add a description to an entity  | Yes. |
| Edit an existing description    | Yes. |
| Add a new memory                | **No** — record via `record_memory` / the chat UI. |
| Add a new entity                | **No** — add via `add_entity` / inferred from new memories. |
| Delete a memory / entity        | **No** — delete via `delete_memory` / `delete_entity`. |
| Clear a description             | **No** in v1 — UI/MCP only. |

These limits keep the import safe (no destructive surprises) and the DB
canonical. A future v2 may bring bidirectional sync via a file watcher,
likely a Rust `notify-rs` daemon.

### Round-trip in action

```bash
# Export, edit a person's description in Obsidian, import back.
make mcp-token email=you@example.com name="vault-roundtrip"  # -> $TOK
# (use the MCP token via Claude Desktop, LM Studio, or curl)
```

## Artifact catalog (in-place file indexing)

Reflections can catalog the files on an external drive (or any host
folder) **without moving them** and **without auto-processing
contents**. The bytes stay where they are; Postgres only stores stat
metadata (path, mtime, size, mime, lazy sha256) until you explicitly
opt a folder in for extraction.

The catalog runs as a **host bridge** on `:9005` (not in Docker) so it
can see drives the user plugs in after `docker compose up`. Same pattern
as the calendar / STT / TTS bridges.

### One-time setup

```bash
# 1. Run the bridge as a proper .app so macOS can grant Full Disk Access.
make catalog-bridge-app
open apps/macos/ReflectionsCatalogBridge.app

# 2. Grant Full Disk Access in System Settings → Privacy & Security →
#    Full Disk Access → toggle on "Reflections Catalog Bridge".

# 3. Tell the api container where the bridge listens (add to .env):
CATALOG_BRIDGE_URL=http://host.docker.internal:9005

# 4. Re-create the api so it picks up the env var, then start the bridge in
#    the background (joins `bridges-up` automatically when CATALOG_BRIDGE_URL
#    is set).
docker compose up -d api
make catalog-bridge-bg
```

### Index a folder (one command)

```bash
make crawl-folder email=you@example.com path=/Volumes/Photos-10TB \
                  label="Photos Archive"
```

This registers the folder as a "volume" (idempotent — drops a
`.reflections-volume.json` marker so it's identifiable across
remounts), then walks it stat-only. Output:

```
  Volume: Photos Archive (id=…)
  fingerprint=b2c3-…, volume_uuid=ABCD-1234

  Walking /Volumes/Photos-10TB...

  Files seen:        12384
  Newly added:       12384
  Updated (changed): 0
  Unchanged:         0
  Pages fetched:     3
  Elapsed:           5.21s
```

Re-running is safe — unchanged files are no-ops, real changes mark
already-extracted artifacts `stale` so the next extraction pass
re-runs them.

### Extracting content (text from PDF / image / audio / video)

Extraction is **opt-in per (volume, glob, mime, kind)**:

```bash
# In Claude Desktop with an MCP token that has mcp:read + mcp:write:
#   "Set a policy on volume <id>: extract all PDFs as public, and
#   .heic images as private."
#   "Apply extraction policies on that volume."
```

Or via curl using the `set_extraction_policy` and
`apply_extraction_policies` MCP tools. Each rule has an `action`:

- `extract` — derive text, store memory chunks publicly
- `extract_private` — derive text, store chunks with `private=true`
  (only callers who are admin AND have the `mcp:read_private` scope
  can recall them; web UI shows them to the signed-in user always)
- `ignore` — skip (default for anything that matches no rule)

Extractors today:

| Kind | Pipeline | Notes |
|---|---|---|
| `pdf` | `pypdf` | One chunk per non-empty page; locator `{page, total_pages}` |
| `image` | EXIF via Pillow + caption via Ollama `qwen3-vl` | EXIF (incl. GPS) → artifact attributes; caption → chunk text |
| `audio` | STT bridge (whisper.cpp) | Transcript chunked at sentence boundaries |
| `video` | `ffmpeg` → audio path | Strips audio to 16 kHz mono PCM, then transcribes |

After extraction, the existing entity-extraction pass runs over the
new chunks for free — so a PDF mentioning Sarah and Brooklyn auto-
populates those entities and links them to the artifact.

### What lands in the graph

`/memory/graph` includes artifact nodes by default (toggle with
`?include_artifacts=false`). Edges:

- `memory:<id>` → `artifact:<id>` (relation `from_artifact`) when a
  chunk was derived from an artifact
- `artifact:<id>` → `entity:<id>` (relation `mentions`) from
  `artifact_entity_links`

Artifact node kinds in the palette: `artifact_pdf` (violet),
`artifact_image` (sky), `artifact_audio` (amber), `artifact_video`
(red), `artifact_other` (slate).

### Stopping / restarting

```bash
make bridges-status   # show what's up
make bridges-down     # stop STT + TTS + Calendar + Catalog
make bridges-up       # start everything CATALOG_BRIDGE_URL is set
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

