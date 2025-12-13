# Local Avatar AI (Character.ai-style) — Offline-First Stack + Tooling

## Goals + Non-Goals
- **Goal**: A local “avatar AI” you can chat with (persona + long-term memory), running on your machine, where **no conversation data leaves the computer**.
- **Goal**: Pluggable models (swap LLMs/embeddings/TTS), reproducible setup via **Poetry + Docker Compose**.
- **Non-goal (initially)**: Perfect realtime voice, video avatars, or multi-user scaling. We’ll design for it, but ship an MVP first.

## High-Level Architecture (Local-Only)
**Client UI** (Web or Desktop)  
↕︎ WebSocket/HTTP  
**Backend API** (Python)  
- chat orchestration (prompting, tool calls, memory)  
- auth/local profiles, persona management  
- conversation storage + retrieval  
↕︎  
**Model Runtime** (local inference server)  
- LLM (chat)  
- Embeddings model (memory retrieval)  
↕︎  
**Storage** (local)  
- relational DB for structured state  
- vector DB for long-term memory + semantic search  

Optional (voice):
- **STT**: microphone → text
- **TTS**: text → audio playback

Everything runs locally (LAN-only bindings), and we avoid any telemetry.

## Apple Silicon (macOS) Considerations
Apple Silicon is excellent for local LLMs and realtime audio, but there’s one big deployment constraint:

- **Metal acceleration is not available inside Docker on macOS** in the same way it is on Linux with CUDA.

Practical implication:
- Run **Ollama on the host** (macOS install) to get **Metal** acceleration.
- Keep **FastAPI + Next.js + Postgres** in Docker Compose if you want, but treat “model runtime” as a host service.
- For STT, prefer a path that can use Apple Silicon well:
  - **whisper.cpp** with Metal can be very fast for realtime.
  - **faster-whisper** can still work well, especially with smaller models, but you’ll want to benchmark on your machine.

### STT bridge (current implementation)
We currently use a small **host-run STT bridge** (`reflections.stt_bridge`) so we can:
- run **whisper.cpp** on macOS with Metal
- keep the main API in Docker while still calling STT locally

Flow:
- browser streams PCM16 frames → FastAPI WebSocket
- backend buffers audio
- on `end`, backend calls `STT_BASE_URL=/transcribe` with a WAV file
- backend emits `final_transcript` and then calls Ollama with that transcript

Note: if FastAPI runs in Docker (default), `STT_BASE_URL` should usually be
`http://host.docker.internal:9001` so the container can reach the host bridge.

### TTS bridge (current implementation)
We currently use a small **host-run TTS bridge** (`reflections.tts_bridge`) so we can:
- use macOS **`say`** (fast, no extra model downloads)
- return a **16kHz PCM WAV** that the browser can play via WebAudio

Note: if FastAPI runs in Docker (default), `TTS_BASE_URL` should usually be
`http://host.docker.internal:9002` so the container can reach the host bridge.

Suggested Apple Silicon defaults:
- **LLM (Ollama)**: start with a **7B–8B** instruct model (quality/latency sweet spot).
- **Embeddings**: SentenceTransformers runs fine on CPU; you can explore MPS acceleration later if needed.
- **TTS (Piper)**: generally fast enough for realtime on Apple Silicon.

## Core Components (What We Need)

### 1) Model Inference Runtime (LLM server)
We want an inference layer that can run **quantized local models** efficiently on CPU / Apple Silicon / CUDA.

**Good options:**
- **Ollama** (easy local model management; runs many OSS models; great developer experience)
- **llama.cpp** (max control + best “runs anywhere” story; uses GGUF quantized models)
- **vLLM** (best throughput on modern GPUs; more “server” oriented)

**Recommendation for MVP**:
- Start with **Ollama** (fast iteration), or **llama.cpp** if you want maximum “no magic”.

