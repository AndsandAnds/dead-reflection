from __future__ import annotations

import base64
import io
import wave
from dataclasses import dataclass, field

import httpx  # type: ignore[import-not-found]

from reflections.core.settings import settings


@dataclass
class VoiceRepository:
    """Data layer for voice session (MVP stub).

    In the real implementation this will call a host STT service (whisper.cpp+Metal).
    """

    bytes_received: int = 0
    audio_pcm16le: bytearray = field(default_factory=bytearray)

    def ingest_audio(self, audio_bytes: bytes) -> int:
        self.bytes_received += len(audio_bytes)
        self.audio_pcm16le.extend(audio_bytes)
        # "flush" concept for DB doesn't apply here; we still keep this layer dumb.
        return self.bytes_received

    def reset_audio(self) -> None:
        self.bytes_received = 0
        self.audio_pcm16le.clear()

    async def transcribe_audio(self, *, sample_rate: int) -> str:
        """
        Transcribe buffered PCM16LE mono audio via an STT service.

        No error handling here (repository rule); service decides fallbacks.
        """
        if not settings.STT_BASE_URL:
            raise RuntimeError("STT_BASE_URL is not configured")

        wav_bytes = self._to_wav_bytes(sample_rate=sample_rate)
        files = {"audio": ("audio.wav", wav_bytes, "audio/wav")}
        async with httpx.AsyncClient(base_url=settings.STT_BASE_URL) as client:
            resp = await client.post(
                "/transcribe",
                files=files,
                timeout=float(settings.STT_TIMEOUT_S),
            )
            resp.raise_for_status()
            data = resp.json()
            return str(data.get("text", "")).strip()

    def _to_wav_bytes(self, *, sample_rate: int) -> bytes:
        buf = io.BytesIO()
        with wave.open(buf, "wb") as wf:
            wf.setnchannels(1)
            wf.setsampwidth(2)  # PCM16
            wf.setframerate(int(sample_rate))
            wf.writeframes(bytes(self.audio_pcm16le))
        return buf.getvalue()

    async def generate_assistant_reply(self, *, transcript: str) -> str:
        """
        Call the local Ollama runtime to produce an assistant reply.

        No error handling here (repository rule); service decides fallbacks.
        """
        # Back-compat helper: call chat with a single user message.
        return await self.generate_assistant_reply_chat(
            messages=[{"role": "user", "content": transcript}]
        )

    async def generate_assistant_reply_chat(
        self, *, messages: list[dict[str, str]]
    ) -> str:
        """
        Call Ollama /api/chat with full message history.

        This keeps conversational context by sending the accumulated messages
        each turn (no server-side sessions).
        """
        payload = {
            "model": settings.OLLAMA_MODEL,
            "messages": messages,
            "stream": False,
            # Keep model hot between calls (best-effort; Ollama may ignore).
            "keep_alive": "10m",
        }
        async with httpx.AsyncClient(base_url=settings.OLLAMA_BASE_URL) as client:
            resp = await client.post("/api/chat", json=payload, timeout=30.0)
            resp.raise_for_status()
            data = resp.json()
            msg = data.get("message") or {}
            return str(msg.get("content", "")).strip()

    async def synthesize_tts_wav(self, *, text: str) -> bytes:
        """
        Synthesize TTS audio via a host-run TTS bridge.

        No error handling here (repository rule); service decides fallbacks.
        """
        if not settings.TTS_BASE_URL:
            raise RuntimeError("TTS_BASE_URL is not configured")
        async with httpx.AsyncClient(base_url=settings.TTS_BASE_URL) as client:
            resp = await client.post(
                "/speak",
                json={"text": text},
                timeout=float(settings.TTS_TIMEOUT_S),
            )
            resp.raise_for_status()
            return bytes(resp.content)

    @staticmethod
    def wav_bytes_to_b64(wav_bytes: bytes) -> str:
        return base64.b64encode(wav_bytes).decode("ascii")
