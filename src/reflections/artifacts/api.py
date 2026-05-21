from __future__ import annotations

from functools import lru_cache
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException  # type: ignore[import-not-found]
from sqlalchemy.ext.asyncio import AsyncSession  # type: ignore[import-not-found]
from starlette import status  # type: ignore[import-not-found]

from reflections.artifacts.exceptions import (
    ArtifactsNotConfiguredException,
    ArtifactsNotFoundException,
    ArtifactsServiceException,
    ArtifactsUnprocessableException,
    VolumeOfflineException,
)
from reflections.artifacts.schemas import (
    Artifact,
    ArtifactPage,
    RegisterVolumeRequest,
    Volume,
    VolumeListResponse,
    WalkRequest,
    WalkResult,
)
from reflections.artifacts.service import ArtifactsService
from reflections.auth.depends import current_user_required
from reflections.commons.depends import database_session

router = APIRouter(prefix="/artifacts", tags=["artifacts"])


@lru_cache
def get_artifacts_service() -> ArtifactsService:
    return ArtifactsService.default()


def _map_exc(exc: Exception) -> HTTPException:
    if isinstance(exc, ArtifactsNotConfiguredException):
        return HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=exc.details or exc.message,
        )
    if isinstance(exc, VolumeOfflineException):
        return HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=exc.details or exc.message,
        )
    if isinstance(exc, ArtifactsNotFoundException):
        return HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=exc.details or exc.message,
        )
    if isinstance(exc, ArtifactsUnprocessableException):
        return HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=exc.details or exc.message,
        )
    if isinstance(exc, ArtifactsServiceException):
        return HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=exc.details or exc.message,
        )
    raise exc  # pragma: no cover


def _volume_to_schema(row, mount_path: str | None) -> Volume:  # type: ignore[no-untyped-def]
    return Volume(
        id=row.id,
        user_id=row.user_id,
        label=row.label,
        volume_uuid=row.volume_uuid,
        fingerprint=row.fingerprint,
        mount_path=mount_path,
        # v1: trust mount_hints existence as "should be findable". A
        # follow-up will probe the bridge here for live online state.
        online=bool(mount_path),
        created_at=row.created_at,
        last_seen_at=row.last_seen_at,
    )


def _artifact_to_schema(row) -> Artifact:  # type: ignore[no-untyped-def]
    return Artifact(
        id=row.id,
        user_id=row.user_id,
        volume_id=row.volume_id,
        relative_path=row.relative_path,
        kind=row.kind,  # type: ignore[arg-type]
        mime=row.mime,
        size_bytes=row.size_bytes,
        mtime=row.mtime,
        sha256=row.sha256,
        attributes=row.attributes,
        catalog_state=row.catalog_state,  # type: ignore[arg-type]
        error=row.error,
        extracted_at=row.extracted_at,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


# --- volumes ----------------------------------------------------------------


@router.get("/volumes", response_model=VolumeListResponse)
async def list_volumes(
    session: Annotated[AsyncSession, Depends(database_session)],
    svc: Annotated[ArtifactsService, Depends(get_artifacts_service)],
    user=Depends(current_user_required),
) -> VolumeListResponse:
    try:
        pairs = await svc.list_volumes(session, user_id=user.id)
    except Exception as exc:
        raise _map_exc(exc)
    return VolumeListResponse(
        items=[_volume_to_schema(r, mp) for (r, mp) in pairs]
    )


@router.post(
    "/volumes",
    response_model=Volume,
    status_code=status.HTTP_201_CREATED,
)
async def register_volume(
    req: RegisterVolumeRequest,
    session: Annotated[AsyncSession, Depends(database_session)],
    svc: Annotated[ArtifactsService, Depends(get_artifacts_service)],
    user=Depends(current_user_required),
) -> Volume:
    try:
        row = await svc.register_volume(
            session,
            user_id=user.id,
            mount_path=req.mount_path,
            label=req.label,
        )
    except Exception as exc:
        raise _map_exc(exc)
    return _volume_to_schema(row, req.mount_path)


@router.delete(
    "/volumes/{volume_id}", status_code=status.HTTP_204_NO_CONTENT
)
async def delete_volume(
    volume_id: UUID,
    session: Annotated[AsyncSession, Depends(database_session)],
    svc: Annotated[ArtifactsService, Depends(get_artifacts_service)],
    user=Depends(current_user_required),
) -> None:
    try:
        await svc.delete_volume(session, user_id=user.id, volume_id=volume_id)
    except Exception as exc:
        raise _map_exc(exc)


@router.post(
    "/volumes/{volume_id}/catalog", response_model=WalkResult
)
async def catalog_volume(
    volume_id: UUID,
    req: WalkRequest,
    session: Annotated[AsyncSession, Depends(database_session)],
    svc: Annotated[ArtifactsService, Depends(get_artifacts_service)],
    user=Depends(current_user_required),
) -> WalkResult:
    if req.volume_id != volume_id:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="volume_id mismatch",
        )
    try:
        result = await svc.catalog_volume(
            session,
            user_id=user.id,
            volume_id=volume_id,
            subpath=req.subpath,
            max_entries_per_page=req.max_entries,
        )
    except Exception as exc:
        raise _map_exc(exc)
    return WalkResult(**result)


# --- artifacts --------------------------------------------------------------


@router.get("", response_model=ArtifactPage)
async def list_artifacts(
    session: Annotated[AsyncSession, Depends(database_session)],
    svc: Annotated[ArtifactsService, Depends(get_artifacts_service)],
    user=Depends(current_user_required),
    volume_id: UUID | None = None,
    kind: str | None = None,
    limit: int = 100,
    offset: int = 0,
) -> ArtifactPage:
    try:
        rows = await svc.list_artifacts(
            session,
            user_id=user.id,
            volume_id=volume_id,
            kind=kind,
            limit=limit,
            offset=offset,
        )
    except Exception as exc:
        raise _map_exc(exc)
    return ArtifactPage(
        items=[_artifact_to_schema(r) for r in rows],
        limit=limit,
        offset=offset,
    )


@router.get("/{artifact_id}", response_model=Artifact)
async def get_artifact(
    artifact_id: UUID,
    session: Annotated[AsyncSession, Depends(database_session)],
    svc: Annotated[ArtifactsService, Depends(get_artifacts_service)],
    user=Depends(current_user_required),
) -> Artifact:
    try:
        row = await svc.get_artifact(
            session, user_id=user.id, artifact_id=artifact_id
        )
    except Exception as exc:
        raise _map_exc(exc)
    return _artifact_to_schema(row)


@router.delete(
    "/{artifact_id}", status_code=status.HTTP_204_NO_CONTENT
)
async def delete_artifact(
    artifact_id: UUID,
    session: Annotated[AsyncSession, Depends(database_session)],
    svc: Annotated[ArtifactsService, Depends(get_artifacts_service)],
    user=Depends(current_user_required),
) -> None:
    try:
        await svc.delete_artifact(
            session, user_id=user.id, artifact_id=artifact_id
        )
    except Exception as exc:
        raise _map_exc(exc)
