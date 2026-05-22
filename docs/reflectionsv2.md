# Plan — Local Voice Agent + Knowledge Graph + MCP + Calendar

## Context

The user wants a fully-local voice agent that remembers events and conversations, supports auth/users, exposes itself via MCP (Claude Desktop + local LLMs), reads/writes the user's Apple Calendar, and is **internet-isolated for non-admin users**. The user also wants a **human-readable knowledge graph** that can be browsed and edited (Obsidian-style was illustrative — a polished web UI is acceptable, with markdown export as an interop layer). Open-source only, vendor-agnostic. MCP server should use **FastMCP** and stay as close to FastAPI as possible.

Two existing codebases were reviewed:
- `/Users/once/Development/light-void` — sprawling (Neo4j + Qdrant + Redis + MinIO + Celery), drifted from the life-timeline vision, has legacy Revelator (music distribution) Celery code that doesn't belong, no MCP, no voice pipeline, no admin gating.
- `/Users/once/Development/reflections` — ~80% of the target already. Voice loop (whisper.cpp + Metal + Piper) works, auth/sessions live, memory_items table with auto-ingest works, conversations persist with replay, avatars + voice config wired, PydanticAI agent orchestration. **Zero vendor SDKs**. Strict layering (api/service/repository/schemas/exceptions/flows) enforced.

**Decision: continue from `reflections`. Abandon `light-void`.**

## v1 Scope

Build on `reflections` to add:
1. Admin role + first-signup-promotes
2. Entity-aware knowledge graph (people / places / events / topics) on top of `memory_items`
3. Web UI for knowledge graph browse + semantic search + inline edit
4. Markdown export/import as interop with Obsidian / any text editor
5. Internet egress gating — network-level isolation + app-layer wrapper, admin-only per-call toggle
6. **Apple Calendar integration** via a host EventKit bridge (read + write + list calendars)
7. **MCP server using FastMCP, mounted inside FastAPI** at `/mcp` for HTTP; thin stdio shim for Claude Desktop. Curated toolset includes memory + calendar.
8. Voice satellite protocol spec (documentation only — no hardware in v1)

## v2 Scope (explicitly deferred)

- Rust ports — FastMCP-equivalent in rmcp, vault watcher (notify-rs), VAD/resampling helpers
- Voice satellites (Pi + ReSpeaker, possibly wiped Google Home if confirmed flashable)
- Kubernetes manifests
- LoRA fine-tuning / vLLM migration
- LLM-based memory extraction replacing the heuristic at [src/reflections/memory/service.py:43](src/reflections/memory/service.py:43)
- Date-based recall and daily objective (already on `docs/next-steps.md` P1)
- Cross-platform calendar (CalDAV, Google Calendar) — EventKit-only in v1
- Bidirectional vault file-watcher (one-way export + manual import in v1)

## User Stories

- As a household user, I speak to the assistant and it remembers what matters.
- As a household user, I browse my life as a navigable knowledge graph (people → events → days), search semantically, and edit a memory inline. Changes round-trip back to recall.
- As a household user, I ask "what's on my calendar today?" or "schedule a haircut next Tuesday at 3" and the assistant reads/writes Apple Calendar via the host bridge.
- As a household user, I ask "what did I do on March 5?" and get a date-grounded reply that pulls from both memories AND calendar events.
- As a household user, I export my entire vault to markdown (one click) for backup or Obsidian use.
- As an **admin** user, I flip an "internet" toggle for a single turn ("look up this song"). UI shows clear indicator. Non-admins cannot.
- As a power user, I install the MCP server in Claude Desktop and have it `record_memory`, `recall_memory`, `search_memories`, `get_today`, `list_calendar_events`, `create_calendar_event`.
- As a power user, I point a local Ollama at the MCP HTTP endpoint (`http://localhost:8000/mcp`) and get the same tools.
- *(v2)* A Pi or wiped speaker acts as a satellite mic+speaker via the documented WS protocol.

## Architecture

