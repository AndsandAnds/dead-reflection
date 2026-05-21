from fastapi import FastAPI

from reflections.artifacts.api import router as artifacts_router
from reflections.auth.api import router as auth_router
from reflections.avatars.api import router as avatars_router
from reflections.calendar.api import router as calendar_router
from reflections.conversations.api import router as conversations_router
from reflections.entities.api import router as entities_router
from reflections.health.api import router as health_router
from reflections.mcp.api import router as mcp_router
from reflections.memory.api import router as memory_router
from reflections.outbound.api import router as outbound_router
from reflections.vault.api import router as vault_router
from reflections.voice.api import router as voice_router


def configure_routers(app: FastAPI) -> FastAPI:
    app.include_router(artifacts_router)
    app.include_router(auth_router)
    app.include_router(avatars_router)
    app.include_router(calendar_router)
    app.include_router(conversations_router)
    app.include_router(entities_router)
    app.include_router(health_router)
    app.include_router(mcp_router)
    app.include_router(memory_router)
    app.include_router(outbound_router)
    app.include_router(vault_router)
    app.include_router(voice_router)
    return app
