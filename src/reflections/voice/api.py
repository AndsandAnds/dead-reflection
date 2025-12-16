from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, WebSocket
from sqlalchemy.ext.asyncio import AsyncSession  # type: ignore[import-not-found]

from reflections.voice import service
from reflections.voice.http_schemas import GreetResponse, ListVoicesResponse
from reflections.voice.http_service import VoiceHttpService, get_voice_http_service
from reflections.voice.exceptions import VoiceServiceException
from reflections.auth.depends import current_user_required
from reflections.commons.depends import database_session

router = APIRouter()


@router.websocket("/ws/voice")
async def ws_voice(websocket: WebSocket) -> None:
    # API layer: accept WS and delegate to service.
    await websocket.accept()
    try:
        await service.run_voice_session(websocket)
    except VoiceServiceException:
        # WebSocket equivalent of mapping exceptions -> protocol response.
        await websocket.close(code=1011)


@router.get("/voice/greet", response_model=GreetResponse)
async def greet(
    session: Annotated[AsyncSession, Depends(database_session)],
    svc: Annotated[VoiceHttpService, Depends(get_voice_http_service)],
    user=Depends(current_user_required),
) -> GreetResponse:
    return await svc.greet(session, user=user)


@router.get("/voice/voices", response_model=ListVoicesResponse)
async def list_voices(
    svc: Annotated[VoiceHttpService, Depends(get_voice_http_service)],
    user=Depends(current_user_required),
) -> ListVoicesResponse:
    # user is intentionally unused; auth gate only (consistent with the app’s privacy posture).
    _ = user
    return await svc.list_voices()