```
┌───────────────────────────────────────────────────────────────┐
│ Browser (Next.js) — voice UI, knowledge graph, calendar       │
└──────────────┬───────────────────────────┬────────────────────┘
               │ WS /ws/voice              │ HTTPS REST + /mcp
               │                           │
┌──────────────▼───────────────────────────▼────────────────────┐
│ FastAPI (Docker, internal-net) — one app, many routers        │
│  ├─ auth/   ├─ voice/   ├─ memory/   ├─ conversations/        │
│  ├─ avatars/   ├─ entities/ (NEW)    ├─ vault/ (NEW)          │
│  ├─ calendar/ (NEW)                                           │
│  ├─ mcp/  (NEW — FastMCP sub-app mounted at /mcp)             │
│  └─ commons/depends — is_admin gate                           │
└──┬──────────────┬────────────────┬──────────────┬─────────────┘
   │              │                │              │
   │ host:9001    │ host:9002      │ host:9004    │ host:11434
   │ STT bridge   │ TTS bridge     │ Calendar     │ Ollama (Metal)
   │ (whisper.cpp)│ (Piper)        │ bridge (NEW) │
   │                               │ pyobjc/      │
   │                               │ EventKit     │
   │
   │  ┌──────────────────────────────────────────────────────┐
   │  │ Postgres 18 + pgvector (canonical)                   │
   │  │   users, sessions, memory_items, entities (NEW),     │
   │  │   memory_entity_links (NEW), conversations,          │
   │  │   conversation_turns, avatars, mcp_tokens (NEW),     │
   │  │   outbound_audit_log (NEW), satellite_tokens (NEW)   │
   │  └──────────────────────────────────────────────────────┘
   │
   │ egress-net (admin-only)
┌──▼────────────────────────────────────────────────────────────┐
│ egress-proxy — requires admin JWT, logs every outbound        │
└────┬──────────────────────────────────────────────────────────┘
     ▼ Internet

┌────────────────────────────────────────────────────────────────┐
│ Claude Desktop / local LLM client                              │
│  - stdio: `python -m reflections.mcp.stdio` (thin shim that    │
│           forwards to the same FastMCP server via HTTP/SSE)    │
│  - HTTP/SSE: http://localhost:8000/mcp                         │
└────────────────────────────────────────────────────────────────┘
```

**Key architectural choices driven by user feedback:**
- **One FastAPI app**, MCP is a sub-app mounted via `app.mount("/mcp", mcp.http_app())`. Shares auth dependencies, settings, DB sessions.
- **Calendar lives behind a host bridge** (same pattern as STT/TTS), because EventKit requires native macOS APIs and user-granted permission.

## Implementation Phases

### Phase 0 — Cleanup + admin role groundwork (~2 days)

**Files to add/modify:**
- `alembic/versions/<new>_add_users_is_admin.py` — `users.is_admin BOOLEAN NOT NULL DEFAULT FALSE`
- [src/reflections/auth/models.py](src/reflections/auth/models.py) — add `is_admin` column
- [src/reflections/auth/repository.py](src/reflections/auth/repository.py) — add `count_users()` helper
- [src/reflections/auth/service.py](src/reflections/auth/service.py) — in `signup()`, set `is_admin=True` if `count_users() == 0`
- [src/reflections/auth/depends.py](src/reflections/auth/depends.py) — add `current_admin_required` dependency, raises 403 for non-admins
- [apps/web/app/](apps/web/app/) — show "Admin" badge in `LuminaTopBar` when `me.is_admin`

**Test:** Sign up first user → DB shows `is_admin=true`. Sign up second → `is_admin=false`. Hit an admin-gated endpoint as second user → 403.

---

### Phase 1 — Entities + knowledge graph data model (~3 days)

`memory_items` is flat. A knowledge graph needs entities and explicit links.

**Files to add:**
- `alembic/versions/<new>_add_entities.py`:
  - `entities`: id (uuid7), user_id, kind ENUM('person','place','event','topic'), name, slug (unique per user+kind), description TEXT, attributes JSONB, embedding vector(384), created_at, updated_at
  - `memory_entity_links`: memory_item_id, entity_id, relation TEXT NULL, weight FLOAT NULL — PK (memory_item_id, entity_id, relation)
- `src/reflections/entities/` — full module following layering convention
  - Endpoints: `GET /entities`, `GET /entities/{id}`, `POST /entities`, `PATCH /entities/{id}`, `DELETE /entities/{id}`, `POST /entities/{id}/merge`, `GET /entities/{id}/memories`
- [src/reflections/memory/service.py:43](src/reflections/memory/service.py:43) — keep heuristic, plus a Pydantic AI extraction pass after ingest that:
  1. Asks Ollama for a structured `EntityExtractionResult { people[], places[], events[], topics[] }` from the chunk
  2. Upserts entities (match by slug per user+kind)
  3. Inserts `memory_entity_links`

**Test:** Speak a chunk containing names + a place + an event → entities row appears, links row appears, `GET /entities` lists them.

---

### Phase 2 — Web UI: knowledge graph + semantic search + inline edit (~5 days)

**Files to add (`apps/web/app/`):**
- `explore/page.tsx` — primary memory browse surface (search bar, filters, result cards with linked entity chips, inline edit)
- `graph/page.tsx` — knowledge graph viz using **react-force-graph-2d** (lightweight, OSS, MIT). Nodes = entities + memory cards; edges = `memory_entity_links`. Click → side panel
- `entity/[slug]/page.tsx` — entity detail (timeline of linked memories + linked calendar events, edit name/description)
- Shared components: `MemoryCard`, `EntityChip`, `SearchBar`, `DateRangePicker`

**Backend additions:**
- [src/reflections/memory/api.py](src/reflections/memory/api.py) — extend `POST /memory/search` with filters (entity_ids, date range, kind)
- `PATCH /memory/{id}` for inline edit (re-embeds on content change)

**Test:** Open `/graph` — see entity nodes. Click a person → memories filtered. Click a memory → inline edit → re-search shows updated content.

