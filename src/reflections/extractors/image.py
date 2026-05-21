"""
Image extractor — one caption chunk per image.

Uses qwen3-vl (or any vision model loaded in Ollama) for the caption.
EXIF is read with Pillow + pillow-heif (for iPhone HEIC) and merged
into the chunk metadata.

The caption call goes to local Ollama — it's not internet egress, so
the admin gate doesn't apply.
"""

from __future__ import annotations

import base64
import io
from typing import Any, Awaitable, Callable

import httpx  # type: ignore[import-not-found]

from reflections.core.settings import settings
from reflections.extractors.base import (
    ArtifactMeta,
    ExtractedChunk,
    ExtractionError,
)

# qwen3-vl exists on this user's Ollama; fall back to qwen3-vl:8b when
# the bigger tag isn't loaded. Configurable via env.
def _vision_model() -> str:
    import os

    return os.environ.get("OLLAMA_VISION_MODEL", "qwen3-vl:latest")


_CAPTION_PROMPT = (
    "Describe what's in this image in 1-3 sentences. Be concrete — name "
    "specific people, places, objects, and any visible text. Keep it "
    "factual; no speculation about feelings or context that isn't shown."
)


async def extract(
    read_bytes: Callable[[], Awaitable[bytes]],
    meta: ArtifactMeta,
    *,
    ollama_url: str | None = None,
) -> list[ExtractedChunk]:
    blob = await read_bytes()
    if not blob:
        raise ExtractionError("empty_image")

    exif = _read_exif(blob, meta.mime)
    caption = await _caption(blob, ollama_url=ollama_url or settings.OLLAMA_BASE_URL)
    if not caption:
        # No caption + no EXIF text content = nothing useful to embed.
        # Returning an empty list is fine; the artifact stays catalogued
        # without derived chunks.
        return []

    return [
        ExtractedChunk(
            content=caption,
            locator={"page": 1, "total_pages": 1},
            metadata={
                "source_kind": "image",
                "filename": meta.relative_path.rsplit("/", 1)[-1],
                "exif": exif,
            },
        )
    ]


def _read_exif(blob: bytes, mime: str | None) -> dict[str, Any]:
    """Best-effort EXIF read. Returns {} if Pillow can't open it."""
    try:
        from PIL import Image, ExifTags  # type: ignore[import-not-found]
    except ImportError:  # pragma: no cover
        return {}
    # HEIC/HEIF support is a one-time register from pillow-heif.
    try:
        import pillow_heif  # type: ignore[import-not-found]

        pillow_heif.register_heif_opener()
    except Exception:
        pass
    try:
        img = Image.open(io.BytesIO(blob))
    except Exception:
        return {}

    out: dict[str, Any] = {
        "width": img.width,
        "height": img.height,
        "format": img.format,
    }
    try:
        raw = img._getexif() or {}  # type: ignore[attr-defined]
    except Exception:
        raw = {}
    if raw:
        tagmap = {v: k for k, v in ExifTags.TAGS.items()}
        for human in (
            "DateTimeOriginal",
            "Make",
            "Model",
            "LensModel",
            "Orientation",
            "ExposureTime",
            "FNumber",
            "ISOSpeedRatings",
            "FocalLength",
        ):
            tag = tagmap.get(human)
            if tag is None:
                continue
            val = raw.get(tag)
            if val is None:
                continue
            # IFDRational + tuples aren't JSON-friendly; coerce.
            try:
                out[human] = float(val) if hasattr(val, "__float__") else str(val)
            except Exception:
                out[human] = repr(val)
        # GPS — coarse, just the decimal lat/lng if present
        gps_tag = tagmap.get("GPSInfo")
        if gps_tag is not None and gps_tag in raw:
            try:
                gps = raw[gps_tag]
                lat = _gps_to_decimal(gps.get(2), gps.get(1))
                lng = _gps_to_decimal(gps.get(4), gps.get(3))
                if lat is not None and lng is not None:
                    out["GPS"] = {"lat": lat, "lng": lng}
            except Exception:
                pass
    return out


def _gps_to_decimal(dms, ref) -> float | None:
    if not dms:
        return None
    try:
        deg, mn, sec = [float(x) for x in dms]
    except Exception:
        return None
    val = deg + mn / 60.0 + sec / 3600.0
    if ref in ("S", "W"):
        val = -val
    return round(val, 6)


async def _caption(blob: bytes, *, ollama_url: str) -> str:
    """Send the image to Ollama's vision model and return the caption."""
    b64 = base64.b64encode(blob).decode("ascii")
    payload = {
        "model": _vision_model(),
        "prompt": _CAPTION_PROMPT,
        "images": [b64],
        "stream": False,
        "options": {"temperature": 0.0},
        "keep_alive": "10m",
    }
    timeout = httpx.Timeout(120.0, connect=5.0)
    async with httpx.AsyncClient(base_url=ollama_url, timeout=timeout) as client:
        try:
            r = await client.post("/api/generate", json=payload)
        except Exception as exc:
            raise ExtractionError(f"ollama_unreachable: {exc}") from exc
    if r.status_code >= 400:
        raise ExtractionError(
            f"ollama_caption_failed: http_{r.status_code} {r.text[:200]}"
        )
    data = r.json()
    return str(data.get("response", "")).strip()
