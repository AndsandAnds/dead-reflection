from __future__ import annotations

from functools import lru_cache
from typing import Annotated

from fastapi import Cookie, Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession  # type: ignore[import-not-found]

from reflections.auth.service import AuthService
from reflections.commons.depends import database_session
from reflections.core.settings import settings


@lru_cache
def get_auth_service() -> AuthService:
    return AuthService.create()


async def current_user_optional(
    request: Request,
    session: Annotated[AsyncSession, Depends(database_session)],
    svc: Annotated[AuthService, Depends(get_auth_service)],
    token: str | None = Cookie(default=None, alias=settings.AUTH_COOKIE_NAME),
):
    if not token:
        return None
    return await svc.get_user_for_session_token(session, token=token)


