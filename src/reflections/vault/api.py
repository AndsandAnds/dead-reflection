from __future__ import annotations

from functools import lru_cache
from typing import Annotated

from fastapi import (  # type: ignore[import-not-found]
    APIRouter,
    Depends,
    File,
    HTTPException,
    Query,
    UploadFile,
)
from fastapi.responses import Response  # type: ignore[import-not-found]
from sqlalchemy.ext.asyncio import AsyncSession  # type: ignore[import-not-found]
from starlette import status  # type: ignore[import-not-found]

from reflections.auth.depends import current_user_required
from reflections.commons.depends import database_session
from reflections.vault.exceptions import (
    VaultServiceException,
    VaultUnprocessableException,
)
from reflections.vault.schemas import ImportStats
from reflections.vault.service import VaultService

router = APIRouter(prefix="/vault", tags=["vault"])


@lru_cache
def get_vault_service() -> VaultService:
    return VaultService.default()


@router.post("/export")
async def export_vault(
    session: Annotated[AsyncSession, Depends(database_session)],
    svc: Annotated[VaultService, Depends(get_vault_service)],
    user=Depends(current_user_required),
) -> Response:
    """
    Render the caller's entire memory + entity store as a tar.gz of markdown
    notes (daily/, people/, places/, events/, topics/). Stream-back as
    `application/gzip`. Stats are returned in the `X-Vault-Stats` header.
    """
    try:
        blob, stats = await svc.export_user_vault(session, user_id=user.id)
    except VaultServiceException as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=exc.details or exc.message,
        ) from exc
    fname = f"reflections-vault-{user.email or user.id}.tar.gz"
    return Response(
        content=blob,
        media_type="application/gzip",
        headers={
            "Content-Disposition": f'attachment; filename="{fname}"',
            "X-Vault-Stats": stats.model_dump_json(),
        },
    )


@router.post("/import", response_model=ImportStats)
async def import_vault(
    session: Annotated[AsyncSession, Depends(database_session)],
    svc: Annotated[VaultService, Depends(get_vault_service)],
    file: Annotated[UploadFile, File(..., description="tar.gz exported by /vault/export")],
    dry_run: Annotated[bool, Query()] = False,
    user=Depends(current_user_required),
) -> ImportStats:
    """
    Apply edits from a vault archive. Updates EXISTING memories' content
    (re-embeds them) and EXISTING entities' descriptions. New rows in the
    archive are skipped — the DB stays canonical for what exists.
    """
    blob = await file.read()
    try:
        return await svc.import_user_vault(
            session, user_id=user.id, tarball=blob, dry_run=dry_run
        )
    except VaultUnprocessableException as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=exc.details or exc.message,
        ) from exc
    except VaultServiceException as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=exc.details or exc.message,
        ) from exc
