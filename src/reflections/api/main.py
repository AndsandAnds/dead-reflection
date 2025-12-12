from __future__ import annotations

from fastapi import FastAPI

from reflections.api.exceptions import configure_global_exception_handlers
from reflections.api.routers import configure_routers
from reflections.core.settings import settings


def build_app() -> FastAPI:
    app = FastAPI(title=settings.API_TITLE, version=settings.API_VERSION)
    configure_routers(app)
    configure_global_exception_handlers(app)
    return app


app = build_app()
