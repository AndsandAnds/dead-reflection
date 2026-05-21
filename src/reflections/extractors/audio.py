"""
Audio extractor — posts bytes to the existing STT bridge (whisper.cpp).

The bridge returns the full transcript; we chunk it into ~30-second
slices so vector search has tighter hits than a single multi-thousand-
word blob would give. Since the bridge doesn't return word-level
timestamps, the chunk locators carry the chunk index rather than a
real timestamp; that's a v2 polish (passing back the timeline from
whisper.cpp).
"""

from __future__ import annotations

import io
from typing import Awaitable, Callable

import httpx  # type: ignore[import-not-found]

from reflections.core.settings import settings
from reflections.extractors.base import (
    ArtifactMeta,
    ExtractedChunk,
    ExtractionError,
)

# Roughly aligns to ~30s of speech for a normal speaker; tunable.
_DEFAULT_CHUNK_CHAR_TARGET = 600


async def extract(
    read_bytes: Callable[[], Awaitable[bytes]],
    meta: ArtifactMeta,
    *,
    stt_url: str | None = None,
    chunk_char_target: int = _DEFAULT_CHUNK_CHAR_TARGET,
) -> list[ExtractedChunk]:
    url = stt_url or settings.STT_BASE_URL
    if not url:
        raise ExtractionError("stt_bridge_not_configured")

    blob = await read_bytes()
    if not blob:
        raise ExtractionError("empty_audio")

    text = await _transcribe(blob, base_url=url, mime=meta.mime or "application/octet-stream", filename=meta.relative_path)
    text = (text or "").strip()
    if not text:
        return []

    parts = _chunk_text(text, chunk_char_target)
    return [
        ExtractedChunk(
            content=part,
            locator={"chunk": idx + 1, "total_chunks": len(parts)},
            metadata={
                "source_kind": "audio",
                "filename": meta.relative_path.rsplit("/", 1)[-1],
                "chunk_chars": len(part),
            },
        )
        for idx, part in enumerate(parts)
    ]


async def _transcribe(
    blob: bytes, *, base_url: str, mime: str, filename: str
) -> str:
    timeout = httpx.Timeout(float(settings.STT_TIMEOUT_S))
    files = {
        "audio": (filename.rsplit("/", 1)[-1], io.BytesIO(blob), mime),
    }
    async with httpx.AsyncClient(timeout=timeout) as client:
        try:
            r = await client.post(f"{base_url.rstrip('/')}/transcribe", files=files)
        except Exception as exc:
            raise ExtractionError(f"stt_unreachable: {exc}") from exc
    if r.status_code >= 400:
        raise ExtractionError(
            f"stt_failed: http_{r.status_code} {r.text[:200]}"
        )
    data = r.json()
    return str(data.get("text", ""))


def _chunk_text(text: str, target: int) -> list[str]:
    """Break a long transcript into ~target-char chunks at sentence
    boundaries when possible."""
    if len(text) <= target:
        return [text.strip()] if text.strip() else []
    parts: list[str] = []
    buf = ""
    for sentence in _split_sentences(text):
        if len(buf) + len(sentence) + 1 > target and buf:
            parts.append(buf.strip())
            buf = sentence
        else:
            buf = (buf + " " + sentence).strip() if buf else sentence
    if buf.strip():
        parts.append(buf.strip())
    return parts


def _split_sentences(text: str) -> list[str]:
    # Cheap sentence splitter — splits on terminal punctuation followed
    # by whitespace + capital. Good enough for transcribed speech.
    import re

    raw = re.split(r"(?<=[.!?])\s+(?=[A-Z])", text)
    return [s.strip() for s in raw if s.strip()]
