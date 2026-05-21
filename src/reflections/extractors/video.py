"""
Video extractor — strips audio with ffmpeg, then runs the audio extractor.

Visual keyframe captioning is v2 (would need ffmpeg keyframe extraction +
the image extractor per frame; meaningful only for shorter videos).
"""

from __future__ import annotations

import asyncio
import os
import tempfile
from typing import Awaitable, Callable

from reflections.extractors import audio as audio_extractor
from reflections.extractors.base import (
    ArtifactMeta,
    ExtractedChunk,
    ExtractionError,
)


async def extract(
    read_bytes: Callable[[], Awaitable[bytes]],
    meta: ArtifactMeta,
) -> list[ExtractedChunk]:
    blob = await read_bytes()
    if not blob:
        raise ExtractionError("empty_video")

    with tempfile.TemporaryDirectory(prefix="reflections-vid-") as td:
        in_path = os.path.join(td, "input.bin")
        out_path = os.path.join(td, "audio.wav")
        with open(in_path, "wb") as f:
            f.write(blob)

        # 16kHz mono PCM16 — matches what whisper.cpp wants and keeps the
        # transferred bytes small.
        cmd = [
            "ffmpeg",
            "-loglevel", "error",
            "-y",
            "-i", in_path,
            "-vn",
            "-ac", "1",
            "-ar", "16000",
            "-c:a", "pcm_s16le",
            out_path,
        ]
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        _stdout, stderr = await proc.communicate()
        if proc.returncode != 0:
            err = (stderr or b"").decode("utf-8", errors="replace")[:300]
            raise ExtractionError(f"ffmpeg_failed: rc={proc.returncode}: {err}")

        with open(out_path, "rb") as f:
            audio_bytes = f.read()

    # Reuse the audio path: same STT bridge, same chunking, same locators.
    async def _read_audio() -> bytes:
        return audio_bytes

    # Re-use the audio extractor's full pipeline.
    audio_meta = ArtifactMeta(
        id=meta.id,
        user_id=meta.user_id,
        mount_path=meta.mount_path,
        relative_path=meta.relative_path,
        # The transcript came from extracted audio; stamp as such so the
        # caller's "source_kind" metadata stays accurate.
        mime="audio/wav",
        size_bytes=len(audio_bytes),
        kind="audio",
    )
    chunks = await audio_extractor.extract(_read_audio, audio_meta)
    # Re-stamp so downstream knows the original was video.
    return [
        ExtractedChunk(
            content=c.content,
            locator={**c.locator, "from": "video"},
            metadata={**c.metadata, "source_kind": "video"},
        )
        for c in chunks
    ]
