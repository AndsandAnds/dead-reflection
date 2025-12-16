from __future__ import annotations

from pydantic import BaseModel


class HealthCheck(BaseModel):
    ok: bool
    configured: bool = True
    base_url: str | None = None
    detail: str | None = None


class HealthResponse(BaseModel):
    status: str
    ollama_base_url: str
    db: HealthCheck
    ollama: HealthCheck
    stt: HealthCheck
    tts: HealthCheck
    avatar_image: HealthCheck
