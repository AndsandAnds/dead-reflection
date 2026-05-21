from __future__ import annotations

from functools import lru_cache
from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, Query  # type: ignore[import-not-found]
from sqlalchemy.ext.asyncio import AsyncSession  # type: ignore[import-not-found]

from reflections.auth.depends import current_admin_required
from reflections.commons.depends import database_session
from reflections.outbound.repository import OutboundAuditRepository
from reflections.outbound.schemas import (
    OutboundAuditEntry,
    OutboundAuditPage,
)

router = APIRouter(prefix="/admin/outbound-audit-log", tags=["admin"])


@lru_cache
def get_audit_repo() -> OutboundAuditRepository:
    return OutboundAuditRepository()


@router.get("", response_model=OutboundAuditPage)
async def list_outbound_audit(
    session: Annotated[AsyncSession, Depends(database_session)],
    repo: Annotated[OutboundAuditRepository, Depends(get_audit_repo)],
    _admin=Depends(current_admin_required),
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
    offset: Annotated[int, Query(ge=0, le=10_000)] = 0,
    user_id: Annotated[UUID | None, Query()] = None,
    outcome: Annotated[
        Literal["ok", "denied", "error"] | None, Query()
    ] = None,
) -> OutboundAuditPage:
    rows = await repo.list_recent(
        session,
        limit=limit,
        offset=offset,
        user_id=user_id,
        outcome=outcome,
    )
    return OutboundAuditPage(
        items=[
            OutboundAuditEntry(
                id=r.id,
                user_id=r.user_id,
                method=r.method,
                url=r.url,
                purpose=r.purpose,
                status_code=r.status_code,
                outcome=r.outcome,  # type: ignore[arg-type]
                error=r.error,
                duration_ms=r.duration_ms,
                ts=r.ts,
            )
            for r in rows
        ],
        limit=limit,
        offset=offset,
    )