---

### Phase 3 — Markdown export/import (~2 days)

DB stays canonical. Markdown is interop, not source of truth.

**Files to add:**
- `src/reflections/vault/` — new module
  - `service.py` — `export_to_vault(user_id, target_dir)` and `import_from_vault(user_id, source_dir, dry_run)`
  - Layout written:
    - `<vault>/daily/YYYY-MM-DD.md` — list of memory chunks + calendar events for that day, frontmatter (id, kind, entities as `[[wikilinks]]`)
    - `<vault>/people/<slug>.md`, `<vault>/places/<slug>.md`, `<vault>/events/<slug>.md`
  - `api.py` — `POST /vault/export` returns tarball; `POST /vault/import` accepts folder upload
- UI: `Settings` page with "Export Vault" button

**v1 ships one-way export + manual one-way import.** Live file watcher → v2 (Rust `notify-rs` candidate).

**Test:** Export → see files in vault dir. Open in Obsidian, `[[wikilinks]]` resolve. Edit a file, import → DB row updates and re-embeds.

---

### Phase 4 — Internet egress gating (~3 days)

**Network-level:**
- [docker-compose.yml](docker-compose.yml) — split `api` and `db` onto `internal-net` (`internal: true`)
- Add `egress-proxy` service on `egress-net`, bridged to api via a separate network
- Use **tinyproxy** with a small auth filter, or a thin FastAPI proxy that validates JWT + role before forwarding
- Outbound from api only reachable via `EGRESS_PROXY_URL`

**App-level:**
- New `src/reflections/commons/http_client.py` — `async_internet_get/post(url, ..., user)`:
  1. Checks `user.is_admin` → raises `InternetForbiddenException` otherwise
  2. Routes through `EGRESS_PROXY_URL` with `Authorization: Bearer <admin JWT>`
  3. Logs every outbound URL to `outbound_audit_log` table
- New `outbound_audit_log` table (migration): id, user_id, url, status, ts

**PydanticAI tool:**
- New `internet_search(query)` tool — calls `commons/http_client.async_internet_get` to DuckDuckGo Lite HTML (OSS, no API key)
- Voice/UI: per-turn "internet mode" toggle, surfaced on `/voice` for admins only. Voice command `"go online"` flips it for next turn.

**Verification:**
- Non-admin attempts `internet_search` → 403 + audit log row
- Admin with internet OFF → tool unavailable
- Admin with internet ON → query goes through proxy, audit log row, response returns

---

### Phase 5 — Apple Calendar integration via host bridge (~4 days)

**Why a bridge:** EventKit needs native macOS APIs and prompts the user for Calendar permission via the system Privacy dialog. This can't run inside a Docker container.

**Files to add:**
- `src/reflections/calendar_bridge/` — host process (same pattern as `stt_bridge` / `tts_bridge`)
  - `main.py` — FastAPI on `:9004`
  - Endpoints: `GET /calendars`, `GET /events?from=&to=&calendar_id?=`, `POST /events`, `PATCH /events/{id}`, `DELETE /events/{id}`, `GET /health`
  - Implementation uses `pyobjc-framework-EventKit`. First request triggers the EventKit authorization prompt; the bridge surfaces a clear "not authorized" error if the user denied
  - Optional shared secret header `X-Calendar-Bridge-Secret` so other Mac apps can't hit it
- `src/reflections/calendar/` — module inside main FastAPI app
  - `repository.py` — HTTP client to the bridge (httpx), uses `host.docker.internal:9004`
  - `service.py` — domain logic; normalizes EventKit shapes to our `CalendarEvent` schema
  - `api.py` — `/calendar/calendars`, `/calendar/events` REST routes (auth-required)
  - `schemas.py` — `CalendarEvent { id, calendar_id, title, start, end, all_day, location?, notes?, attendees? }`
- Settings additions: `CALENDAR_BRIDGE_URL` (default `http://host.docker.internal:9004`), `CALENDAR_BRIDGE_SECRET` (optional)
- `Makefile` — `calendar-bridge` target and `calendar-bridge-bg` (mirrors STT/TTS targets); included in `bridges-up`
- `check-calendar-bridge` preflight that warns if EventKit permission not granted
- `pyproject.toml` — add `pyobjc-framework-EventKit` to a new optional dep group `mac` (so the package still installs cleanly on Linux for k8s-portable images)

**PydanticAI tools (voice agent gains calendar awareness):**
- `list_calendar_events(date_range)`, `create_calendar_event(title, start, end, ...)`, `update_calendar_event(id, ...)`
- Date-natural-language parsing: use `python-dateutil` or a small Ollama-backed normalizer for "tomorrow 3pm"

**UI:**
- New `/calendar` page — today + upcoming, quick-create form
- Daily note in `/explore` (and exported markdown) folds in calendar events for that date

**Voice integration:**
- Try voice flows: "what's on my calendar today?", "add a meeting with Sarah tomorrow at 3", "move my 4pm to 5pm"

