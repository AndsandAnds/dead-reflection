from __future__ import annotations

from fastapi import APIRouter, WebSocket

from reflections.voice import service
from reflections.voice.exceptions import VoiceServiceException

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
