"""MCP tools that wrap the entities service."""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Literal
from uuid import UUID

from pydantic import Field

from reflections.core.db import database_manager
from reflections.entities.service import EntitiesService
from reflections.mcp.auth import current_user_id

EntityKindLiteral = Literal["person", "place", "event", "topic"]

_entities_service: EntitiesService | None = None


def _service() -> EntitiesService:
    global _entities_service
    if _entities_service is None:
        _entities_service = EntitiesService.create()
    return _entities_service


def register(mcp) -> None:  # type: ignore[no-untyped-def]
    @mcp.tool
    async def list_entities(
        kind: EntityKindLiteral | None = None,
        limit: Annotated[int, Field(ge=1, le=500)] = 100,
        offset: Annotated[int, Field(ge=0, le=10_000)] = 0,
    ) -> dict:
        """
        List entities (people, places, events, topics) belonging to the
        authenticated user. Filter by `kind` to narrow.
        """
        user_id = current_user_id()
        await database_manager.initialize()
        async with database_manager.session() as session:
            rows = await _service().list_for_user(
                session,
                user_id=user_id,
                kind=kind,
                limit=limit,
                offset=offset,
            )
        return {"items": [_entity_dict(r) for r in rows]}

    @mcp.tool
    async def get_entity(entity_id: str) -> dict:
        """Fetch a single entity by id."""
        user_id = current_user_id()
        await database_manager.initialize()
        async with database_manager.session() as session:
            row = await _service().get(
                session, user_id=user_id, entity_id=UUID(entity_id)
            )
        return _entity_dict(row)

    @mcp.tool
    async def add_entity(
        kind: EntityKindLiteral,
        name: Annotated[str, Field(min_length=1, max_length=200)],
        description: str | None = None,
    ) -> dict:
        """
        Create or upsert an entity. Idempotent by (user, kind, slug) where slug
        is derived from `name` — calling with the same name returns the
        existing entity, optionally updating its description.
        """
        user_id = current_user_id()
        await database_manager.initialize()
        async with database_manager.session() as session:
            row = await _service().add(
                session,
                user_id=user_id,
                kind=kind,
                name=name,
                description=description,
            )
        return _entity_dict(row)

    @mcp.tool
    async def update_entity(
        entity_id: str,
        name: str | None = None,
        description: str | None = None,
    ) -> dict:
        """Update name or description of an entity."""
        user_id = current_user_id()
        await database_manager.initialize()
        async with database_manager.session() as session:
            row = await _service().update(
                session,
                user_id=user_id,
                entity_id=UUID(entity_id),
                name=name,
                description=description,
            )
        return _entity_dict(row)

    @mcp.tool
    async def delete_entity(entity_id: str) -> dict:
        """Delete an entity. Also removes all memory_entity_links pointing to it."""
        user_id = current_user_id()
        await database_manager.initialize()
        async with database_manager.session() as session:
            await _service().delete(
                session, user_id=user_id, entity_id=UUID(entity_id)
            )
        return {"deleted": True}

    @mcp.tool
    async def merge_entities(from_id: str, into_id: str) -> dict:
        """
        Merge two entities of the same kind (e.g. "Sarah" and "Sarah K"). All
        memory links from `from_id` are repointed to `into_id` and `from_id`
        is deleted.
        """
        user_id = current_user_id()
        await database_manager.initialize()
        async with database_manager.session() as session:
            await _service().merge_into(
                session,
                user_id=user_id,
                target_id=UUID(into_id),
                from_id=UUID(from_id),
            )
        return {"merged": True}

    @mcp.tool
    async def list_entity_memories(
        entity_id: str,
        limit: Annotated[int, Field(ge=1, le=500)] = 100,
    ) -> dict:
        """List memory ids that link to a given entity."""
        user_id = current_user_id()
        await database_manager.initialize()
        async with database_manager.session() as session:
            ids = await _service().list_memories_for(
                session,
                user_id=user_id,
                entity_id=UUID(entity_id),
                limit=limit,
            )
        return {"memory_ids": [str(i) for i in ids]}

    @mcp.tool
    async def link_memory_to_entity(
        memory_id: str, entity_id: str, relation: str = ""
    ) -> dict:
        """
        Idempotently link a memory to an entity, optionally with a relation
        label (e.g. "attended", "lived_at"). Repeats are no-ops.
        """
        user_id = current_user_id()
        await database_manager.initialize()
        async with database_manager.session() as session:
            # Verify the entity belongs to the user first.
            await _service().get(
                session, user_id=user_id, entity_id=UUID(entity_id)
            )
            await _service().repo.insert_link(
                session,
                memory_item_id=UUID(memory_id),
                entity_id=UUID(entity_id),
                relation=relation,
            )
            await session.commit()
        return {"linked": True}


def _entity_dict(row) -> dict:  # type: ignore[no-untyped-def]
    return {
        "id": str(row.id),
        "kind": row.kind,
        "name": row.name,
        "slug": row.slug,
        "description": row.description,
        "attributes": row.attributes,
        "created_at": _iso(row.created_at),
        "updated_at": _iso(row.updated_at),
    }


def _iso(d: datetime) -> str:
    return d.isoformat()