**Test:** Run `make calendar-bridge` → first call triggers EventKit prompt → grant permission → `GET /calendar/events?from=...` returns real events. Ask via voice "what's on my calendar today?" → assistant lists them. "Schedule X tomorrow at 3" → event appears in Calendar.app.

---

### Phase 6 — MCP server via FastMCP, mounted in FastAPI (~4 days)

**Library:** `fastmcp` (FastAPI-style decorators, supports stdio + SSE/Streamable HTTP; pip install fastmcp).

**Files to add:**
- `pyproject.toml` — add `fastmcp>=2.0`
- `src/reflections/mcp/` — new module
  - `server.py` — defines `mcp = FastMCP("Reflections")`, all `@mcp.tool()` and `@mcp.resource()` functions. Tools call into existing service-layer classes directly (no extra HTTP hop)
  - `app.py` — exports the ASGI HTTP/SSE app via `mcp.http_app()` (or `mcp.sse_app()` depending on FastMCP version)
  - `stdio.py` — thin entry point `python -m reflections.mcp.stdio` that runs FastMCP in stdio mode; intended to be launched by Claude Desktop directly
  - `auth.py` — MCP token validation (Bearer header for HTTP, env var for stdio)
- [src/reflections/api/main.py](src/reflections/api/main.py) — `app.mount("/mcp", mcp_http_app)` so HTTP MCP shares the FastAPI process, auth dependencies, settings, and DB sessions
- New `mcp_tokens` table: id, user_id, name, token_hash, created_at, last_used_at, revoked_at
- `POST /mcp/tokens` endpoint (auth-required) — mints a token, returns it once
- `make mcp-token user=...` Makefile target
- README — Claude Desktop install snippet:
  ```json
  {
    "mcpServers": {
      "reflections": {
        "command": "python",
        "args": ["-m", "reflections.mcp.stdio"],
        "env": {
          "REFLECTIONS_API_URL": "http://localhost:8000",
          "REFLECTIONS_MCP_TOKEN": "<paste token>"
        }
      }
    }
  }
  ```

**Tools (v1 surface):**

Memory:
- `record_memory(content, kind="card"|"chunk", scope="user"|"avatar", entities?: string[])`
- `recall_memory(query, top_k=5, kind?, entity?, date_from?, date_to?)`
- `search_memories(query, filters)`
- `get_today()` — returns today's daily note (memories + calendar events)
- `set_daily_objective(text)`

Entities:
- `list_people()`, `get_person(slug)`, `list_events()`, `get_event(slug)`
- `log_event(name, date, description, people?: string[], place?: string)`
- `link_memory_to_entity(memory_id, entity_slug, relation?)`

Calendar:
- `list_calendar_events(date_range)`
- `create_calendar_event(title, start, end, calendar?, location?, notes?)`
- `update_calendar_event(id, ...)`
- `delete_calendar_event(id)`

Resources:
- `timeline://date/{YYYY-MM-DD}` — daily note as markdown (memories + calendar events for the day)
- `person://{slug}`, `event://{slug}` — entity notes as markdown
- `calendar://today`, `calendar://week` — calendar slices as markdown

**Test:**
- Mint token → wire Claude Desktop → in Claude, call `recall_memory("birthday")` → results
- `curl -N -H "Authorization: Bearer ..." http://localhost:8000/mcp/sse` → SSE stream
- From Claude Desktop: `create_calendar_event("Test", "tomorrow 3pm", "tomorrow 4pm")` → event appears in Calendar.app

---

### Phase 7 — Voice satellite protocol spec (~1 day, docs only)

**Deliverable:** `docs/voice-satellite-protocol.md`

**Spec contents:**
- WS endpoint: `/ws/voice` (same as browser)
- Auth: `Authorization: Bearer <satellite token>` header on WS upgrade
- Audio in: binary frames, PCM16LE mono, 16kHz preferred
- Audio out: `tts_chunk` messages (16kHz PCM16 WAV)
- Control: `hello`, `end`, `cancel`
- Capability negotiation: client advertises `{ has_speaker, has_mic, sample_rate, vad_local }`
- Reference implementations to ship in v2: Raspberry Pi (Python `sounddevice`), ESP32 later

New `satellite_tokens` table (migration scaffolded; mint endpoint deferred to v2).

---

## Files to Delete / Clean

- All of `/Users/once/Development/light-void` — not touched in this plan; user can archive independently
- In `reflections`: nothing to delete (codebase is clean)

## Verification (end-to-end)