### Ollama Now, vLLM Later (Planned Migration)
You’re right: **Ollama is great for running models**, but it’s not the best place to do serious fine-tuning/retraining workflows.

**Plan**
- **Phase 1 (MVP)**: Use **Ollama** for local inference (fast setup, good ergonomics).
- **Phase 2 (vLLM)**: Move to **vLLM** for higher-performance serving and better alignment with custom-trained weights.

**Key design choice (so migration is easy)**:
- Build the backend against an **OpenAI-compatible API shape** (chat completions + streaming), and keep “model provider” behind an interface (OllamaProvider / VllmProvider). That way, switching runtime is mostly config.

**What “retraining” looks like in this plan**
- **Persona + behavior** (MVP): done via **system prompts + style rules + memory**, not by fine-tuning.
- **Fine-tuning (v1+)**: run **SFT/LoRA** using separate training tooling, then serve the resulting weights via **vLLM**.
  - Training tools to consider: **Axolotl**, **Hugging Face TRL**, or custom scripts.
  - Output: a new checkpoint (or base + adapter) that **vLLM** can serve.

**Why this works well for voice**
- Ollama gets us to a working voice assistant quickly.
- vLLM later improves latency/throughput and makes custom model variants easier to deploy cleanly.

**Apple Silicon note**
- For best performance on macOS, prefer **host-installed Ollama** (Metal) rather than running Ollama inside Docker.

### 2) Backend API (Python)
The backend is responsible for:
- session + conversation state
- persona system prompt + style constraints
- memory write/read policies (what becomes long-term memory)
- tool execution (optional: filesystem search, calendar, notes, etc.)

**Backend layering convention (required)**
- **`api.py`**: all API logic only
  - FastAPI routers/endpoints, request/response models, status codes
  - translates domain errors → HTTP responses
- **`schemas.py`**: request/response models and internal DTOs
  - keep Pydantic models here when they’re reused across layers
- **`exceptions.py`**: feature-level exception types and constants
  - custom exceptions live here (used by service/flow; mapped by api)
- **`flows.py`** (optional): orchestration across **multiple services**
  - used when an endpoint needs to coordinate more than one service
- **`service.py`**: main business logic
  - orchestrates repositories and external services
  - owns transactions/commits and error handling
  - defines/raises custom exceptions (domain/service layer)
- **`repository.py`**: data access only
  - all DB queries (and/or external API calls)
  - **no error handling**
  - returns raw results (and flushes when appropriate), leaving commit decisions to `service.py`

**App wiring convention (project-wide)**
- Central app assembly lives in `reflections.api.main`:
  - `build_app()` constructs the FastAPI app
  - `configure_routers(app)` registers feature routers
  - `configure_global_exception_handlers(app)` registers global exception handlers
- Shared infrastructure modules:
  - `reflections.core.*` (settings, db, websocket manager)
  - `reflections.commons.*` (logging, exceptions, depends)

**Serialization convention**
- Prefer **Pydantic v2** utilities over manual JSON handling:
  - `model_validate(...)` when parsing incoming payloads
  - `model_dump()` when emitting payloads
- For websockets, prefer `websocket.receive_json()` + `websocket.send_json(model.model_dump())`

**ID convention**
- Use **UUIDv7** (time-ordered) for IDs throughout the backend (via `uuid6.uuid7()`).

**Tools/Libraries:**
- **FastAPI** (HTTP + WebSockets)
- **Pydantic** (schemas)
- **PydanticAI** (agent orchestration with typed tools + structured outputs)
- **SQLAlchemy** (DB access)
- **Alembic** (migrations)
- **httpx** (calling the local model server)

Orchestration approach (recommended):
- **PydanticAI + FastAPI**:
  - define **typed tools** (memory read/write, persona loading, “stop talking”/cancel, etc.)
  - enforce **structured outputs** where needed (e.g., extracting memories, function routing)
  - keep the **model provider swappable** (Ollama now, vLLM later) behind a small adapter

