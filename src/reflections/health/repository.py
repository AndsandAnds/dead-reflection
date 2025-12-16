from __future__ import annotations

import os

import httpx  # type: ignore[import-not-found]
import sqlalchemy as sa  # type: ignore[import-not-found]

from reflections.core.db import database_manager
from reflections.core.settings import settings


def get_ollama_base_url() -> str:
    return settings.OLLAMA_BASE_URL


async def check_db() -> tuple[bool, str | None]:
    try:
        await database_manager.initialize()
        async with database_manager.session() as session:
            await session.execute(sa.text("SELECT 1"))
        return True, None
    except Exception as exc:
        return False, str(exc)


async def check_http_ok(
    base_url: str, *, path: str, timeout_s: float, accept_404: bool = False
) -> tuple[bool, str | None]:
    try:
        timeout = httpx.Timeout(timeout_s, connect=min(0.25, timeout_s))
        async with httpx.AsyncClient(base_url=base_url, timeout=timeout) as client:
            resp = await client.get(path)
            # Consider any 2xx/3xx as "reachable".
            if 200 <= int(resp.status_code) < 400:
                return True, None
            # Some local bridges don't implement /health; treat 404 as reachable.
            if accept_404 and int(resp.status_code) == 404:
                return True, None
            return False, f"HTTP {resp.status_code}"
    except Exception as exc:
        return False, str(exc)


async def check_ollama() -> tuple[bool, str | None]:
    # Ollama is host-installed in local dev. In some environments it may not be running;
    # health should still return quickly and indicate ollama.ok=false.
    return await check_http_ok(settings.OLLAMA_BASE_URL, path="/api/tags", timeout_s=0.8)


async def check_stt() -> tuple[bool, str | None]:
    if not settings.STT_BASE_URL:
        return False, "not_configured"
    return await check_http_ok(
        settings.STT_BASE_URL, path="/health", timeout_s=0.8, accept_404=True
    )


async def check_tts() -> tuple[bool, str | None]:
    if not settings.TTS_BASE_URL:
        return False, "not_configured"
    return await check_http_ok(
        settings.TTS_BASE_URL, path="/health", timeout_s=0.8, accept_404=True
    )


async def check_a1111() -> tuple[bool, str | None]:
    if not settings.A1111_BASE_URL:
        return False, "not_configured"
    # Standard Automatic1111 endpoint; returns list of models.
    return await check_http_ok(settings.A1111_BASE_URL, path="/sdapi/v1/sd-models", timeout_s=1.2)


def check_avatar_image_engine() -> tuple[bool, str | None]:
    engine = (settings.AVATAR_IMAGE_ENGINE or "").strip().lower()
    if engine == "a1111":
        if not settings.A1111_BASE_URL:
            return False, "not_configured"
        # Base URL configured; service may optionally ping it.
        return True, None
    if engine == "diffusers_sdxl":
        base = settings.DIFFUSERS_SDXL_BASE_MODEL or ""
        if not base:
            return False, "base_model_not_configured"
        if not os.path.exists(base):
            return False, f"base_model_missing:{base}"
        ref = settings.DIFFUSERS_SDXL_REFINER_MODEL or ""
        if ref and not os.path.exists(ref):
            return False, f"refiner_model_missing:{ref}"
        return True, None
    return False, f"unknown_engine:{engine or 'empty'}"
