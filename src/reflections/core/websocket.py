"""
WebSocket manager (pattern-aligned).

We may later use this for tracking active voice sessions and for structured
progress updates.
"""

from __future__ import annotations

from typing import Any

from fastapi import WebSocket, status

from reflections.commons.logging import logger


class WebSocketError(Exception):
    def __init__(self, code: int, message: str):
        self.code = code
        self.message = message
        super().__init__(message)


class WebSocketManager:
    def __init__(self) -> None:
        self.active_connections: dict[str, WebSocket] = {}

    async def connect(self, connection_id: str, websocket: WebSocket) -> None:
        try:
            await websocket.accept()
            self.active_connections[connection_id] = websocket
        except Exception as exc:
            logger.exception("Failed to establish WebSocket connection", exc_info=exc)
            raise WebSocketError(
                code=status.WS_1011_INTERNAL_ERROR,
                message="Failed to establish connection",
            ) from exc

    async def disconnect(self, connection_id: str) -> None:
        ws = self.active_connections.pop(connection_id, None)
        if ws is None:
            return
        try:
            await ws.close()
        except Exception as exc:
            logger.exception("Error closing WebSocket connection", exc_info=exc)

    async def send_json(self, connection_id: str, data: dict[str, Any]) -> None:
        ws = self.active_connections.get(connection_id)
        if ws is None:
            raise WebSocketError(
                code=status.WS_1008_POLICY_VIOLATION,
                message="Connection not found",
            )
        try:
            await ws.send_json(data)
        except Exception as exc:
            logger.exception("Error sending WebSocket message", exc_info=exc)
            raise WebSocketError(
                code=status.WS_1011_INTERNAL_ERROR,
                message="Failed to send message",
            ) from exc


websocket_manager = WebSocketManager()
