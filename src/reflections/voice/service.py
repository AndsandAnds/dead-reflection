from __future__ import annotations

import asyncio
import contextlib
import json
import time
from array import array
from dataclasses import dataclass, field
from functools import lru_cache
from typing import Any

from fastapi import WebSocket, WebSocketDisconnect  # type: ignore[import-not-found]
from pydantic import TypeAdapter  # type: ignore[import-not-found]

from reflections.commons.logging import logger
from reflections.core.db import database_manager
from reflections.core.settings import settings
from reflections.memory.schemas import Turn
from reflections.memory.service import MemoryService
from reflections.voice.exceptions import VoiceServiceException
from reflections.voice.repository import VoiceRepository
from reflections.voice.schemas import (
    ClientMessage,
    ServerAssistantDelta,
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
    finalizing: bool = False
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


@lru_cache
def get_memory_service() -> MemoryService:
    return MemoryService.create()


def should_store_turns(turns: list[Turn]) -> bool:
    # Basic guardrails v0: skip empty/placeholder audio.
    joined = " ".join(t.content.strip() for t in turns if t.content)
    if not joined:
        return False
    low = joined.lower()
    if "[blank_audio]" in low:
        return False
    if low.startswith("(stub)"):
        return False
    return True


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


def pop_streaming_tts_chunks(
    buffer: str, *, max_chars: int = 180, min_chars: int = 40
) -> tuple[list[str], str]:
    """
    Incremental TTS chunker for streamed assistant text.

    We want to start speaking early, but avoid synthesizing tiny fragments.
    Strategy:
    - Prefer cutting at sentence boundaries (. ! ? or newline) once buffer is
      big enough.
    - Otherwise, cut at a space near max_chars.
    """
    buf = buffer.replace("\r", "")
    chunks: list[str] = []

    while True:
        cleaned = buf.strip()
        if len(cleaned) < min_chars:
            break

        # Sentence boundary cut.
        cut_idx = -1
        for ch in (".", "!", "?", "\n"):
            i = buf.rfind(ch, 0, min(len(buf), max_chars) + 1)
            cut_idx = max(cut_idx, i)
        if cut_idx != -1:
            chunk = buf[: cut_idx + 1].strip()
            buf = buf[cut_idx + 1 :]
            if chunk:
                chunks.append(chunk)
            continue

        # Fallback: split near max_chars.
        if len(buf) > max_chars:
            i = buf.rfind(" ", 0, max_chars + 1)
            if i == -1:
                i = max_chars
            chunk = buf[:i].strip()
            buf = buf[i:]
            if chunk:
                chunks.append(chunk)
            continue

        break

    return chunks, buf


async def run_voice_session(websocket: WebSocket) -> None:
    """
    Service-layer voice session loop.

    Owns orchestration and cancellation semantics. Uses repository for data access.
    """
    repo = VoiceRepository()
    state = VoiceSessionState()

    # Voice sessions can optionally write to Postgres (memory/conversation).
    await database_manager.initialize()

    send_lock = asyncio.Lock()
    finalize_lock = asyncio.Lock()

    async def send(model: Any) -> None:
        async with send_lock:
            await websocket.send_json(model.model_dump())

    await send(build_ready_message())

    async def cancel_turn(*, reset_audio: bool) -> None:
        state.finalizing = False
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

    async def start_finalize_turn(*, reason: str) -> None:
        """
        Start exactly one finalize/turn task.

        Guards against races between client 'end' and server endpointing.
        """
        async with finalize_lock:
            if state.finalizing:
                return
            state.finalizing = True
            state.recording = False
            state.latest_partial_text = ""
            state.vad_started_monotonic = 0.0
            state.vad_last_speech_monotonic = 0.0

            pcm = repo.audio_snapshot()
            repo.reset_audio()

            if not pcm:
                state.finalizing = False
                await send(ServerError(message="no_audio"))
                await send(build_done_message())
                return

            if state.turn_task and not state.turn_task.done():
                # Only a client 'end' should preempt an in-flight turn.
                if reason == "client_end":
                    await cancel_turn(reset_audio=False)
                else:
                    return

            state.turn_task = asyncio.create_task(
                process_turn(pcm_snapshot=pcm, sample_rate=state.sample_rate)
            )

    async def process_turn(*, pcm_snapshot: bytes, sample_rate: int) -> None:
        bytes_received = len(pcm_snapshot)
        duration_s = bytes_received / max(1.0, float(sample_rate) * 2.0)

        tts_task: asyncio.Task[None] | None = None
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

            # Stream assistant reply and feed TTS as text arrives.
            assistant_text = ""
            tts_buffer = ""
            tts_seq = 0
            tts_q: asyncio.Queue[str | None] | None = None

            async def tts_consumer() -> None:
                nonlocal tts_seq
                assert tts_q is not None
                while True:
                    item = await tts_q.get()
                    if item is None:
                        return
                    wav_bytes = await repo.synthesize_tts_wav(text=item)
                    await send(
                        ServerTtsChunk(
                            seq=tts_seq,
                            wav_b64=repo.wav_bytes_to_b64(wav_bytes),
                            is_last=False,
                        )
                    )
                    tts_seq += 1

            if settings.TTS_BASE_URL:
                tts_q = asyncio.Queue()
                tts_task = asyncio.create_task(tts_consumer())

            try:
                async for delta in repo.stream_assistant_reply_chat(
                    messages=state.messages
                ):
                    assistant_text += delta
                    await send(ServerAssistantDelta(delta=delta))

                    if settings.TTS_BASE_URL and tts_q is not None:
                        tts_buffer += delta
                        ready, tts_buffer = pop_streaming_tts_chunks(tts_buffer)
                        for chunk in ready:
                            await tts_q.put(chunk)
            except Exception as exc:
                await send(ServerError(message=f"ollama_error:{exc!s}"))
                assistant_text = "(stub) (ollama unavailable) I heard you."

            # Flush remaining TTS buffer (if any).
            if settings.TTS_BASE_URL and tts_q is not None:
                tail = tts_buffer.strip()
                if tail:
                    await tts_q.put(tail)
                await tts_q.put(None)
                if tts_task is not None:
                    await tts_task

            reply = assistant_text.strip()
            await send(build_assistant_message(text=reply))
            state.messages.append({"role": "assistant", "content": reply})

            # Automatic episodic memory ingest (opt-in/offline by default).
            if settings.MEMORY_AUTO_INGEST:
                try:
                    turns = [
                        Turn(role="user", content=transcript),
                        Turn(role="assistant", content=reply),
                    ]
                    if should_store_turns(turns):
                        async with database_manager.session() as session:
                            await get_memory_service().ingest_episodic(
                                session,
                                user_id=settings.DEFAULT_USER_ID,
                                avatar_id=settings.DEFAULT_AVATAR_ID,
                                turns=turns,
                                chunk_turn_window=settings.MEMORY_CHUNK_TURN_WINDOW,
                            )
                except Exception as exc:
                    # Don't fail the voice turn if memory ingestion fails.
                    details = getattr(exc, "details", None)
                    if details:
                        logger.info("memory_auto_ingest_failed: %s (%s)", exc, details)
                    else:
                        logger.info("memory_auto_ingest_failed: %s", exc)

            await send(build_done_message())
        except asyncio.CancelledError:
            if tts_task is not None and not tts_task.done():
                tts_task.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await tts_task
            raise
        except Exception as exc:
            await send(ServerError(message=f"turn_error:{exc!s}"))
            await send(build_done_message())
        finally:
            state.finalizing = False

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

                # Auto-finalize (guarded against races with client end).
                if state.turn_task and not state.turn_task.done():
                    continue
                if state.finalizing:
                    continue
                await start_finalize_turn(reason="endpoint")
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
                if isinstance(audio_bytes, bytes | bytearray):
                    level = rms_pcm16le(bytes(audio_bytes))

                    # When finalizing a turn, ignore silence/ambient frames so we
                    # don't cancel the turn just because the mic is still
                    # streaming. Only treat *speech-level* frames as barge-in.
                    if state.finalizing and level < 0.02:
                        continue

                    # Barge-in: only cancel in-flight work when speech is detected.
                    if state.turn_task and not state.turn_task.done() and level >= 0.02:
                        await cancel_turn(reset_audio=True)
                    if not state.recording:
                        state.vad_started_monotonic = time.monotonic()
                    if level >= 0.02:
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
                await start_finalize_turn(reason="client_end")
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
