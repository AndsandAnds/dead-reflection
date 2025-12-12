from __future__ import annotations

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
        # Minimal, non-streaming call for MVP.
        payload = {
            "model": settings.OLLAMA_MODEL,
            "prompt": transcript,
            "stream": False,
        }
        async with httpx.AsyncClient(base_url=settings.OLLAMA_BASE_URL) as client:
            resp = await client.post("/api/generate", json=payload, timeout=30.0)
            resp.raise_for_status()
            data = resp.json()
            return str(data.get("response", "")).strip()
