from __future__ import annotations

from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, Field

EntityKind = Literal["person", "place", "event", "topic"]


class Entity(BaseModel):
    id: UUID
    user_id: UUID
    kind: EntityKind
    name: str
    slug: str
    description: str | None = None
    attributes: dict[str, Any] | None = None
    created_at: datetime
    updated_at: datetime


class CreateEntityRequest(BaseModel):
    kind: EntityKind
    name: str = Field(min_length=1, max_length=200)
    description: str | None = None
    attributes: dict[str, Any] | None = None


class UpdateEntityRequest(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    description: str | None = None
    attributes: dict[str, Any] | None = None


class MergeEntitiesRequest(BaseModel):
    # Merge `from_id` into the entity in the URL path; links repoint and the
    # source entity is deleted.
    from_id: UUID


class EntityListResponse(BaseModel):
    items: list[Entity]


class EntityMemoriesResponse(BaseModel):
    memory_ids: list[UUID]


# ---- LLM extraction (used internally by memory ingest) ----


class ExtractedEntity(BaseModel):
    kind: EntityKind
    name: str
    description: str | None = None


class ExtractedEntities(BaseModel):
    people: list[str] = Field(default_factory=list)
    places: list[str] = Field(default_factory=list)
    events: list[str] = Field(default_factory=list)
    topics: list[str] = Field(default_factory=list)

    def as_entities(self) -> list[ExtractedEntity]:
        out: list[ExtractedEntity] = []
        for n in self.people:
            out.append(ExtractedEntity(kind="person", name=n))
        for n in self.places:
            out.append(ExtractedEntity(kind="place", name=n))
        for n in self.events:
            out.append(ExtractedEntity(kind="event", name=n))
        for n in self.topics:
            out.append(ExtractedEntity(kind="topic", name=n))
        return out