Other orchestration options (later, if needed):
- **Lightweight custom** (still viable if you want minimal dependencies)
- **LangGraph / LangChain** (tool graphs; can add complexity)
- **LlamaIndex** (RAG/memory utilities)

### 3) Memory System (Short-term + Long-term)
To feel character.ai-like, we need multiple memory layers:
- **Short-term memory**: recent message window (prompt context)
- **Long-term memory**: semantic notes about the user + the avatar’s “life” and shared history
- **Persona memory**: immutable-ish character definition + “facts”

**Our memory decisions (v0)**
- **Write policy**: automatic (no “remember this” UX)
  - store **episodic memory cards** (distilled) + **raw recall chunks**
- **Scope**: hybrid
  - **user-global** profile memory
  - **per-avatar** episodic memory
- **Raw chunking**: by turns (groups of **3–6 turns**)
- **Embeddings**: SentenceTransformers **`BAAI/bge-small-en-v1.5`** → **384-dim**
- **Vector search**: **L2-normalized embeddings + inner product** (fast; HNSW + `vector_ip_ops`)

**Memory transparency (UX)**
- Provide endpoints/UI to:
  - inspect stored memories
  - delete memories

**Vector DB (local) options:**
- **Chroma** (simple, local-first; easiest start)
- **Qdrant** (excellent; can run as a local Docker service)
- **Postgres + pgvector** (single database for relational + vector; great for “keep it simple”)
- **SQLite + sqlite-vss / sqlite-vec** (very compact local footprint; more setup)

**When Postgres + pgvector is a good idea**
- You want **one system** to manage (schemas, migrations, backups) for both chat state and memory embeddings.
- Your scale is “local app scale” (personal datasets, thousands to low millions of vectors) and you value simplicity over peak vector performance.
- You want **hybrid queries** (metadata filters + vector similarity) in one place.

**When a dedicated vector DB (Qdrant/Chroma) is better**
- You expect **very large** vector collections, heavy concurrent retrieval, or want more vector-first features out of the box.
- You want to tune vector indexing/perf independently from your relational DB.

**Relational DB options:**
- **SQLite** (best MVP default)
- **Postgres** (if we want multi-process + richer queries; easy in Compose; pairs well with **pgvector**)

### 4) Embeddings Model (for memory retrieval)
We need a small, fast embedding model that runs locally.

**Options:**
- **bge-small / bge-base** (strong general embeddings)
- **nomic-embed-text** (popular; easy via Ollama in some setups)
- **e5-small / e5-base** (solid retrieval embeddings)

**Recommendation for MVP**:
- Use **SentenceTransformers** (CPU-friendly, easy local packaging, keeps embeddings independent of the LLM runtime).

**Suggested SentenceTransformers picks**
- **BAAI/bge-small-en-v1.5** (strong quality/speed default for English)
- **intfloat/e5-small-v2** (solid retrieval embeddings; good speed)

> We can still swap to an Ollama-served embedding model later, but SentenceTransformers is a great “simple + local + reliable” baseline.

### 5) Client UI
You can build:
- **Web UI** (**Next.js** recommended)
- **Desktop UI** (Tauri/Electron) if you want a “native app” feel

MVP UI needs:
- streaming tokens
- persona selection
- memory on/off toggle (and “what did you remember?” inspectability)

**Next.js (recommended)**
- **Why**: excellent UX/tooling, easy realtime UI patterns, and straightforward mic/audio handling in the browser.
- **How it connects**:
  - Next.js serves the UI
  - FastAPI provides:
    - WebSocket endpoints for **audio streaming + partial transcripts + token streaming**
    - REST endpoints for avatar management, history, memory inspection
- **Realtime voice**:
  - Start with **WebSocket audio frames** from the browser (fast MVP).
  - Upgrade to **WebRTC** if you need best-in-class latency/echo handling later.

