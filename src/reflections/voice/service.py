from __future__ import annotations

import asyncio
import contextlib
import json
import time
from array import array
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
    ServerTtsChunk,
)


@dataclass
class VoiceSessionState:
    closed: bool = False
    recording: bool = False
    sample_rate: int = 16000
    messages: list[dict[str, str]] = field(default_factory=list)
    latest_partial_text: str = ""
    turn_task: asyncio.Task[None] | None = None
    # naive VAD / endpointing (RMS threshold on PCM16)
    vad_last_speech_monotonic: float = 0.0
    vad_started_monotonic: float = 0.0


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


def rms_pcm16le(pcm16le: bytes) -> float:
    """
    Compute RMS level in [0, ~1] for mono PCM16LE bytes.
    """
    if not pcm16le:
        return 0.0
    samples = array("h")
    samples.frombytes(pcm16le)
    if not samples:
        return 0.0
    acc = 0.0
    for s in samples:
        x = float(s) / 32768.0
        acc += x * x
    return (acc / float(len(samples))) ** 0.5


def chunk_text_for_tts(text: str, *, max_chars: int = 180) -> list[str]:
    """
    Chunk text for "streaming-like" TTS. Keeps chunks small so audio starts fast.
    """
    t = " ".join(text.strip().split())
    if not t:
        return []
    # sentence-ish split
    parts: list[str] = []
    buf: list[str] = []
    size = 0
    for token in t.replace("\n", " ").split(" "):
        if not token:
            continue
        if size + len(token) + 1 > max_chars and buf:
            parts.append(" ".join(buf))
            buf = [token]
            size = len(token)
        else:
            buf.append(token)
            size += len(token) + 1
    if buf:
        parts.append(" ".join(buf))
    return parts


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

    async def cancel_turn(*, reset_audio: bool) -> None:
        # Cancel any in-flight processing.
        if state.turn_task and not state.turn_task.done():
            state.turn_task.cancel()
        state.turn_task = None
        state.recording = False
        state.latest_partial_text = ""
        if reset_audio:
            repo.reset_audio()
        await send(build_cancelled_message())
        # Ensure UI exits "finalizing" state even if it was waiting for done.
        await send(build_done_message())

    async def process_turn(*, pcm_snapshot: bytes, sample_rate: int) -> None:
        bytes_received = len(pcm_snapshot)
        duration_s = bytes_received / max(1.0, float(sample_rate) * 2.0)

        try:
            transcript = (
                f"(stub) user spoke for ~{duration_s:.2f}s ({bytes_received} bytes)"
            )
            if settings.STT_BASE_URL:
                transcript = await repo.transcribe_audio(
                    sample_rate=sample_rate, pcm16le=pcm_snapshot
                )
            await send(
                build_final_transcript_message(
                    text=transcript,
                    bytes_received=bytes_received,
                    duration_s=duration_s,
                )
            )

            state.messages.append({"role": "user", "content": transcript})

            try:
                reply = await asyncio.wait_for(
                    repo.generate_assistant_reply_chat(messages=state.messages),
                    timeout=float(settings.OLLAMA_TIMEOUT_S),
                )
            except Exception as exc:
                await send(ServerError(message=f"ollama_error:{exc!s}"))
                reply = "(stub) (ollama unavailable) I heard you."

            await send(build_assistant_message(text=reply))
            state.messages.append({"role": "assistant", "content": reply})

            # "Streaming-like" TTS: synthesize chunks and send sequentially.
            if settings.TTS_BASE_URL:
                chunks = chunk_text_for_tts(reply)
                for i, chunk in enumerate(chunks):
                    wav_bytes = await repo.synthesize_tts_wav(text=chunk)
                    await send(
                        ServerTtsChunk(
                            seq=i,
                            wav_b64=repo.wav_bytes_to_b64(wav_bytes),
                            is_last=(i == len(chunks) - 1),
                        )
                    )
                # Back-compat: also emit the old single-message form for clients
                # that haven't been updated yet (first chunk only).
                if chunks:
                    wav_bytes = await repo.synthesize_tts_wav(text=chunks[0])
                    await send(
                        build_tts_audio_message(
                            wav_b64=repo.wav_bytes_to_b64(wav_bytes)
                        )
                    )

            await send(build_done_message())
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            await send(ServerError(message=f"turn_error:{exc!s}"))
            await send(build_done_message())

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
        # Streaming-like STT: repeatedly transcribe a small tail window so the UI
        # receives frequent partial updates. (True incremental decoding remains a
        # future improvement, but this delivers the intended UX.)
        last_text = ""
        inflight: asyncio.Task[str] | None = None
        try:
            while True:
                await asyncio.sleep(0.65)
                if state.closed:
                    return
                if not state.recording:
                    continue
                if not settings.STT_BASE_URL:
                    continue

                if inflight and not inflight.done():
                    continue

                snapshot = repo.audio_snapshot()
                # Tail window: last ~3 seconds at capture rate.
                tail_bytes = int(max(1, state.sample_rate) * 2 * 3)
                window = (
                    snapshot[-tail_bytes:] if len(snapshot) > tail_bytes else snapshot
                )
                inflight = asyncio.create_task(
                    repo.transcribe_audio(sample_rate=state.sample_rate, pcm16le=window)
                )
                try:
                    text = await inflight
                except Exception:
                    # Partial STT failures shouldn't kill the session.
                    continue

                text = text.strip()
                if not text or text == last_text:
                    continue
                last_text = text
                state.latest_partial_text = text
                await send(
                    ServerPartialTranscript(
                        text=text,
                        bytes_received=repo.bytes_received,
                    )
                )
        except asyncio.CancelledError:
            if inflight and not inflight.done():
                inflight.cancel()
            raise

    async def endpoint_loop() -> None:
        # Naive server-side VAD/endpointing: watch RMS, auto-end after silence.
        # This complements the client-side silence timer and helps if the client
        # can't run endpointing reliably.
        min_record_s = 0.8
        silence_s = 0.7
        try:
            while True:
                await asyncio.sleep(0.05)
                if state.closed:
                    return
                if not state.recording:
                    continue
                if state.vad_started_monotonic <= 0:
                    continue
                now = time.monotonic()
                if now - state.vad_started_monotonic < min_record_s:
                    continue
                if state.vad_last_speech_monotonic <= 0:
                    continue
                if now - state.vad_last_speech_monotonic < silence_s:
                    continue

                # Auto-finalize.
                state.recording = False
                pcm = repo.audio_snapshot()
                repo.reset_audio()
                state.latest_partial_text = ""
                if not pcm:
                    continue
                if state.turn_task and not state.turn_task.done():
                    continue
                state.turn_task = asyncio.create_task(
                    process_turn(pcm_snapshot=pcm, sample_rate=state.sample_rate)
                )
        except asyncio.CancelledError:
            raise

    sender_task = asyncio.create_task(sender_loop())
    partial_task = asyncio.create_task(partial_stt_loop())
    endpoint_task = asyncio.create_task(endpoint_loop())
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
                    # Barge-in: if we're processing a turn, cancel it immediately.
                    if state.turn_task and not state.turn_task.done():
                        await cancel_turn(reset_audio=True)
                    if not state.recording:
                        state.vad_started_monotonic = time.monotonic()
                    if rms_pcm16le(bytes(audio_bytes)) >= 0.02:
                        state.vad_last_speech_monotonic = time.monotonic()
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
                await cancel_turn(reset_audio=True)
                continue

            if parsed.type == "hello":
                if parsed.sample_rate:
                    state.sample_rate = int(parsed.sample_rate)
                continue

            if parsed.type == "audio_frame":
                state.recording = True
                if not state.vad_started_monotonic:
                    state.vad_started_monotonic = time.monotonic()
                # Back-compat: legacy JSON base64 audio frames.
                try:
                    import base64

                    audio_bytes = base64.b64decode(parsed.pcm16le_b64)
                except Exception:
                    continue
                if rms_pcm16le(audio_bytes) >= 0.02:
                    state.vad_last_speech_monotonic = time.monotonic()
                repo.ingest_audio(audio_bytes)
                continue

            if parsed.type == "end":
                state.recording = False
                state.latest_partial_text = ""
                pcm = repo.audio_snapshot()
                repo.reset_audio()
                if not pcm:
                    await send(ServerError(message="no_audio"))
                    await send(build_done_message())
                    continue
                if state.turn_task and not state.turn_task.done():
                    # Client requested end while we're still finishing a previous
                    # turn; cancel and restart.
                    await cancel_turn(reset_audio=False)
                state.turn_task = asyncio.create_task(
                    process_turn(pcm_snapshot=pcm, sample_rate=state.sample_rate)
                )
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
        if state.turn_task and not state.turn_task.done():
            state.turn_task.cancel()
        sender_task.cancel()
        partial_task.cancel()
        endpoint_task.cancel()
        # CancelledError may inherit from BaseException in modern Python.
        with contextlib.suppress(asyncio.CancelledError):
            await sender_task
        with contextlib.suppress(asyncio.CancelledError):
            await partial_task
        with contextlib.suppress(asyncio.CancelledError):
            await endpoint_task
