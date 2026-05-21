from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field

from reflections.entities.schemas import EntityKind

Role = Literal["user", "assistant", "system"]


class Turn(BaseModel):
    role: Role
    content: str


MemoryScope = Literal["user", "avatar"]
MemoryKind = Literal["card", "chunk"]


class LinkedEntity(BaseModel):
    """Compact entity reference attached to a memory in search/inspect results."""

    id: UUID
    kind: EntityKind
    name: str
    slug: str


class MemoryItem(BaseModel):
    id: UUID
    user_id: UUID
    avatar_id: UUID | None = None
    scope: MemoryScope
    kind: MemoryKind
    content: str
    created_at: datetime
    linked_entities: list[LinkedEntity] = Field(default_factory=list)


class IngestMemoryRequest(BaseModel):
    user_id: UUID
    avatar_id: UUID | None = None
    turns: list[Turn] = Field(min_length=1)
    # raw-chunk sizing by turns (decision #4)
    chunk_turn_window: int = Field(default=6, ge=2, le=20)


class IngestMemoryResponse(BaseModel):
    stored_ids: list[UUID]
    stored_cards: int
    stored_chunks: int


class SearchMemoryRequest(BaseModel):
    user_id: UUID
    avatar_id: UUID | None = None
    query: str = Field(min_length=1)
    top_k: int = Field(default=10, ge=1, le=50)
    include_user_scope: bool = True
    include_avatar_scope: bool = True
    include_cards: bool = True
    include_chunks: bool = True
    # Optional filters added in Phase 2 (web UI / explore page).
    entity_ids: list[UUID] | None = None
    date_from: datetime | None = None
    date_to: datetime | None = None


class SearchMemoryResponse(BaseModel):
    items: list[MemoryItem]


class InspectMemoryRequest(BaseModel):
    user_id: UUID
    avatar_id: UUID | None = None
    limit: int = Field(default=50, ge=1, le=200)
    offset: int = Field(default=0, ge=0, le=10_000)
    include_user_scope: bool = True
    include_avatar_scope: bool = True
    include_cards: bool = True
    include_chunks: bool = True


class InspectMemoryResponse(BaseModel):
    items: list[MemoryItem]


class DeleteMemoryRequest(BaseModel):
    user_id: UUID
    ids: list[UUID] = Field(min_length=1)


class DeleteMemoryResponse(BaseModel):
    deleted_count: int


class PatchMemoryRequest(BaseModel):
    """Inline edit of a memory's content. Re-embeds on save."""

    content: str = Field(min_length=1, max_length=8000)


# ---- Graph view ----


class GraphNode(BaseModel):
    """One node in the knowledge-graph view.

    `id` is prefixed (`memory:<uuid>` or `entity:<uuid>`) so source/target in
    edges are unambiguous when entities and memories share UUID namespaces.
    """

    id: str
    kind: str  # memory_card | memory_chunk | entity_person | entity_place | ...
    label: str


class GraphEdge(BaseModel):
    source: str  # always memory:<uuid> for now
    target: str  # always entity:<uuid> for now
    relation: str = ""


class GraphResponse(BaseModel):
    nodes: list[GraphNode]
    edges: list[GraphEdge]
