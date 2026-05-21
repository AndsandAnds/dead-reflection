from __future__ import annotations

from datetime import datetime
from functools import lru_cache
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query  # type: ignore[import-not-found]
from sqlalchemy.ext.asyncio import AsyncSession  # type: ignore[import-not-found]
from starlette import status  # type: ignore[import-not-found]

from reflections.auth.depends import current_user_required
from reflections.commons.depends import database_session
from reflections.memory.exceptions import (
    MemoryServiceException,
    MemoryUnprocessableException,
)
from reflections.memory.repository import LinkedEntityRow, MemoryRow
from reflections.memory.schemas import (
    DeleteMemoryRequest,
    DeleteMemoryResponse,
    GraphEdge,
    GraphNode,
    GraphResponse,
    IngestMemoryRequest,
    IngestMemoryResponse,
    InspectMemoryRequest,
    InspectMemoryResponse,
    LinkedEntity,
    MemoryItem,
    PatchMemoryRequest,
    SearchMemoryRequest,
    SearchMemoryResponse,
)
from reflections.memory.service import MemoryService

router = APIRouter(prefix="/memory", tags=["memory"])


@lru_cache
def get_memory_service() -> MemoryService:
    return MemoryService.create()


def _to_linked(rows: list[LinkedEntityRow]) -> list[LinkedEntity]:
    return [
        LinkedEntity(id=r.id, kind=r.kind, name=r.name, slug=r.slug)  # type: ignore[arg-type]
        for r in rows
    ]


def _to_item(r: MemoryRow, linked: list[LinkedEntityRow] | None = None) -> MemoryItem:
    return MemoryItem(
        id=r.id,
        user_id=r.user_id,
        avatar_id=r.avatar_id,
        scope=r.scope,
        kind=r.kind,
        content=r.content,
        created_at=r.created_at,
        linked_entities=_to_linked(linked or []),
    )


async def _attach_linked(
    svc: MemoryService,
    session: AsyncSession,
    user_id: UUID,
    rows: list[MemoryRow],
) -> list[MemoryItem]:
    if not rows:
        return []
    by_id = await svc.get_linked_entities(
        session, user_id=user_id, memory_ids=[r.id for r in rows]
    )
    return [_to_item(r, by_id.get(r.id, [])) for r in rows]


@router.post("/ingest", response_model=IngestMemoryResponse)
async def ingest_memory(
    req: IngestMemoryRequest,
    session: Annotated[AsyncSession, Depends(database_session)],
    svc: Annotated[MemoryService, Depends(get_memory_service)],
    user=Depends(current_user_required),
) -> IngestMemoryResponse:
    # Enforce: you can only write to your own memory.
    if req.user_id != user.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Cannot write memory for another user",
        )
    stored_ids, cards, chunks = await svc.ingest_episodic(
        session,
        user_id=user.id,
        avatar_id=req.avatar_id,
        turns=req.turns,
        chunk_turn_window=req.chunk_turn_window,
    )
    return IngestMemoryResponse(
        stored_ids=stored_ids, stored_cards=cards, stored_chunks=chunks
    )


@router.post("/search", response_model=SearchMemoryResponse)
async def search_memory(
    req: SearchMemoryRequest,
    session: Annotated[AsyncSession, Depends(database_session)],
    svc: Annotated[MemoryService, Depends(get_memory_service)],
    user=Depends(current_user_required),
) -> SearchMemoryResponse:
    if req.user_id != user.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Cannot search memory for another user",
        )
    rows = await svc.search(
        session,
        user_id=user.id,
        avatar_id=req.avatar_id,
        query=req.query,
        top_k=req.top_k,
        include_user_scope=req.include_user_scope,
        include_avatar_scope=req.include_avatar_scope,
        include_cards=req.include_cards,
        include_chunks=req.include_chunks,
        entity_ids=req.entity_ids,
        date_from=req.date_from,
        date_to=req.date_to,
    )
    items = await _attach_linked(svc, session, user.id, rows)
    return SearchMemoryResponse(items=items)