1. `make up && make migrate && make bridges-up` — stack starts (STT + TTS + Calendar bridges)
2. Sign up first user → admin badge appears in UI
3. Speak via `/voice` → see transcript, response, audio playback
4. Open `/explore` → search "birthday" → results with entity chips
5. Open `/graph` → entity-memory graph renders; click a person → side panel + memories
6. Inline edit a memory → save → re-search reflects change
7. Settings → Export Vault → tarball → unpack → `tree` shows daily/people/places/events layout, opens cleanly in Obsidian
8. Open `/calendar` → real Apple Calendar events render; create one → it appears in Calendar.app
9. Voice: "what's on my calendar today?" → assistant lists events. "Schedule lunch with Sarah tomorrow at noon" → event created, audit visible
10. Non-admin attempts `internet_search` → 403 + audit log row
11. Admin toggles internet → "what's the release year of Kid A" → response with cited source, audit log row
12. `make mcp-token user=...` → mint token → paste into Claude Desktop config → restart Claude Desktop → `recall_memory("birthday")` returns results
13. `curl -N -H "Authorization: Bearer ..." http://localhost:8000/mcp/sse` → SSE stream
14. From Claude Desktop: `create_calendar_event("Test", "tomorrow 3pm", "tomorrow 4pm")` → event in Calendar.app
15. `pytest` green, `vitest` green

## Open / Deferred Decisions

- **Vault layout (daily + entity notes)** — assumed best practice; sanity-check during Phase 3.
- **react-force-graph-2d vs 3D** — 2D for v1; can lift the light-void Three.js scene in v2 if wanted.
- **Egress proxy choice (tinyproxy vs custom FastAPI)** — tentative tinyproxy; reassess in Phase 4 based on JWT-validation ergonomics.
- **MCP HTTP transport** — using FastMCP's HTTP/SSE app; upgrade to Streamable HTTP when stable.
- **Date-based recall + daily objective** (`docs/next-steps.md` P1) — deferred to after Phase 3; daily-note structure makes this trivial.
- **Calendar permission UX** — first call triggers EventKit prompt; if denied, bridge returns a structured error and the UI surfaces a "grant Calendar permission" panel.
- **Cross-platform calendar** — EventKit is macOS-only. CalDAV / Google Calendar adapters deferred to v2; the `calendar/repository.py` interface is designed to allow swapping backends.

## Rough sizing

~4-5 weeks of focused dev for v1, single-developer pace. Phase 0+1 are sequential blockers; Phases 2, 3, 4, 5, 6 can interleave once 1 is done. Phase 7 is a day of writing.

---

# v2 — Improvements Roadmap (Themed Catalog)

## Context

v1 shipped (Phases 0-8 + artifact extraction + privacy gate + graph search + text input). The system works end-to-end on one Mac with one user, but the user has flagged ~14 areas they want to grow into. This catalog organizes those (plus a few additions I think are worth flagging) into themes, with a short *what / why / effort / risks-and-trade-offs* per item so they can be picked off independently.

Items marked **[+]** were not in the user's original list — I'm adding them because the existing architecture has obvious next-step gaps they fill.

Effort is a rough single-developer estimate: **XS** ≤ 1 day · **S** = 2-3 days · **M** = 1 week · **L** = 2-4 weeks · **XL** = months.

---

## Theme 1 — Model layer (the LLM brain)

### M1. Swap the foundation model (#5)
**What:** Move off the current Ollama default (qwen3 / llama 3.2 class) onto a better-fit foundation model. Candidates: Qwen2.5-7B-Instruct or Qwen2.5-14B (if hardware allows), Llama 3.3 70B Q4 on a Studio, or mlx-lm for Metal-native inference. The serving runtime could change too (Ollama → vLLM, or llama.cpp directly, or mlx-server).
**Why:** Most user-perceived "is this thing smart?" quality lives here. The current model is decent for chat but often weak at structured extraction. Bigger or better-tuned model = fewer entity-extraction mistakes, better tool-use, more coherent recall.
**Effort:** S (model swap) — L (runtime swap to vLLM/mlx).
**Trade-offs:** Bigger models = more RAM, slower latency. mlx-lm is Mac-only (locks you off Linux). vLLM is more performant but assumes Linux + nvidia OR Mac mlx-backed.

### M2. Fine-tune the local model on personal data (#4)
**What:** LoRA fine-tune the chosen foundation model on the user's memory cards + transcripts + style preferences. Already on the v2-deferred list.
**Why:** A 7B that's seen *your* writing style produces more "your-voice" assistant replies and better entity-extraction on your specific domain (e.g., names of bands in your scene).
**Effort:** L. Needs: training pipeline (axolotl or similar), eval set, GPU access (cloud rental or Studio).
**Trade-offs:** Catastrophic forgetting risk; eval-driven loop is essential. Probably worth doing AFTER M1 settles, so you fine-tune on the new base.

### M3. Sub-agents / routing for specialized tasks (#8)
**What:** Split the single PydanticAI agent into specialized agents called from a router. E.g. `memory-recall-agent`, `calendar-agent`, `extraction-agent`, `internet-search-agent`. Or run a small fast model (1B-3B) for routing/extraction and the big model only when reasoning is needed.
**Why:** Smaller per-task prompts = faster, cheaper, easier to test. Extraction does NOT need a 14B model. Routing pattern also lets you swap models per task without touching everything.
**Effort:** M.
**Trade-offs:** More moving parts. Routing failures are confusing to debug. Probably overkill until you feel the single-agent prompt getting bloated.

