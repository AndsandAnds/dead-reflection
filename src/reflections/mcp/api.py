from __future__ import annotations

from functools import lru_cache
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException  # type: ignore[import-not-found]
from sqlalchemy.ext.asyncio import AsyncSession  # type: ignore[import-not-found]
from starlette import status  # type: ignore[import-not-found]

from reflections.auth.depends import current_user_required
from reflections.commons.depends import database_session
from reflections.mcp.exceptions import (
    McpServiceException,
    McpTokenNotFoundException,
)
from reflections.mcp.schemas import (
    CreateMcpTokenRequest,
    McpTokenCreated,
    McpTokenListResponse,
    McpTokenPublic,
)
from reflections.mcp.service import McpService

router = APIRouter(prefix="/mcp/tokens", tags=["mcp"])


@lru_cache
def get_mcp_service() -> McpService:
    return McpService.default()


def _to_public(row) -> McpTokenPublic:  # type: ignore[no-untyped-def]
    return McpTokenPublic(
        id=row.id,
        user_id=row.user_id,
        name=row.name,
        scopes=list(getattr(row, "scopes", []) or []),
        created_at=row.created_at,
        last_used_at=row.last_used_at,
        revoked_at=row.revoked_at,
    )


@router.post("", response_model=McpTokenCreated, status_code=status.HTTP_201_CREATED)
async def mint_token(
    req: CreateMcpTokenRequest,
    session: Annotated[AsyncSession, Depends(database_session)],
    svc: Annotated[McpService, Depends(get_mcp_service)],
    user=Depends(current_user_required),
) -> McpTokenCreated:
    try:
        row, raw = await svc.mint(
            session, user_id=user.id, name=req.name, scopes=req.scopes
        )
    except McpServiceException as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=exc.details or exc.message,
        ) from exc
    public = _to_public(row)
    return McpTokenCreated(
        **public.model_dump(),
        token=raw,
    )


@router.get("", response_model=McpTokenListResponse)
async def list_tokens(
    session: Annotated[AsyncSession, Depends(database_session)],
    svc: Annotated[McpService, Depends(get_mcp_service)],
    user=Depends(current_user_required),
) -> McpTokenListResponse:
    rows = await svc.list_for_user(session, user_id=user.id)
    return McpTokenListResponse(items=[_to_public(r) for r in rows])


@router.delete("/{token_id}", status_code=status.HTTP_204_NO_CONTENT)
async def revoke_token(
    token_id: UUID,
    session: Annotated[AsyncSession, Depends(database_session)],
    svc: Annotated[McpService, Depends(get_mcp_service)],
    user=Depends(current_user_required),
) -> None:
    try:
        await svc.revoke(session, user_id=user.id, token_id=token_id)
    except McpTokenNotFoundException as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=exc.details or exc.message,
        ) from exc
