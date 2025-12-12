---
description: "Backend layering rule: api.py (HTTP), service.py (business logic), repository.py (data access), plus optional flows.py and shared schemas/exceptions"
globs:
  - "src/reflections/**"
alwaysApply: false
---

## Required backend layering (enforced)
When implementing backend functionality under `src/reflections/**`, use these layers:

### `schemas.py` (schemas/DTOs)
- Owns:
  - Pydantic request/response models
  - DTOs reused across layers

### Serialization (Pydantic-first)
- Prefer Pydantic v2 helpers over manual JSON:
  - parse with `model_validate(...)` / `TypeAdapter(...).validate_python(...)`
  - emit with `model_dump()`
- For websockets:
  - prefer `receive_json()` / `send_json(model.model_dump())`
  - avoid `json.dumps` / `json.loads` in feature code unless strictly necessary

### IDs
- Use UUIDv7 for identifiers:
  - prefer `reflections.commons.ids.uuid7_uuid()` (wraps `uuid6.uuid7()`), store in Postgres as native `uuid`.
  - use `uuid7_str()` only for display/logging.

### `exceptions.py` (custom exceptions/constants)
- Owns:
  - feature-level custom exception types and constants
- Used by:
  - `service.py` / `flows.py` (raise)
  - `api.py` (map to HTTP responses)

### `api.py` (HTTP layer)
- Owns:
  - FastAPI routers/endpoints
  - request/response schemas
  - status codes and HTTP-specific error mapping
- Must not:
  - contain business logic beyond simple validation/translation
  - access the database directly

### `flows.py` (optional orchestration layer)
- Use only when:
  - an endpoint needs to coordinate **more than one service**
- Owns:
  - multi-service orchestration and cross-service workflow logic
- Must not:
  - access repositories directly (call services instead)

### `service.py` (business logic layer)
- Owns:
  - orchestration across repositories, models, and providers
  - error handling
  - transaction/commit decisions (and rollbacks)
  - custom exceptions (domain/service exceptions)
- Must not:
  - contain raw SQL/query construction (delegate to repositories)

### `repository.py` (data access layer)
- Owns:
  - database access (queries) and/or external API calls
  - returning results + flushing as needed
- Must:
  - avoid error handling (let exceptions bubble)
  - avoid commits (service layer commits)

## Practical layout pattern
For a feature `foo`:
- `src/reflections/foo/api.py`
- `src/reflections/foo/schemas.py`
- `src/reflections/foo/exceptions.py`
- `src/reflections/foo/flows.py` (optional)
- `src/reflections/foo/service.py`
- `src/reflections/foo/repository.py`

Keep routers thin, services testable, and repositories dumb.


