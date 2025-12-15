from __future__ import annotations

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware  # type: ignore[import-not-found]

from reflections.api.exceptions import configure_global_exception_handlers
from reflections.api.routers import configure_routers
from reflections.core.settings import settings


def build_app() -> FastAPI:
    app = FastAPI(title=settings.API_TITLE, version=settings.API_VERSION)
    # CORS: be forgiving about localhost vs 127.0.0.1, since devs commonly use either.
    raw_origins = [o.strip() for o in str(settings.CORS_ORIGINS).split(",") if o.strip()]
    origins: list[str] = []
    for o in raw_origins:
        origins.append(o)
        if o.startswith("http://localhost:"):
            origins.append(o.replace("http://localhost:", "http://127.0.0.1:", 1))
        elif o.startswith("http://127.0.0.1:"):
            origins.append(o.replace("http://127.0.0.1:", "http://localhost:", 1))
    # De-dupe while preserving order.
    seen: set[str] = set()
    origins = [o for o in origins if not (o in seen or seen.add(o))]
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