### M4. Dedicated entity-extraction model (#13)
**What:** Replace the current "ask Ollama in JSON mode" extractor with a purpose-built NER model. Options: GLiNER (zero-shot, ~200MB), spaCy + transformers, a fine-tuned BERT for person/place/event/org. Could run as its own bridge or in the api container.
**Why:** Current extractor uses the chat model — slow (~10s per chunk), expensive, and prone to "hallucinating" entities or missing band names (the recent `org` bug). A dedicated NER model is ~100x faster and more precise.
**Effort:** M.
**Trade-offs:** Two models to maintain. GLiNER quality can be uneven on uncommon proper nouns. Loses the "describe this entity" prose path you get free from the chat model.

---

## Theme 2 — Voice loop (latency + naturalness)

### V1. Newer Whisper model (#1)
**What:** Move from whatever's in `WHISPER_CPP_MODEL` today to one of: `large-v3-turbo` (faster than large, ~95% as accurate), Distil-Whisper (English-only, ~2x faster), or quantized variants (q5_1, q8_0) for the same model.
**Why:** STT is the front of the latency budget. Lowering it from ~1.5s to ~400ms makes the assistant feel "present" rather than "polite phone tree". Better accuracy also reduces downstream "did you mean…" loops.
**Effort:** XS. Mostly env-var change + downloading a model + benchmarking on real voice samples.
**Trade-offs:** Distil-Whisper is English-only. Turbo loses a little accuracy on hard accents. Bigger = slower. Worth an A/B with timing dashboards.

### V2. Custom voice (#3)
**What:** Train (or fine-tune) a Piper voice on the user's chosen speaker. Alternative: switch TTS to Coqui XTTS-v2 or F5-TTS, both of which support zero-shot voice cloning from ~10s of reference audio.
**Why:** A consistent, recognizable voice makes the assistant feel like a character, not a stock TTS. Critical for the "satellite speaker in the kitchen" vision — anonymous TTS gets ignored.
**Effort:** S (XTTS-v2 zero-shot) — L (full Piper training).
**Trade-offs:** XTTS is slower (~real-time on M-series CPU, not faster). Piper-trained voices need ~30min of clean source audio. Both blow up RAM if naively loaded alongside Whisper.

### V3. Animated talking avatar (#7)
**What:** Replace the static avatar image with something that lip-syncs to TTS output. Tier list:
  - **Cheap:** SVG mouth overlay driven by output-level RMS (~1 day, just data-binding the existing `outputLevel`).
  - **Mid:** Live2D model (Live2D Cubism SDK is free for personal use) — feels like a VTuber persona.
  - **Heavy:** Wav2Lip or SadTalker generating real lip-sync video from the avatar's photo + TTS audio (per-utterance, on-GPU, ~5s of compute per reply — kills latency for voice flow).
**Why:** Visual presence makes the agent feel embodied. Big UX lift, especially for the web client.
**Effort:** XS (SVG) — S (Live2D) — L (real lip-sync model).
**Trade-offs:** Real lip-sync conflicts with low-latency voice — you can't start playing audio until the video is generated. Probably ship the cheap SVG version first.

### V4. Rust port of hot paths (#2)
**What:** Already on v2-deferred. Target: VAD + resampling in the voice WS loop (currently a per-frame RMS in Python), the catalog walker, and possibly the entity-link writer. Also: an rmcp-based MCP server replacing FastMCP if you start hitting throughput issues.
**Why:** Per-frame Python adds ~5-10ms to the voice loop. Vault watcher in Python wakes up on every file event; Rust + notify-rs would be cleaner.
**Effort:** L. Mostly the binding plumbing, not the algorithms.
**Trade-offs:** Premature unless you've profiled and found Python is actually the bottleneck. Right now the LLM dominates the latency budget by orders of magnitude. Defer until M1/V1 are done and Python is genuinely the slowest part.

---

## Theme 3 — Memory + Graph (recall and structure)

### G1. Smarter recall methods (#14)
**What:** Layer techniques on top of current pgvector HNSW:
  - **Hybrid BM25 + vector** with Reciprocal Rank Fusion (Postgres has `tsvector`/`ts_rank_cd` built in).
  - **Time-decay boost** — recent memories outrank old ones for ambiguous queries.
  - **Graph-aware recall** — when query mentions an entity, boost memories linked to it.
  - **MMR re-ranking** for diversity (kill 5 near-duplicate chunks).
  - **HyDE** — generate a hypothetical answer first, embed THAT, search for similar memories.
  - **Cross-encoder reranker** (e.g., bge-reranker-base) on the top-50.
**Why:** Pure vector search is the simplest thing that works. Each of these is a known +5-15% recall@k for personal-knowledge corpora. Hybrid + reranker is the cheapest combined win.
**Effort:** S per technique. Bundle 2-3 into an `M`-sized milestone.
**Trade-offs:** Reranker adds ~50ms per query. HyDE adds an extra LLM call. Risk of over-tuning to current eval set without a held-out evaluation.

