"""MCP tools that wrap the existing memory service."""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Literal
from uuid import UUID

from pydantic import Field

from reflections.core.db import database_manager
from reflections.mcp.auth import current_user_id, has_scope
from reflections.memory.schemas import Turn
from reflections.memory.service import MemoryService

SCOPE_READ_PRIVATE = "mcp:read_private"

_memory_service: MemoryService | None = None


def _service() -> MemoryService:
    global _memory_service
    if _memory_service is None:
        _memory_service = MemoryService.create()
    return _memory_service


def register(mcp) -> None:  # type: ignore[no-untyped-def]
    @mcp.tool
    async def record_memory(
        content: Annotated[str, Field(min_length=1, max_length=8000)],
        kind: Literal["card", "chunk"] = "card",
        avatar_id: str | None = None,
    ) -> dict:
        """
        Save a memory for the authenticated user.

        - `kind="card"` for distilled facts or preferences worth keeping
          long-term (e.g. "I like my coffee black"). These are the highest-
          signal items returned by recall.
        - `kind="chunk"` for raw conversation snippets or longer narrative
          fragments. These are good for grounding a response in context.

        If `avatar_id` is provided, the memory is scoped to that avatar (and
        will be returned in avatar-scoped searches). Otherwise it's user-global.
        """
        user_id = current_user_id()
        avatar_uuid = UUID(avatar_id) if avatar_id else None
        # The memory service's ingest pipeline operates on turns; we shape a
        # single-turn input so the existing chunking/extraction code can run
        # uniformly for `chunk` content. For `card`, we bypass the heuristic
        # by writing through the repository.
        svc = _service()
        await database_manager.initialize()
        async with database_manager.session() as session:
            if kind == "card":
                emb = svc.embed_text(content)
                scope = "avatar" if avatar_uuid else "user"
                mem_id = await svc.repository.insert_item(
                    session,
                    user_id=user_id,
                    avatar_id=avatar_uuid,
                    scope=scope,
                    kind="card",
                    content=content,
                    embedding=emb,
                )
                await session.commit()
                # Run extraction best-effort against the card text too.
                if svc.entities is not None:
                    try:
                        await svc.entities.upsert_and_link(
                            session,
                            user_id=user_id,
                            memory_item_ids=[mem_id],
                            chunk_text=content,
                        )
                        await session.commit()
                    except Exception:
                        await session.rollback()
                return {"id": str(mem_id), "kind": "card"}

            stored_ids, _cards, _chunks = await svc.ingest_episodic(
                session,
                user_id=user_id,
                avatar_id=avatar_uuid,
                turns=[Turn(role="user", content=content)],
                chunk_turn_window=2,
            )
            return {"ids": [str(i) for i in stored_ids], "kind": "chunk"}

    @mcp.tool
    async def recall_memory(
        query: Annotated[str, Field(min_length=1, max_length=2000)],
        top_k: Annotated[int, Field(ge=1, le=50)] = 5,
        avatar_id: str | None = None,
        kind: Literal["card", "chunk", "any"] = "any",
    ) -> dict:
        """
        Search memories by semantic similarity to `query`.

        Returns the most relevant items as a list of {id, kind, content,
        created_at}. Use `kind="card"` to favor distilled facts; `kind="any"`
        searches both cards and chunks.
        """
        user_id = current_user_id()
        include_private = has_scope(SCOPE_READ_PRIVATE)
        avatar_uuid = UUID(avatar_id) if avatar_id else None
        svc = _service()
        await database_manager.initialize()
        async with database_manager.session() as session:
            rows = await svc.search(
                session,
                user_id=user_id,
                avatar_id=avatar_uuid,
                query=query,
                top_k=top_k,
                include_user_scope=True,
                include_avatar_scope=avatar_uuid is not None,
                include_cards=kind in ("card", "any"),
                include_chunks=kind in ("chunk", "any"),
                include_private=include_private,
            )
        return {
            "items": [
                {
                    "id": str(r.id),
                    "kind": r.kind,
                    "scope": r.scope,
                    "content": r.content,
                    "created_at": _iso(r.created_at),
                }
                for r in rows
            ],
            "include_private": include_private,
        }

    @mcp.tool
    async def inspect_memories(
        limit: Annotated[int, Field(ge=1, le=200)] = 50,
        offset: Annotated[int, Field(ge=0, le=10_000)] = 0,
        kind: Literal["card", "chunk", "any"] = "any",
        avatar_id: str | None = None,
    ) -> dict:
        """
        List memories by recency (newest first). For browsing rather than
        searching; use `recall_memory` for relevance-ranked results.

        Honors the caller's `mcp:read_private` scope — tokens without
        it never see chunks flagged `private`.
        """
        user_id = current_user_id()
        include_private = has_scope(SCOPE_READ_PRIVATE)
        avatar_uuid = UUID(avatar_id) if avatar_id else None
        svc = _service()
        await database_manager.initialize()
        async with database_manager.session() as session:
            rows = await svc.inspect(
                session,
                user_id=user_id,
                avatar_id=avatar_uuid,
                limit=limit,
                offset=offset,
                include_user_scope=True,
                include_avatar_scope=avatar_uuid is not None,
                include_cards=kind in ("card", "any"),
                include_chunks=kind in ("chunk", "any"),
                include_private=include_private,
            )
        return {
            "items": [
                {
                    "id": str(r.id),
                    "kind": r.kind,
                    "scope": r.scope,
                    "content": r.content,
                    "created_at": _iso(r.created_at),
                }
                for r in rows
            ]
        }

    @mcp.tool
    async def delete_memory(memory_id: str) -> dict:
        """Permanently delete a memory by id. Returns the number deleted (0 or 1)."""
        user_id = current_user_id()
        svc = _service()
        await database_manager.initialize()
        async with database_manager.session() as session:
            deleted = await svc.delete(
                session, user_id=user_id, ids=[UUID(memory_id)]
            )
        return {"deleted": deleted}


def _iso(d: datetime) -> str:
    return d.isoformat()
