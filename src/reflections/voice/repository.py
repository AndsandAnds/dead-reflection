from __future__ import annotations

import base64
import io
import json
import wave
from array import array
from collections.abc import AsyncIterator
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
    target_sample_rate: int = 16000

    def ingest_audio(self, audio_bytes: bytes) -> int:
        self.bytes_received += len(audio_bytes)
        self.audio_pcm16le.extend(audio_bytes)
        return self.bytes_received

    def reset_audio(self) -> None:
        self.bytes_received = 0
        self.audio_pcm16le.clear()

    def audio_snapshot(self) -> bytes:
        return bytes(self.audio_pcm16le)

    async def transcribe_audio(
        self, *, sample_rate: int, pcm16le: bytes | None = None
    ) -> str:
        """
        Transcribe buffered PCM16LE mono audio via an STT service.

        No error handling here (repository rule); service decides fallbacks.
        """
        if not settings.STT_BASE_URL:
            raise RuntimeError("STT_BASE_URL is not configured")

        raw = pcm16le if pcm16le is not None else self.audio_snapshot()
        wav_bytes = self._to_wav_bytes(pcm16le=raw, sample_rate=sample_rate)
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

    def _resample_to_target(self, *, pcm16le: bytes, sample_rate: int) -> bytes:
        sr_in = int(sample_rate)
        sr_out = int(self.target_sample_rate)
        if sr_in <= 0:
            raise ValueError("sample_rate must be positive")
        if sr_in == sr_out:
            return pcm16le
        # Avoid stdlib audioop (removed in Python 3.13). This linear resampler is
        # sufficient for STT input normalization in short utterances.
        src = array("h")
        src.frombytes(pcm16le)
        if len(src) < 2:
            return pcm16le

        ratio = sr_out / float(sr_in)
        out_len = max(1, int(round(len(src) * ratio)))
        out = array("h", [0]) * out_len
        step = sr_in / float(sr_out)

        for i in range(out_len):
            pos = i * step
            j = int(pos)
            if j >= len(src) - 1:
                s = int(src[-1])
            else:
                frac = pos - j
                s0 = int(src[j])
                s1 = int(src[j + 1])
                s = int(round((1.0 - frac) * s0 + frac * s1))
            if s > 32767:
                s = 32767
            elif s < -32768:
                s = -32768
            out[i] = s

        return out.tobytes()

    def _to_wav_bytes(self, *, pcm16le: bytes, sample_rate: int) -> bytes:
        # We standardize on 16kHz mono PCM16 for STT inputs.
        pcm16_16k = self._resample_to_target(pcm16le=pcm16le, sample_rate=sample_rate)
        buf = io.BytesIO()
        with wave.open(buf, "wb") as wf:
            wf.setnchannels(1)
            wf.setsampwidth(2)  # PCM16
            wf.setframerate(int(self.target_sample_rate))
            wf.writeframes(pcm16_16k)
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
        timeout_s = float(settings.OLLAMA_TIMEOUT_S)
        timeout = httpx.Timeout(timeout_s, connect=min(2.0, timeout_s))
        async with httpx.AsyncClient(base_url=settings.OLLAMA_BASE_URL) as client:
            resp = await client.post("/api/chat", json=payload, timeout=timeout)
            resp.raise_for_status()
            data = resp.json()
            msg = data.get("message") or {}
            return str(msg.get("content", "")).strip()

    async def stream_assistant_reply_chat(
        self, *, messages: list[dict[str, str]]
    ) -> AsyncIterator[str]:
        """
        Stream Ollama /api/chat and yield text deltas.

        Ollama returns newline-delimited JSON objects when stream=true.
        """
        payload = {
            "model": settings.OLLAMA_MODEL,
            "messages": messages,
            "stream": True,
            "keep_alive": "10m",
        }
        timeout_s = float(settings.OLLAMA_TIMEOUT_S)
        timeout = httpx.Timeout(timeout_s, connect=min(2.0, timeout_s))

        async with httpx.AsyncClient(base_url=settings.OLLAMA_BASE_URL) as client:
            async with client.stream(
                "POST", "/api/chat", json=payload, timeout=timeout
            ) as resp:
                resp.raise_for_status()
                async for line in resp.aiter_lines():
                    if not line:
                        continue
                    obj = json.loads(line)
                    msg = obj.get("message") or {}
                    delta = str(msg.get("content") or "")
                    if delta:
                        yield delta

    async def synthesize_tts_wav(self, *, text: str, voice: str | None = None) -> bytes:
        """
        Synthesize TTS audio via a host-run TTS bridge.

        No error handling here (repository rule); service decides fallbacks.
        """
        if not settings.TTS_BASE_URL:
            raise RuntimeError("TTS_BASE_URL is not configured")
        payload: dict[str, str] = {"text": text}
        if voice:
            payload["voice"] = voice
        async with httpx.AsyncClient(base_url=settings.TTS_BASE_URL) as client:
            resp = await client.post(
                "/speak",
                json=payload,
                timeout=float(settings.TTS_TIMEOUT_S),
            )
            resp.raise_for_status()
            return bytes(resp.content)

    async def list_tts_voices(self) -> dict:
        """
        List available voices from the host TTS bridge (best-effort).

        No error handling here (repository rule); service decides fallbacks.
        """
        if not settings.TTS_BASE_URL:
            raise RuntimeError("TTS_BASE_URL is not configured")
        timeout_s = float(min(2.0, max(0.2, float(settings.TTS_TIMEOUT_S))))
        timeout = httpx.Timeout(timeout_s, connect=min(0.25, timeout_s))
        async with httpx.AsyncClient(base_url=settings.TTS_BASE_URL, timeout=timeout) as client:
            resp = await client.get("/voices")
            resp.raise_for_status()
            data = resp.json()
            if not isinstance(data, dict):
                return {"engine": None, "voices": []}
            return data

    @staticmethod
    def wav_bytes_to_b64(wav_bytes: bytes) -> str:
        return base64.b64encode(wav_bytes).decode("ascii")
