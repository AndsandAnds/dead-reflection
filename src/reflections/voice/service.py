from __future__ import annotations

import asyncio
import contextlib
import json
from dataclasses import dataclass, field
from typing import Any

from fastapi import WebSocket, WebSocketDisconnect  # type: ignore[import-not-found]
from pydantic import TypeAdapter  # type: ignore[import-not-found]

from reflections.core.settings import settings
from reflections.voice.exceptions import VoiceServiceException
from reflections.voice.repository import VoiceRepository
from reflections.voice.schemas import (
    ClientMessage,
    ServerAssistantMessage,
    ServerCancelled,
    ServerDone,
    ServerError,
    ServerFinalTranscript,
    ServerPartialTranscript,
    ServerReady,
    ServerTtsAudio,
)


@dataclass
class VoiceSessionState:
    closed: bool = False
    recording: bool = False
    sample_rate: int = 16000
    messages: list[dict[str, str]] = field(default_factory=list)
    latest_partial_text: str = ""


def build_ready_message() -> ServerReady:
    return ServerReady()


def build_cancelled_message() -> ServerCancelled:
    return ServerCancelled()


def build_partial_transcript_message(
    *, bytes_received: int, duration_s: float
) -> ServerPartialTranscript:
    return ServerPartialTranscript(
        text=f"listening… ~{duration_s:.2f}s",
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


def build_tts_audio_message(*, wav_b64: str) -> ServerTtsAudio:
    return ServerTtsAudio(wav_b64=wav_b64)


def build_done_message() -> ServerDone:
    return ServerDone()


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

    send_lock = asyncio.Lock()

    async def send(model: Any) -> None:
        async with send_lock:
            await websocket.send_json(model.model_dump())

    await send(build_ready_message())

    async def sender_loop() -> None:
        last_sent = 0
        while True:
            await asyncio.sleep(0.25)
            if state.closed:
                return
            if not state.recording:
                continue
            if repo.bytes_received != last_sent:
                last_sent = repo.bytes_received
                duration_s = last_sent / max(1.0, float(state.sample_rate) * 2.0)
                text = state.latest_partial_text.strip()
                if text:
                    await send(
                        ServerPartialTranscript(
                            text=text,
                            bytes_received=last_sent,
                        )
                    )
                else:
                    await send(
                        build_partial_transcript_message(
                            bytes_received=last_sent, duration_s=duration_s
                        )
                    )

    async def partial_stt_loop() -> None:
        # "Batch partial" STT: periodically transcribe audio-so-far to emit a real
        # partial transcript (low-latency feel without a true streaming ASR).
        last_partial_bytes = 0
        inflight: asyncio.Task[str] | None = None
        try:
            while True:
                await asyncio.sleep(1.25)
                if state.closed:
                    return
                if not state.recording:
                    continue
                if not settings.STT_BASE_URL:
                    continue

                bytes_now = repo.bytes_received
                if bytes_now - last_partial_bytes < 8000:
                    # Avoid hammering STT for tiny increments.
                    continue

                if inflight and not inflight.done():
                    continue

                snapshot = repo.audio_snapshot()
                inflight = asyncio.create_task(
                    repo.transcribe_audio(
                        sample_rate=state.sample_rate, pcm16le=snapshot
                    )
                )
                try:
                    text = await inflight
                except Exception:
                    # Partial STT failures shouldn't kill the session.
                    continue

                if text:
                    state.latest_partial_text = text
                    last_partial_bytes = bytes_now
        except asyncio.CancelledError:
            if inflight and not inflight.done():
                inflight.cancel()
            raise

    sender_task = asyncio.create_task(sender_loop())
    partial_task = asyncio.create_task(partial_stt_loop())
    try:
        while True:
            try:
                event = await websocket.receive()
            except WebSocketDisconnect:
                break
            except Exception:
                await send(ServerError(message="invalid_message"))
                continue

            if isinstance(event, dict) and event.get("bytes") is not None:
                audio_bytes = event.get("bytes")
                if isinstance(audio_bytes, (bytes, bytearray)):
                    state.recording = True
                    repo.ingest_audio(bytes(audio_bytes))
                continue

            if not isinstance(event, dict) or event.get("text") is None:
                await send(ServerError(message="invalid_message"))
                continue

            raw_text = event.get("text")
            try:
                payload = json.loads(str(raw_text))
            except Exception:
                await send(ServerError(message="invalid_json"))
                continue

            try:
                parsed = parse_client_message(payload)
            except Exception:
                await send(ServerError(message="invalid_message"))
                continue

            if parsed.type == "cancel":
                state.recording = False
                repo.reset_audio()
                state.latest_partial_text = ""
                await send(build_cancelled_message())
                continue

            if parsed.type == "hello":
                if parsed.sample_rate:
                    state.sample_rate = int(parsed.sample_rate)
                continue

            if parsed.type == "audio_frame":
                state.recording = True
                # Back-compat: legacy JSON base64 audio frames.
                try:
                    import base64

                    audio_bytes = base64.b64decode(parsed.pcm16le_b64)
                except Exception:
                    continue
                repo.ingest_audio(audio_bytes)
                continue

            if parsed.type == "end":
                state.recording = False
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
                        await send(ServerError(message=f"stt_error:{exc!s}"))
                state.latest_partial_text = ""
                await send(
                    build_final_transcript_message(
                        text=transcript,
                        bytes_received=bytes_received,
                        duration_s=duration_s,
                    )
                )

                # Append to conversation history.
                state.messages.append({"role": "user", "content": transcript})

                try:
                    reply = await asyncio.wait_for(
                        repo.generate_assistant_reply_chat(messages=state.messages),
                        timeout=float(settings.OLLAMA_TIMEOUT_S),
                    )
                except Exception as exc:
                    # Make failures visible to the UI while still returning a stub
                    # reply.
                    await send(ServerError(message=f"ollama_error:{exc!s}"))
                    reply = "(stub) (ollama unavailable) I heard you."

                await send(build_assistant_message(text=reply))
                state.messages.append({"role": "assistant", "content": reply})

                if settings.TTS_BASE_URL:
                    try:
                        wav_bytes = await repo.synthesize_tts_wav(text=reply)
                        await send(
                            build_tts_audio_message(
                                wav_b64=repo.wav_bytes_to_b64(wav_bytes)
                            )
                        )
                    except Exception as exc:
                        await send(ServerError(message=f"tts_error:{exc!s}"))

                await send(build_done_message())
                repo.reset_audio()
                continue

            # ignore unknown message types
            continue

    except WebSocketDisconnect:
        pass
    except Exception as exc:
        # If we later add structured error reporting, this is where it belongs.
        raise VoiceServiceException("Voice session failed", str(exc)) from exc
    finally:
        state.closed = True
        sender_task.cancel()
        partial_task.cancel()
        # CancelledError may inherit from BaseException in modern Python.
        with contextlib.suppress(asyncio.CancelledError):
            await sender_task
        with contextlib.suppress(asyncio.CancelledError):
            await partial_task
