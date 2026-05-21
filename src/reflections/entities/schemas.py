from __future__ import annotations

from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, Field

EntityKind = Literal["person", "place", "event", "topic"]


# Names the extractor must never produce as entities. We post-filter on these
# because small local models (Llama 3.2 3B class) frequently leak pronouns
# even when the system prompt forbids them. Match is case-insensitive on the
# stripped name.
_PRONOUN_BLOCKLIST: frozenset[str] = frozenset(
    {
        # Subject
        "i", "you", "he", "she", "it", "we", "they",
        # Object
        "me", "him", "her", "us", "them",
        # Possessive
        "my", "mine", "your", "yours", "his", "hers", "its",
        "our", "ours", "their", "theirs",
        # Reflexive
        "myself", "yourself", "himself", "herself", "itself",
        "ourselves", "yourselves", "themselves",
        # Demonstrative / generic non-referents seen in practice
        "this", "that", "these", "those", "someone", "somebody",
        "anyone", "anybody", "everyone", "everybody",
        "nobody", "no one", "none",
        # Generic stand-ins
        "user", "assistant", "person", "people", "thing", "things",
    }
)


def _is_garbage_name(raw: str) -> bool:
    """Reject pronouns, very short names, and empty strings before insert."""
    n = raw.strip()
    if len(n) < 2:
        return True
    if n.lower() in _PRONOUN_BLOCKLIST:
        return True
    return False


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
        seen: set[tuple[str, str]] = set()
        for kind, names in (
            ("person", self.people),
            ("place", self.places),
            ("event", self.events),
            ("topic", self.topics),
        ):
            for raw in names:
                if _is_garbage_name(raw):
                    continue
                name = raw.strip()
                key = (kind, name.lower())
                if key in seen:
                    continue
                seen.add(key)
                out.append(ExtractedEntity(kind=kind, name=name))  # type: ignore[arg-type]
        return out
