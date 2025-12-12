from __future__ import annotations

import asyncio
import base64
import contextlib
from dataclasses import dataclass
from typing import Any

from fastapi import WebSocket, WebSocketDisconnect
from pydantic import TypeAdapter

from reflections.voice.exceptions import VoiceServiceException
from reflections.voice.repository import VoiceRepository
from reflections.voice.schemas import (
    ClientMessage,
    ServerCancelled,
    ServerError,
    ServerPartialTranscript,
    ServerReady,
)


@dataclass
class VoiceSessionState:
    cancelled: bool = False


def build_ready_message() -> ServerReady:
    return ServerReady()


def build_cancelled_message() -> ServerCancelled:
    return ServerCancelled()


def build_partial_transcript_message(*, bytes_received: int) -> ServerPartialTranscript:
    return ServerPartialTranscript(
        text=f"(stub) heard {bytes_received} bytes",
        bytes_received=bytes_received,
    )


_client_msg_adapter = TypeAdapter(ClientMessage)


def parse_client_message(payload: dict[str, Any]) -> ClientMessage:
    return _client_msg_adapter.validate_python(payload)


async def run_voice_session(websocket: WebSocket) -> None:
    """
    Service-layer voice session loop.

    Owns orchestration and cancellation semantics. Uses repository for data access.
    """
    repo = VoiceRepository()
    state = VoiceSessionState()

    await websocket.send_json(build_ready_message().model_dump())

    async def sender_loop() -> None:
        last_sent = 0
        while True:
            await asyncio.sleep(0.25)
            if state.cancelled:
                return
            if repo.bytes_received != last_sent:
                last_sent = repo.bytes_received
                await websocket.send_json(
                    build_partial_transcript_message(
                        bytes_received=last_sent
                    ).model_dump()
                )

    sender_task = asyncio.create_task(sender_loop())
    try:
        while True:
            try:
                payload = await websocket.receive_json()
            except WebSocketDisconnect:
                break
            except Exception:
                await websocket.send_json(
                    ServerError(message="invalid_json").model_dump()
                )
                continue

            if not isinstance(payload, dict):
                await websocket.send_json(
                    ServerError(message="invalid_message").model_dump()
                )
                continue

            try:
                parsed = parse_client_message(payload)
            except Exception:
                await websocket.send_json(
                    ServerError(message="invalid_message").model_dump()
                )
                continue

            if parsed.type == "cancel":
                state.cancelled = True
                await websocket.send_json(build_cancelled_message().model_dump())
                break

            if parsed.type == "audio_frame":
                try:
                    audio_bytes = base64.b64decode(parsed.pcm16le_b64)
                except Exception:
                    continue
                repo.ingest_audio(audio_bytes)
                continue

            # ignore unknown message types
            continue

    except WebSocketDisconnect:
        pass
    except Exception as exc:
        # If we later add structured error reporting, this is where it belongs.
        raise VoiceServiceException("Voice session failed", str(exc)) from exc
    finally:
        state.cancelled = True
        sender_task.cancel()
        # CancelledError may inherit from BaseException in modern Python.
        with contextlib.suppress(asyncio.CancelledError):
            await sender_task
