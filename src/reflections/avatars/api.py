from __future__ import annotations

from functools import lru_cache
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException  # type: ignore[import-not-found]
from sqlalchemy.ext.asyncio import AsyncSession  # type: ignore[import-not-found]
from starlette import status  # type: ignore[import-not-found]

from reflections.avatars.schemas import (
    AvatarPublic,
    CreateAvatarRequest,
    DeleteAvatarRequest,
    GenerateAvatarImageRequest,
    GenerateAvatarImageResponse,
    ListAvatarsResponse,
    OkResponse,
    SetActiveAvatarRequest,
    UpdateAvatarRequest,
)
from reflections.avatars.service import AvatarsService
from reflections.auth.depends import current_user_required
from reflections.commons.depends import database_session

router = APIRouter(prefix="/avatars", tags=["avatars"])


@lru_cache
def get_avatars_service() -> AvatarsService:
    return AvatarsService.create()


def _to_public(a) -> AvatarPublic:  # type: ignore[no-untyped-def]
    return AvatarPublic(
        id=a.id,
        user_id=a.user_id,
        name=a.name,
        persona_prompt=a.persona_prompt,
        image_url=a.image_url,
        voice_config=a.voice_config,
        created_at=a.created_at,
        updated_at=a.updated_at,
    )


@router.get("", response_model=ListAvatarsResponse)
async def list_avatars(
    session: Annotated[AsyncSession, Depends(database_session)],
    svc: Annotated[AvatarsService, Depends(get_avatars_service)],
    user=Depends(current_user_required),
) -> ListAvatarsResponse:
    items, active = await svc.list_avatars(session, user=user)
    return ListAvatarsResponse(items=[_to_public(a) for a in items], active_avatar_id=active)


@router.post("", response_model=AvatarPublic, status_code=status.HTTP_201_CREATED)
async def create_avatar(
    req: CreateAvatarRequest,
    session: Annotated[AsyncSession, Depends(database_session)],
    svc: Annotated[AvatarsService, Depends(get_avatars_service)],
    user=Depends(current_user_required),
) -> AvatarPublic:
    a = await svc.create_avatar(
        session,
        user=user,
        name=req.name,
        persona_prompt=req.persona_prompt,
        image_url=req.image_url,
        voice_config=req.voice_config,
        set_active=bool(req.set_active),
    )
    return _to_public(a)


@router.patch("/{avatar_id}", response_model=AvatarPublic)
async def update_avatar(
    avatar_id: str,
    req: UpdateAvatarRequest,
    session: Annotated[AsyncSession, Depends(database_session)],
    svc: Annotated[AvatarsService, Depends(get_avatars_service)],
    user=Depends(current_user_required),
) -> AvatarPublic:
    from uuid import UUID

    a = await svc.update_avatar(
        session,
        user=user,
        avatar_id=UUID(avatar_id),
        name=req.name,
        persona_prompt=req.persona_prompt,
        image_url=req.image_url,
        voice_config=req.voice_config,
    )
    if a is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Avatar not found")
    return _to_public(a)


@router.post("/{avatar_id}/generate-image", response_model=GenerateAvatarImageResponse)
async def generate_avatar_image(
    avatar_id: str,
    req: GenerateAvatarImageRequest,
    session: Annotated[AsyncSession, Depends(database_session)],
    svc: Annotated[AvatarsService, Depends(get_avatars_service)],
    user=Depends(current_user_required),
) -> GenerateAvatarImageResponse:
    from uuid import UUID

    try:
        image_url = await svc.generate_image(
            session,
            user=user,
            avatar_id=UUID(avatar_id),
            engine=req.engine,
            prompt=req.prompt,
            negative_prompt=req.negative_prompt,
            width=req.width,
            height=req.height,
            steps=req.steps,
            cfg_scale=req.cfg_scale,
            sampler_name=req.sampler_name,
            seed=req.seed,
        )
    except ValueError as exc:
        if str(exc) == "avatar_not_found":
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="Avatar not found"
            )
        if str(exc) == "engine_not_supported":
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST, detail="Engine not supported"
            )
        raise
    return GenerateAvatarImageResponse(image_url=image_url)


@router.post("/active", response_model=OkResponse)
async def set_active_avatar(
    req: SetActiveAvatarRequest,
    session: Annotated[AsyncSession, Depends(database_session)],
    svc: Annotated[AvatarsService, Depends(get_avatars_service)],
    user=Depends(current_user_required),
) -> OkResponse:
    await svc.set_active(session, user=user, avatar_id=req.avatar_id)
    return OkResponse(ok=True)


@router.post("/delete", response_model=OkResponse)
async def delete_avatar(
    req: DeleteAvatarRequest,
    session: Annotated[AsyncSession, Depends(database_session)],
    svc: Annotated[AvatarsService, Depends(get_avatars_service)],
    user=Depends(current_user_required),
) -> OkResponse:
    deleted = await svc.delete_avatar(session, user=user, avatar_id=req.avatar_id)
    if deleted <= 0:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Avatar not found")
    return OkResponse(ok=True)


