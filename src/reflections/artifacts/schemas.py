from __future__ import annotations

from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, Field

ArtifactKind = Literal["pdf", "image", "audio", "video", "other"]
CatalogState = Literal[
    "catalogued", "extracting", "extracted", "stale", "failed"
]


class Volume(BaseModel):
    id: UUID
    user_id: UUID
    label: str
    volume_uuid: str | None = None
    fingerprint: str | None = None
    # First-hint mount path for the current host; when unmounted, this
    # is the last-known path. UI uses it for an "expected at …" line.
    mount_path: str | None = None
    online: bool = False
    created_at: datetime
    last_seen_at: datetime | None = None


class RegisterVolumeRequest(BaseModel):
    # Absolute path on the host. The catalog bridge resolves it,
    # reads/creates the marker, and returns identity.
    mount_path: str = Field(min_length=1)
    label: str | None = None


class Artifact(BaseModel):
    id: UUID
    user_id: UUID
    volume_id: UUID
    relative_path: str
    kind: ArtifactKind
    mime: str | None = None
    size_bytes: int
    mtime: datetime
    sha256: str | None = None
    attributes: dict[str, Any] | None = None
    catalog_state: CatalogState
    error: str | None = None
    extracted_at: datetime | None = None
    created_at: datetime
    updated_at: datetime


class ArtifactPage(BaseModel):
    items: list[Artifact]
    limit: int
    offset: int


class WalkRequest(BaseModel):
    volume_id: UUID
    subpath: str = ""
    # Per-request page size. The api iterates internally so this is
    # mostly an implementation knob, not a user knob.
    max_entries: int = Field(default=5000, ge=1, le=20000)


class WalkResult(BaseModel):
    volume_id: UUID
    files_seen: int
    files_added: int
    files_updated: int
    files_unchanged: int
    pages_fetched: int
    started_at: datetime
    finished_at: datetime


class VolumeListResponse(BaseModel):
    items: list[Volume]
