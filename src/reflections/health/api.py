from __future__ import annotations

from fastapi import APIRouter

from reflections.health import service
from reflections.health.schemas import HealthResponse

router = APIRouter()


@router.get("/health", response_model=HealthResponse)
async def health() -> HealthResponse:
    return HealthResponse(**(await service.get_health_payload()))
