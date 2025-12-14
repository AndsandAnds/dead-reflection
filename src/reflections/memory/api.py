from __future__ import annotations

from functools import lru_cache
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException  # type: ignore[import-not-found]
from sqlalchemy.ext.asyncio import AsyncSession  # type: ignore[import-not-found]
from starlette import status  # type: ignore[import-not-found]

from reflections.auth.depends import current_user_required
from reflections.commons.depends import database_session
from reflections.memory.schemas import (
    DeleteMemoryRequest,
    DeleteMemoryResponse,
    IngestMemoryRequest,
    IngestMemoryResponse,
    InspectMemoryRequest,
    InspectMemoryResponse,
    MemoryItem,
    SearchMemoryRequest,
    SearchMemoryResponse,
)
from reflections.memory.service import MemoryService

router = APIRouter(prefix="/memory", tags=["memory"])


@lru_cache
def get_memory_service() -> MemoryService:
    return MemoryService.create()


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
    )
    return SearchMemoryResponse(
        items=[
            MemoryItem(
                id=r.id,
                user_id=r.user_id,
                avatar_id=r.avatar_id,
                scope=r.scope,
                kind=r.kind,
                content=r.content,
                created_at=r.created_at,
            )
            for r in rows
        ]
    )


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
    return InspectMemoryResponse(
        items=[
            MemoryItem(
                id=r.id,
                user_id=r.user_id,
                avatar_id=r.avatar_id,
                scope=r.scope,
                kind=r.kind,
                content=r.content,
                created_at=r.created_at,
            )
            for r in rows
        ]
    )


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