@router.post("/inspect", response_model=InspectMemoryResponse)
async def inspect_memory(
    req: InspectMemoryRequest,
    session: Annotated[AsyncSession, Depends(database_session)],
    svc: Annotated[MemoryService, Depends(get_memory_service)],
    user=Depends(current_user_required),
) -> InspectMemoryResponse:
    if req.user_id != user.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Cannot inspect memory for another user",
        )
    rows = await svc.inspect(
        session,
        user_id=user.id,
        avatar_id=req.avatar_id,
        limit=req.limit,
        offset=req.offset,
        include_user_scope=req.include_user_scope,
        include_avatar_scope=req.include_avatar_scope,
        include_cards=req.include_cards,
        include_chunks=req.include_chunks,
    )
    items = await _attach_linked(svc, session, user.id, rows)
    return InspectMemoryResponse(items=items)


@router.post("/delete", response_model=DeleteMemoryResponse)
async def delete_memory(
    req: DeleteMemoryRequest,
    session: Annotated[AsyncSession, Depends(database_session)],
    svc: Annotated[MemoryService, Depends(get_memory_service)],
    user=Depends(current_user_required),
) -> DeleteMemoryResponse:
    if req.user_id != user.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Cannot delete memory for another user",
        )
    deleted = await svc.delete(session, user_id=user.id, ids=req.ids)
    return DeleteMemoryResponse(deleted_count=deleted)


@router.patch("/{memory_id}", response_model=MemoryItem)
async def patch_memory(
    memory_id: UUID,
    req: PatchMemoryRequest,
    session: Annotated[AsyncSession, Depends(database_session)],
    svc: Annotated[MemoryService, Depends(get_memory_service)],
    user=Depends(current_user_required),
) -> MemoryItem:
    try:
        row = await svc.update_content(
            session, user_id=user.id, memory_id=memory_id, content=req.content
        )
    except MemoryUnprocessableException as exc:
        # 404 for not-found, 422 for genuinely bad input
        if str(exc) == "memory_not_found":
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)
            ) from exc
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(exc),
        ) from exc
    except MemoryServiceException as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=exc.details or exc.message,
        ) from exc
    linked = (await svc.get_linked_entities(
        session, user_id=user.id, memory_ids=[row.id]
    )).get(row.id, [])
    return _to_item(row, linked)


@router.get("/graph", response_model=GraphResponse)
async def graph_memory(
    session: Annotated[AsyncSession, Depends(database_session)],
    svc: Annotated[MemoryService, Depends(get_memory_service)],
    user=Depends(current_user_required),
    date_from: Annotated[datetime | None, Query()] = None,
    date_to: Annotated[datetime | None, Query()] = None,
    entity_id: Annotated[UUID | None, Query()] = None,
    limit_memories: Annotated[int, Query(ge=1, le=2000)] = 500,
) -> GraphResponse:
    mems, ents, edges = await svc.get_graph(
        session,
        user_id=user.id,
        date_from=date_from,
        date_to=date_to,
        entity_id=entity_id,
        limit_memories=limit_memories,
    )
    nodes: list[GraphNode] = []
    for m in mems:
        # Short label for memory nodes — first 60 chars of content.
        label = m.content if len(m.content) <= 60 else (m.content[:57] + "...")
        nodes.append(
            GraphNode(
                id=f"memory:{m.id}",
                kind=f"memory_{m.kind}",
                label=label,
            )
        )
    for e in ents:
        nodes.append(
            GraphNode(
                id=f"entity:{e.id}",
                kind=f"entity_{e.kind}",
                label=e.name,
            )
        )
    edge_models = [
        GraphEdge(
            source=f"memory:{mid}",
            target=f"entity:{eid}",
            relation=rel,
        )
        for (mid, eid, rel) in edges
    ]
    return GraphResponse(nodes=nodes, edges=edge_models)
