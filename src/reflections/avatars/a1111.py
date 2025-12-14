from __future__ import annotations

import base64
from dataclasses import dataclass
from typing import Any

import httpx  # type: ignore[import-not-found]

from reflections.core.settings import settings


class A1111Exception(RuntimeError):
    pass


@dataclass(frozen=True)
class A1111Client:
    base_url: str

    async def txt2img(self, payload: dict[str, Any]) -> str:
        timeout_s = float(settings.A1111_TIMEOUT_S)
        async with httpx.AsyncClient(base_url=self.base_url, timeout=timeout_s) as client:
            resp = await client.post("/sdapi/v1/txt2img", json=payload)
            resp.raise_for_status()
            data = resp.json()
        images = data.get("images") if isinstance(data, dict) else None
        if not images or not isinstance(images, list) or not images[0]:
            raise A1111Exception("a1111_no_images")
        # A1111 returns base64-encoded PNG bytes (no data URL prefix).
        b64 = str(images[0])
        # Validate b64 is decodable (helps catch HTML error pages).
        try:
            base64.b64decode(b64[:64] + "==", validate=False)
        except Exception as exc:
            raise A1111Exception(f"a1111_invalid_image_b64:{exc!s}") from exc
        return f"data:image/png;base64,{b64}"


def get_a1111_client() -> A1111Client:
    if not settings.A1111_BASE_URL:
        raise A1111Exception("A1111_BASE_URL is not configured")
    return A1111Client(base_url=str(settings.A1111_BASE_URL))


