"""
Extractor contract — every kind-specific extractor (pdf, image, audio,
video) implements a single async function:

    async def extract(
        artifact_kind_data: Any,
        read_bytes: Callable[[], Awaitable[bytes]],
        meta: ArtifactMeta,
    ) -> list[ExtractedChunk]

The caller (extraction service) is responsible for pulling bytes from
the catalog bridge and for writing the resulting chunks to memory_items
with the right (user_id, artifact_id, artifact_locator, private) stamp.

This shape makes the extractors trivially testable — pass an in-memory
read_bytes function returning a fixture, assert on the chunks.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any
from uuid import UUID


@dataclass(frozen=True)
class ArtifactMeta:
    """Minimum identity an extractor needs. Avoids importing ArtifactRow."""

    id: UUID
    user_id: UUID
    mount_path: str
    relative_path: str
    mime: str | None
    size_bytes: int
    kind: str


@dataclass(frozen=True)
class ExtractedChunk:
    """One memory chunk derived from an artifact.

    `locator` is whatever lets a downstream UI render "from <title>(p.7)"
    or "from <title> at 03:42". Free-form JSON-friendly dict; the only
    contract is that it round-trips through Postgres.
    """

    content: str
    locator: dict[str, Any] = field(default_factory=dict)
    # Per-chunk metadata that goes into memory_items.metadata (NOT
    # artifacts.attributes — that's for the artifact as a whole).
    metadata: dict[str, Any] = field(default_factory=dict)


class ExtractionError(Exception):
    """Raised by an extractor when the bytes can't be processed."""

    pass


class UnsupportedArtifactError(ExtractionError):
    """The dispatcher doesn't know how to handle this kind/mime."""

    pass
