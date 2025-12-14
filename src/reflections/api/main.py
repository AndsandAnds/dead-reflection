from __future__ import annotations

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware  # type: ignore[import-not-found]

from reflections.api.exceptions import configure_global_exception_handlers
from reflections.api.routers import configure_routers
from reflections.core.settings import settings


def build_app() -> FastAPI:
    app = FastAPI(title=settings.API_TITLE, version=settings.API_VERSION)
    origins = [o.strip() for o in str(settings.CORS_ORIGINS).split(",") if o.strip()]
    if origins:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=origins,
            allow_credentials=True,
            allow_methods=["*"],
            allow_headers=["*"],
        )
    configure_routers(app)
    configure_global_exception_handlers(app)
    return app


app = build_app()