### G2. Neo4j (or AGE) as the graph store (#6)
**What:** Move the knowledge graph off Postgres tables into a real graph DB. Two paths:
  - **Neo4j container** alongside Postgres. Entities + links live there; memories stay in Postgres with a pointer.
  - **Apache AGE** extension — gives Cypher on top of Postgres, same container.
**Why:** Cypher queries unlock patterns that are painful in SQL: "find people I've met at places I've also been with Sarah", "show me 2-hop neighbors of The Hogs". Better recommendation/recall surface.
**Effort:** M (AGE) — L (Neo4j separation).
**Trade-offs:** Two DBs to back up, sync, migrate. Right now the graph isn't that complex (single user, <10k entities). AGE keeps it in-process and is the lower-risk first step. Re-evaluate when graph-shape questions start showing up in recall failures.

### G3. External data sources (#11)
**What:** Pull in structured external data:
  - **Wikipedia/Wikidata** — auto-enrich entity descriptions ("Talk Talk" → band, formed 1981, members…).
  - **RSS feeds** the user follows — auto-create memory chunks tagged with the source.
  - **Music history** (Last.fm scrobbles, Apple Music exports), **books** (Goodreads), **fitness** (Apple Health).
**Why:** Most of "who am I" is already represented in services. The agent gets dramatically smarter if it has access to your past listening, reading, travel.
**Effort:** S per source. A connector framework is M.
**Trade-offs:** Privacy implications — needs the admin-gate pattern extended. Sources have wildly different shapes; needs a normalization layer.

### G4. Hierarchical / summary-of-summaries memory **[+]**
**What:** When chunks pile up (>10k for a user), generate weekly/monthly/quarterly *summary memories* and retrieve from the summary layer first, then drill into source chunks. Standard "memory hierarchy" pattern from MemGPT-style systems.
**Why:** Vector search degrades when you have lots of similar chunks. A summary-first retrieval keeps results coherent at scale.
**Effort:** M.
**Trade-offs:** Summary quality depends on M1's foundation model. Needs a regen schedule (cron) and storage for the derived rows.

### G5. Encryption at rest for sensitive content **[+]**
**What:** Use `pgcrypto` to encrypt `memory_items.content` (and entity descriptions) for rows flagged `private`. Symmetric key stored in a host keychain (macOS Keychain Access via the bridge pattern), unlocked at api boot.
**Why:** Today the admin-AND-scope gate is at the *API* layer — anyone with DB access bypasses it. Encryption-at-rest is the defense-in-depth layer that matches the existing privacy posture.
**Effort:** M. Migration + service-layer encrypt/decrypt + key-management story.
**Trade-offs:** Searchability — encrypted content can't be `tsvector`-indexed. Backup/restore needs the key. Lose the key, lose the data.

---

## Theme 4 — UX

### U1. Voice-driven CRUD on the graph **[+]**
**What:** Voice commands like "delete that last memory", "merge Sarah Mitchell into Sarah", "rename The Hogs to The Hoggs", "mark this private". Today only ingest and recall work via voice; edits require the web UI.
**Why:** Closes the loop on hands-free use. Currently you record a memory, then have to open the browser to fix typos in the extracted entities.
**Effort:** M. New PydanticAI tools + careful confirmation prompts (irreversible ops).
**Trade-offs:** "Delete that" is dangerous — needs explicit confirmation. Pronoun resolution ("that") needs short-term turn context.

### U2. Proactive surfacing / daily brief **[+]**
**What:** A scheduled job that builds a morning brief: today's calendar events, birthdays from entities with `birthday` attribute, anniversaries of past memories ("3 years ago today you went to Point Reyes with Alex"), pending TODOs. Delivered as a TTS audio file, browser notification, or both.
**Why:** Pulls the assistant from reactive to proactive. The data is already there.
**Effort:** S for the briefing, M if delivery includes push notifications across devices.
**Trade-offs:** Easy to make annoying. Needs opt-in and quiet hours.

### U3. Mobile companion (PWA first, native later) **[+]**
**What:** Make the existing Next.js app a PWA so it installs to phone home screens, then phase 2 a thin native React Native shell with proper background audio and Siri intent integration.
**Why:** Voice agent that requires a laptop is half a voice agent. Phone-first is where most "log this memory" moments happen.
**Effort:** S (PWA manifest + offline shell) — L (native shell with proper iOS audio).
**Trade-offs:** Audio capture on iOS Safari is hostile (no MediaRecorder, weird AudioContext quirks). May force native.

---

## Theme 5 — Sharing + Deployment

### S1. LAN access for household users (#10)
**What:** Expose the api on the local network with multi-tenant guards (we already have per-user isolation). Add: TLS cert (self-signed via mkcert OR a Tailscale cert), mDNS publish (`reflections.local`), proper CORS for the LAN's IP range, signup flow for second users.
**Why:** "Single user on the device they ran `make up` on" is a hard ceiling. LAN access turns it into a family/household tool with near-zero infra.
**Effort:** S. Most heavy lifting (auth, per-user data, MCP tokens) is done.
**Trade-offs:** mDNS is finicky on some routers. Need a UX for the "this is your first signup, you are now the admin" warning per device.

