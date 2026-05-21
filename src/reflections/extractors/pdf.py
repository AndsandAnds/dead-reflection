"""PDF text extractor — one chunk per page."""

from __future__ import annotations

import io
from typing import Awaitable, Callable

from reflections.extractors.base import (
    ArtifactMeta,
    ExtractedChunk,
    ExtractionError,
)


async def extract(
    read_bytes: Callable[[], Awaitable[bytes]],
    meta: ArtifactMeta,
    *,
    max_pages: int = 5000,
) -> list[ExtractedChunk]:
    """Read the PDF bytes, parse with pypdf, emit one chunk per page.

    Empty pages (no text or text-extraction fails for that page) are
    skipped — they'd just pollute search with nothing.
    """
    try:
        from pypdf import PdfReader  # type: ignore[import-not-found]
    except ImportError as exc:  # pragma: no cover
        raise ExtractionError("pypdf_not_installed") from exc

    blob = await read_bytes()
    if not blob:
        raise ExtractionError("empty_pdf")

    try:
        reader = PdfReader(io.BytesIO(blob))
    except Exception as exc:
        raise ExtractionError(f"pdf_parse_failed: {exc}") from exc

    out: list[ExtractedChunk] = []
    total_pages = min(len(reader.pages), max_pages)
    for idx in range(total_pages):
        try:
            page = reader.pages[idx]
            text = (page.extract_text() or "").strip()
        except Exception:
            # One bad page shouldn't kill the whole document.
            continue
        if not text:
            continue
        out.append(
            ExtractedChunk(
                content=text,
                locator={"page": idx + 1, "total_pages": len(reader.pages)},
                metadata={
                    "source_kind": "pdf",
                    "filename": meta.relative_path.rsplit("/", 1)[-1],
                },
            )
        )
    return out
