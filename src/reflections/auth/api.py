from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Request, Response  # type: ignore[import-not-found]
from fastapi.responses import JSONResponse  # type: ignore[import-not-found]
from sqlalchemy.ext.asyncio import AsyncSession  # type: ignore[import-not-found]
from starlette import status  # type: ignore[import-not-found]

from reflections.auth.depends import current_user_optional, get_auth_service
from reflections.auth.exceptions import AuthServiceNotFoundException
from reflections.auth.schemas import AuthResponse, LoginRequest, SignupRequest, UserPublic
from reflections.auth.service import AuthService
from reflections.commons.depends import database_session
from reflections.core.settings import settings

router = APIRouter(prefix="/auth", tags=["auth"])


def _set_session_cookie(resp: Response, token: str) -> None:
    resp.set_cookie(
        key=settings.AUTH_COOKIE_NAME,
        value=token,
        httponly=True,
        secure=bool(settings.AUTH_COOKIE_SECURE),
        samesite=str(settings.AUTH_COOKIE_SAMESITE),
        path="/",
        max_age=int(settings.AUTH_SESSION_TTL_DAYS) * 24 * 60 * 60,
    )


def _clear_session_cookie(resp: Response) -> None:
    resp.delete_cookie(
        key=settings.AUTH_COOKIE_NAME,
        path="/",
    )


@router.post("/signup", response_model=AuthResponse)
async def signup(
    req: SignupRequest,
    request: Request,
    session: Annotated[AsyncSession, Depends(database_session)],
    svc: Annotated[AuthService, Depends(get_auth_service)],
) -> JSONResponse:
    user, token = await svc.signup(
        session, email=str(req.email), name=req.name, password=req.password
    )
    data = AuthResponse(
        user=UserPublic(
            id=user.id,
            email=user.email,
            name=user.name,
            created_at=user.created_at,
            last_login_at=user.last_login_at,
        )
    ).model_dump(mode="json")
    resp = JSONResponse(status_code=status.HTTP_200_OK, content=data)
    _set_session_cookie(resp, token)
    return resp


@router.post("/login", response_model=AuthResponse)
async def login(
    req: LoginRequest,
    request: Request,
    session: Annotated[AsyncSession, Depends(database_session)],
    svc: Annotated[AuthService, Depends(get_auth_service)],
) -> JSONResponse:
    # Map invalid creds to 401 (instead of generic 404/400)
    try:
        user, token = await svc.login(
            session, email=str(req.email), password=req.password
        )
    except AuthServiceNotFoundException as exc:
        raise AuthServiceNotFoundException(
            "unauthorized", exc.details or "Invalid credentials"
        ) from exc

    data = AuthResponse(
        user=UserPublic(
            id=user.id,
            email=user.email,
            name=user.name,
            created_at=user.created_at,
            last_login_at=user.last_login_at,
        )
    ).model_dump(mode="json")
    resp = JSONResponse(status_code=status.HTTP_200_OK, content=data)
    _set_session_cookie(resp, token)
    return resp


@router.post("/logout")
async def logout(
    request: Request,
    response: Response,
    session: Annotated[AsyncSession, Depends(database_session)],
    svc: Annotated[AuthService, Depends(get_auth_service)],
    user=Depends(current_user_optional),
) -> JSONResponse:
    token = request.cookies.get(settings.AUTH_COOKIE_NAME)
    if token:
        await svc.logout(session, token=token)
    resp = JSONResponse(status_code=status.HTTP_200_OK, content={"ok": True})
    _clear_session_cookie(resp)
    return resp


@router.get("/me", response_model=AuthResponse)
async def me(
    user=Depends(current_user_optional),
) -> AuthResponse:
    if not user:
        raise AuthServiceNotFoundException("unauthorized", "Not logged in")
    return AuthResponse(
        user=UserPublic(
            id=user.id,
            email=user.email,
            name=user.name,
            created_at=user.created_at,
            last_login_at=user.last_login_at,
        )
    )