### S2. On-prem dedicated server (#12)
**What:** Move the api + db + bridges off the laptop onto a dedicated Mac Mini / Studio / NUC running 24/7. Voice satellites and mobile clients all point at it.
**Why:** Required for satellites to work (laptop isn't always on). Frees the laptop hardware budget for bigger models. Cleaner backup story.
**Effort:** S (just deploy). Configuration management (versioning the docker-compose stack, secrets) is the real work.
**Trade-offs:** Network dependency for everything. Remote-access story needs Tailscale or similar. Calendar bridge is macOS-only (so server has to be a Mac if you want Apple Calendar — or you accept calendar-only-when-laptop-is-up, or implement CalDAV as the cross-platform path).

### S3. Voice satellites (Pi / wiped speakers) (was v1-deferred)
**What:** Build the satellite implementations against the protocol spec in `docs/voice-satellite-protocol.md`. Reference target: Pi 5 + ReSpeaker 4-mic array. Stretch: flash a Google Home Mini with custom firmware.
**Why:** Without satellites, the system is only available when you're at a laptop. Satellites make it ambient.
**Effort:** L. Hardware procurement + audio pipeline + wake-word + power management.
**Trade-offs:** Wake-word detection on a Pi is power-hungry. Network-dependent — no offline mode in v1.

### S4. Hosted graph + entity-claim flow (#9)
**What:** Big architectural shift. Let an entity (a person in your graph, e.g. "Sarah Mitchell") receive an invite link, claim their node, and add events/memories from their side. Probably a separate hosted instance (`reflections.cloud`) that syncs with the user's local DB.
**Why:** Some events are richer when both participants contribute ("we both remember this trip differently").
**Effort:** XL. New auth boundary, conflict resolution, public/private semantics, hosting infra, GDPR-class privacy controls.
**Trade-offs:** Inverts the "fully local" thesis. Probably wants to live as a separate product layer, not a feature of the local app. Defer until S1+S2 are solid and there's actual demand.

---

## Theme 6 — Ops + observability

### O1. Metrics + tracing **[+]**
**What:** Prometheus metrics (counters per endpoint, histograms for STT/LLM/TTS latency, queue depths) + OpenTelemetry traces stitching `/ws/voice → STT → LLM → TTS`. Grafana dashboard for the laptop.
**Why:** Right now "is it slow?" is purely vibes. Can't tune what you can't measure. Becomes critical once you're trying to budget latency between Whisper / LLM / TTS for V1+V2.
**Effort:** S.
**Trade-offs:** One more container if you self-host Grafana. Prom adds negligible overhead.

### O2. Backup/restore + sync **[+]**
**What:** A `make backup target=...` that produces a `pg_dump` + the vault tarball, signed and optionally encrypted. Restore is the reverse. Stretch: incremental sync to an S3-compatible target (Backblaze B2 is cheap).
**Why:** The current "reset-graph" is reversible only via this. The whole memory-of-your-life thesis falls apart without a real backup.
**Effort:** S.
**Trade-offs:** Encryption keys management (see G5). External target = network dependency for the backup path.

---

## Suggested ordering (if forced)

Not a roadmap — just the dependency-graph view of the catalog above:

1. **Foundations to upgrade first** (cheap, unblocks others): V1 (whisper), M4 (NER), O1 (observability), O2 (backup), G5 (encryption).
2. **Then the model jump**: M1 (foundation model), and only AFTER that M2 (fine-tune).
3. **Then the recall improvements**: G1 (hybrid + reranker), G3 (external sources), G4 (hierarchical summaries).
4. **In parallel as personal taste**: V2 (custom voice), V3 (animated avatar), U1 (voice CRUD), U2 (daily brief).
5. **Sharing**: S1 (LAN) → S2 (on-prem server) → S3 (satellites). S4 (hosted) is a separate product.
6. **Defer until something hurts**: V4 (Rust hot paths), G2 (Neo4j), M3 (sub-agents).

## Verification (when items ship)

Each item that ships should answer one verification question:
- **Model items (M*, V1):** A/B vs current on a 50-prompt held-out set; first-token latency and end-to-end latency dashboards.
- **Recall items (G1, G4):** Recall@5 and Recall@20 on a hand-built eval set of ~30 "ask about something you mentioned 2 weeks ago" queries.
- **Voice items (V2, V3):** MOS-style listening test, latency budget unchanged.
- **Graph items (G2, G3):** Cypher/SQL query latency, dedup quality (no duplicate-name entities after running new sources through).
- **Sharing items (S1, S2):** Second user signs up from another device, posts a memory, sees their own data; admin sees nothing of theirs.
- **Ops items (O1, O2):** Dashboard exists and is non-zero; restore-from-backup produces a working stack.