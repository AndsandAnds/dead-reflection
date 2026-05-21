from __future__ import annotations

from functools import lru_cache
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException  # type: ignore[import-not-found]
from sqlalchemy.ext.asyncio import AsyncSession  # type: ignore[import-not-found]
from starlette import status  # type: ignore[import-not-found]

from reflections.auth.depends import current_user_required
from reflections.commons.depends import database_session
from reflections.entities.exceptions import (
    EntitiesNotFoundException,
    EntitiesServiceException,
    EntitiesUnprocessableException,
)
from reflections.entities.schemas import (
    CreateEntityRequest,
    Entity,
    EntityKind,
    EntityListResponse,
    EntityMemoriesResponse,
    MergeEntitiesRequest,
    UpdateEntityRequest,
)
from reflections.entities.service import EntitiesService

router = APIRouter(prefix="/entities", tags=["entities"])


@lru_cache
def get_entities_service() -> EntitiesService:
    return EntitiesService.create()


def _to_schema(row) -> Entity:  # type: ignore[no-untyped-def]
    return Entity(
        id=row.id,
        user_id=row.user_id,
        kind=row.kind,
        name=row.name,
        slug=row.slug,
        description=row.description,
        attributes=row.attributes,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


@router.get("", response_model=EntityListResponse)
async def list_entities(
    session: Annotated[AsyncSession, Depends(database_session)],
    svc: Annotated[EntitiesService, Depends(get_entities_service)],
    user=Depends(current_user_required),
    kind: EntityKind | None = None,
    limit: int = 100,
    offset: int = 0,
) -> EntityListResponse:
    rows = await svc.list_for_user(
        session, user_id=user.id, kind=kind, limit=limit, offset=offset
    )
    return EntityListResponse(items=[_to_schema(r) for r in rows])


@router.post("", response_model=Entity, status_code=status.HTTP_201_CREATED)
async def create_entity(
    req: CreateEntityRequest,
    session: Annotated[AsyncSession, Depends(database_session)],
    svc: Annotated[EntitiesService, Depends(get_entities_service)],
    user=Depends(current_user_required),
) -> Entity:
    try:
        row = await svc.add(
            session,
            user_id=user.id,
            kind=req.kind,
            name=req.name,
            description=req.description,
            attributes=req.attributes,
        )
    except EntitiesUnprocessableException as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=exc.details or exc.message,
        ) from exc
    return _to_schema(row)


@router.get("/{entity_id}", response_model=Entity)
async def get_entity(
    entity_id: UUID,
    session: Annotated[AsyncSession, Depends(database_session)],
    svc: Annotated[EntitiesService, Depends(get_entities_service)],
    user=Depends(current_user_required),
) -> Entity:
    try:
        row = await svc.get(session, user_id=user.id, entity_id=entity_id)
    except EntitiesNotFoundException as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=exc.details or exc.message,
        ) from exc
    return _to_schema(row)


@router.patch("/{entity_id}", response_model=Entity)
async def update_entity(
    entity_id: UUID,
    req: UpdateEntityRequest,
    session: Annotated[AsyncSession, Depends(database_session)],
    svc: Annotated[EntitiesService, Depends(get_entities_service)],
    user=Depends(current_user_required),
) -> Entity:
    try:
        row = await svc.update(
            session,
            user_id=user.id,
            entity_id=entity_id,
            name=req.name,
            description=req.description,
            attributes=req.attributes,
        )
    except EntitiesNotFoundException as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=exc.details or exc.message,
        ) from exc
    return _to_schema(row)


@router.delete("/{entity_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_entity(
    entity_id: UUID,
    session: Annotated[AsyncSession, Depends(database_session)],
    svc: Annotated[EntitiesService, Depends(get_entities_service)],
    user=Depends(current_user_required),
) -> None:
    try:
        await svc.delete(session, user_id=user.id, entity_id=entity_id)
    except EntitiesNotFoundException as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=exc.details or exc.message,
        ) from exc


@router.post("/{entity_id}/merge", status_code=status.HTTP_204_NO_CONTENT)
async def merge_entity(
    entity_id: UUID,
    req: MergeEntitiesRequest,
    session: Annotated[AsyncSession, Depends(database_session)],
    svc: Annotated[EntitiesService, Depends(get_entities_service)],
    user=Depends(current_user_required),
) -> None:
    try:
        await svc.merge_into(
            session, user_id=user.id, target_id=entity_id, from_id=req.from_id
        )
    except EntitiesNotFoundException as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=exc.details or exc.message,
        ) from exc
    except EntitiesUnprocessableException as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=exc.details or exc.message,
        ) from exc
    except EntitiesServiceException as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=exc.details or exc.message,
        ) from exc


@router.get("/{entity_id}/memories", response_model=EntityMemoriesResponse)
async def list_entity_memories(
    entity_id: UUID,
    session: Annotated[AsyncSession, Depends(database_session)],
    svc: Annotated[EntitiesService, Depends(get_entities_service)],
    user=Depends(current_user_required),
    limit: int = 100,
) -> EntityMemoriesResponse:
    ids = await svc.list_memories_for(
        session, user_id=user.id, entity_id=entity_id, limit=limit
    )
    return EntityMemoriesResponse(memory_ids=ids)