#### Current WS voice protocol (v0)
- Client → Server:
  - `hello` (with capture `sample_rate`)
  - **binary WS frames**: raw **PCM16LE** mono audio (no JSON wrapper per frame)
  - `end` (finalize + transcribe + respond)
  - `cancel`
  - (legacy) `audio_frame` (base64 PCM16LE) is still supported for back-compat
- Server → Client:
  - `ready`
  - `partial_transcript` (best-effort; when STT is configured we emit “batch partial” transcriptions)
  - `final_transcript` (real STT text when STT is configured, otherwise stub)
  - `assistant_message` (Ollama response; **context retained** by sending full message history via `/api/chat`)
  - `tts_audio` (base64 WAV; optional when TTS configured)
  - `done` (turn complete; session can remain open for next turn)
  - `error` (e.g. `stt_error:*` / `ollama_error:*` / `tts_error:*`)

**Resampling decision (v0)**:
- Browser sends device-rate PCM16LE; backend **standardizes to 16kHz mono PCM16** before STT.

### 6) Safety + Privacy Controls (Local-first)
Even local-only, we want guardrails:
- “Do not store sensitive info” memory filters
- per-avatar memory policies (strict vs permissive)
- data export/delete tools
- local encryption at rest (optional v1)

## Open-Source Model Choices (Chat LLM)
You’ll choose based on your hardware (CPU vs GPU vs Apple Silicon) and desired quality/speed.

## Licensing + Distribution Notes (Important)
- **Models have licenses**: some allow commercial use, some restrict it, and some require attribution. We should pick models whose terms match your intended usage.
- **Weights vs code**: “open-source” sometimes refers to code, while weights are under a separate license—verify both.
- **Local-only does not remove license obligations**: even if nothing leaves the machine, redistribution and usage still follow the model license.

### Strong general chat models (local-friendly)
- **Llama 3.1 / 3.2 Instruct** (Meta; widely supported; great baseline)
- **Qwen2.5 Instruct** (Alibaba; very strong; good multilingual)
- **Mistral / Mixtral Instruct** (Mistral AI; good quality)
- **Gemma 2 Instruct** (Google; solid)
- **Phi-3** (Microsoft; smaller; fast; good for constrained devices)

### What format we’ll use locally
- **GGUF quantized models** (best for llama.cpp; often used with Ollama too)
- Quantization levels: **Q4_K_M** is a common quality/speed sweet spot; Q5/Q6 improves quality if you have RAM/VRAM.

### Practical sizing guidance (very rough)
- **7B–8B**: good “MVP quality” on many machines
- **13B–14B**: noticeably better coherence, needs more memory
- **30B+**: best local quality, but hardware demands rise sharply

> We’ll benchmark 1–2 candidate models on your machine and pick the best quality-per-latency.

## Real-Time Voice (Priority)
To feel “alive”, voice mode needs low latency, **streaming** in both directions, and good turn-taking.

### Voice Loop Architecture (Streaming)
- **Mic capture** (browser/desktop) → 16kHz mono PCM frames (e.g., 20ms chunks)
- **VAD (voice activity detection)** + endpointing:
  - detects speech start/stop
  - enables **barge-in** (user interrupts while TTS is talking)
- **Streaming STT**:
  - produces partial transcripts while user is speaking
  - finalizes when endpoint is detected
- **LLM streaming**:
  - generates tokens as soon as we have enough transcript
  - optionally starts responding before user fully stops (aggressive mode)
- **Streaming TTS**:
  - begins audio output from partial text chunks
  - can be cancelled immediately on barge-in

### Latency Targets (Rules of Thumb)
- **< 300ms**: feels instant (hard)
- **300–800ms**: “fast assistant” (good target for local)
- **> 1.5s**: starts to feel sluggish for voice

To hit good voice latency locally, we generally prefer:
- smaller / quantized models
- streaming everywhere
- short audio frames + fast endpointing

