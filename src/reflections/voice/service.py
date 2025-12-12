from __future__ import annotations

import asyncio
import base64
import contextlib
from dataclasses import dataclass
from typing import Any

from fastapi import WebSocket, WebSocketDisconnect
from pydantic import TypeAdapter

from reflections.core.settings import settings
from reflections.voice.exceptions import VoiceServiceException
from reflections.voice.repository import VoiceRepository
from reflections.voice.schemas import (
    ClientMessage,
    ServerAssistantMessage,
    ServerCancelled,
    ServerError,
    ServerFinalTranscript,
    ServerPartialTranscript,
    ServerReady,
)


@dataclass
class VoiceSessionState:
    cancelled: bool = False
    sample_rate: int = 16000


def build_ready_message() -> ServerReady:
    return ServerReady()


def build_cancelled_message() -> ServerCancelled:
    return ServerCancelled()


def build_partial_transcript_message(
    *, bytes_received: int, duration_s: float
) -> ServerPartialTranscript:
    return ServerPartialTranscript(
        text=f"(stub) listening… ~{duration_s:.2f}s",
        bytes_received=bytes_received,
    )


def build_final_transcript_message(
    *, text: str, bytes_received: int, duration_s: float
) -> ServerFinalTranscript:
    return ServerFinalTranscript(
        text=text, bytes_received=bytes_received, duration_s=duration_s
    )


def build_assistant_message(*, text: str) -> ServerAssistantMessage:
    return ServerAssistantMessage(text=text)


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
                duration_s = last_sent / max(1.0, float(state.sample_rate) * 2.0)
                await websocket.send_json(
                    build_partial_transcript_message(
                        bytes_received=last_sent, duration_s=duration_s
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

            if parsed.type == "hello":
                if parsed.sample_rate:
                    state.sample_rate = int(parsed.sample_rate)
                continue

            if parsed.type == "audio_frame":
                try:
                    audio_bytes = base64.b64decode(parsed.pcm16le_b64)
                except Exception:
                    continue
                repo.ingest_audio(audio_bytes)
                continue

            if parsed.type == "end":
                state.cancelled = True
                bytes_received = repo.bytes_received
                duration_s = bytes_received / max(1.0, float(state.sample_rate) * 2.0)
                transcript = (
                    f"(stub) user spoke for ~{duration_s:.2f}s ({bytes_received} bytes)"
                )
                if settings.STT_BASE_URL:
                    try:
                        transcript = await repo.transcribe_audio(
                            sample_rate=state.sample_rate
                        )
                    except Exception as exc:
                        await websocket.send_json(
                            ServerError(message=f"stt_error:{exc!s}").model_dump()
                        )
                await websocket.send_json(
                    build_final_transcript_message(
                        text=transcript,
                        bytes_received=bytes_received,
                        duration_s=duration_s,
                    ).model_dump()
                )

                try:
                    reply = await asyncio.wait_for(
                        repo.generate_assistant_reply(transcript=transcript),
                        timeout=float(settings.OLLAMA_TIMEOUT_S),
                    )
                except Exception as exc:
                    # Make failures visible to the UI while still returning a stub
                    # reply.
                    await websocket.send_json(
                        ServerError(message=f"ollama_error:{exc!s}").model_dump()
                    )
                    reply = "(stub) (ollama unavailable) I heard you."

                await websocket.send_json(
                    build_assistant_message(text=reply).model_dump()
                )
                break

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
