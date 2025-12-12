from fastapi import FastAPI

from reflections.health.api import router as health_router
from reflections.memory.api import router as memory_router
from reflections.voice.api import router as voice_router


def configure_routers(app: FastAPI) -> FastAPI:
    app.include_router(health_router)
    app.include_router(memory_router)
    app.include_router(voice_router)
    return app