### Transport: How Audio Moves
- **Browser UI**: capture mic with Web APIs, send audio frames via **WebSocket** (simplest) or **WebRTC** (best for realtime media).
- **Desktop UI**: direct device access via Python + `sounddevice` is easiest.

**MVP recommendation**: WebSocket audio frames (fast to ship), then upgrade to WebRTC if needed.

### Speech-to-Text (STT)
- **whisper.cpp** (**recommended on Apple Silicon with Metal**; very fast; portable; supports streaming-style decoding)
- **faster-whisper** (Whisper via CTranslate2; good realtime performance; can run CPU/GPU)
- **sherpa-onnx** (streaming ASR options; often very low-latency on CPU)
- **Vosk / Kaldi** (classic, lightweight; lower accuracy than modern Whisper variants)

**Practical MVP pick**:
- **Apple Silicon**: start with **whisper.cpp + Metal** (host-installed) and a smaller model variant, then benchmark up if needed.
- Otherwise: start with **faster-whisper** using a smaller model (small/medium) tuned for your machine.

### Text-to-Speech (TTS)
- **Piper** (fast, high quality, truly local; great default)
- **Coqui TTS / XTTS-v2** (high quality + voice cloning potential, but heavier)
- **ChatTTS** (optimized for dialogue; often perceived as very natural for conversational back-and-forth)
- **MeloTTS** (lightweight, CPU-friendly, fast inference; good “edge realtime” profile)
- **Fish Speech (v1.5)** (strong multilingual quality; evaluate latency/footprint)
- **CosyVoice2 (0.5B)** (focuses on ultra-low-latency streaming; promising for “instant speech”)
- **OpenVoice v2** (voice cloning + fine-grained control + cross-lingual cloning; evaluate latency/complexity)

**Real-time note**: We want **chunked/streamed synthesis** (or rapid small utterances) so audio starts quickly.

**How I’d think about your list (voice-first)**
- **If we want ultra-low latency first** (best “realtime feel”):
  - prioritize **CosyVoice2 (0.5B)** (streaming-first) or **MeloTTS** (lightweight)
- **If we want best-in-class voice cloning** (but heavier + more complexity):
  - prioritize **XTTS-v2** or **OpenVoice v2**
- **If we want “chatty” conversational cadence**:
  - **ChatTTS** can be a strong fit, but we still need to validate true streaming + interruption behavior
- **If multilingual quality is a top priority**:
  - **Fish Speech** is worth a serious benchmark

**Apple Silicon practical recommendation**
- For the MVP, pick **one low-latency TTS** (start speaking fast, handle barge-in well), then add cloning later.
- Regardless of which model we choose, we should implement the same backend TTS contract:
  - start audio quickly from partial text
  - support immediate cancel on barge-in
  - cache voices/models locally

**Licensing note**
- For each TTS model above, we should confirm the **weights + code license** aligns with your intended usage (personal vs commercial) before we bake it into the default stack.

### Audio I/O
- **sounddevice / pyaudio** (mic capture for desktop mode)
- **silero-vad** or **webrtcvad** (voice activity detection)
- Optional: noise suppression / echo control (especially for speakers + mic)

### Turn-taking + Barge-in (Must-have for “Avatar” Feel)
- **Barge-in**: if user starts speaking, immediately stop TTS playback and cancel the current generation.
- **Endpointing**: tune VAD thresholds + a short “silence timeout” to avoid long awkward gaps.
- **Echo management**:
  - browser mode: rely on built-in acoustic echo cancellation where possible
  - add “push-to-talk” option as a reliable fallback

### Recommended “Voice-First MVP” Stack
- **STT (Apple Silicon)**: **whisper.cpp + Metal**
- **VAD**: `silero-vad`
- **LLM**: a smaller instruct model for low-latency (e.g., **Phi-3** class / **Qwen** small sizes) served by Ollama/llama.cpp
- **TTS**: **Piper**
- **Backend**: FastAPI + WebSockets (audio frames + streaming text + streaming audio)
- **Memory**: keep, but make it non-blocking (store/retrieve async so voice latency stays tight)

