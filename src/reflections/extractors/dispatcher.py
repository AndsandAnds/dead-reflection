"""
Picks the right extractor for an artifact and runs it.

This is intentionally tiny — one mapping table + one dispatch call.
Adding a new extractor is `from . import x` + a line in `_REGISTRY`.
"""

from __future__ import annotations

from typing import Awaitable, Callable

from reflections.extractors import audio, image, pdf, video
from reflections.extractors.base import (
    ArtifactMeta,
    ExtractedChunk,
    UnsupportedArtifactError,
)

_REGISTRY = {
    "pdf": pdf.extract,
    "image": image.extract,
    "audio": audio.extract,
    "video": video.extract,
}


async def dispatch(
    *,
    meta: ArtifactMeta,
    read_bytes: Callable[[], Awaitable[bytes]],
) -> list[ExtractedChunk]:
    fn = _REGISTRY.get(meta.kind)
    if fn is None:
        raise UnsupportedArtifactError(
            f"no_extractor_for_kind: {meta.kind}"
        )
    return await fn(read_bytes, meta)


def supported_kinds() -> list[str]:
    return sorted(_REGISTRY.keys())