## Docker Compose Topology (Typical Local Setup)
We can run a small set of services:
- **api**: FastAPI backend
- **ui**: **Next.js** frontend
- **model**: **host-installed Ollama** (recommended on Apple Silicon for Metal) or a container (CPU-only)
- **vector-db**: Chroma or Qdrant
- **db**: SQLite (in api volume) or **Postgres 18 + pgvector** container

Key privacy defaults:
- bind to **127.0.0.1** only (not `0.0.0.0`) unless you explicitly want LAN access
- disable logs that persist full prompts unless you opt in

### Postgres 18 note (Docker volumes)
Postgres 18+ Docker images expect the data volume mounted at **`/var/lib/postgresql`**
(not `/var/lib/postgresql/data`) so data lives in a major-version subdirectory.
This makes future major upgrades safer.

For dev, if you upgrade PG major versions and the DB fails to start, wiping the
volume is the fastest fix:
- `docker compose down -v`

## MVP Feature Set (Suggested)
- Single avatar with:
  - persona prompt (name, style, boundaries)
  - streaming chat
  - short-term windowing + token budgeting
  - long-term memory store + retrieval (vector search)
  - “memory inspector” (show what got stored and why)
- Local persistence:
  - conversations saved to SQLite/Postgres
  - vector store persisted on disk

## v1 Enhancements (Character.ai-like)
- Multiple avatars + “world” settings
- Per-user profile + personalization (and memory permissions)
- Emotion/state tracking (explicit state machine)
- Tool calling (notes, local files, calendar) with allowlists
- Voice mode (STT + TTS)
- Fine-tuning or LoRA adapters (optional; more work)

## “No Data Leaves” Checklist
- **No external API calls** for inference, embeddings, STT, or TTS
- **No remote telemetry** from UI or backend
- **Explicit network egress block** (optional): run containers with no outbound network where feasible
- **Local-only bind**: `127.0.0.1` ports
- **Data controls**: export/delete conversations + memories

## Suggested Next Step (Decision Points)
Before coding, we should decide:
- **Runtime (now / later)**: Ollama now, vLLM later
- **LLM**: pick 1–2 candidates (e.g., Llama 3.1 8B Instruct vs Qwen2.5 7B Instruct)
- **Vector DB**: Chroma (simplest) vs Qdrant (more “production-like”)
- **UI**: **Next.js** (chosen) vs desktop (later)
- **Voice** (now priority):
  - browser vs desktop first
  - WebSocket vs WebRTC transport
  - STT choice (faster-whisper vs whisper.cpp vs sherpa-onnx)
  - TTS choice (Piper voice selection)

## Training / “Retraining” Track (v1+)
If we want the avatar to truly “feel unique” beyond prompting + memory, we’ll plan for a training pipeline that still keeps data local.

### What we can do without retraining (recommended first)
- Strong persona prompt + examples (few-shot)
- Memory policies (what gets remembered; what gets forgotten)
- Retrieval (bring relevant memories into context)
- Tool usage (notes, calendar, local docs) with strict allowlists

### When to fine-tune (SFT/LoRA)
Fine-tuning is worth it when we want:
- consistent “voice” / tone without large prompts
- domain style (roleplay, specific dialog style)
- better adherence to structured outputs/tools

### Local-first training tooling
- **Axolotl**: common for LoRA/SFT pipelines
- **TRL**: HF training recipes for SFT/DPO-style workflows
- Dataset format: JSONL conversations + metadata (persona, style tags)

### Serving fine-tuned models
- **Ollama**: best for running common models quickly; adapters/FT workflows are not the primary path.
- **vLLM**: preferred for serving custom checkpoints/adapters with strong performance.


