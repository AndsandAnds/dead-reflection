from __future__ import annotations

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware  # type: ignore[import-not-found]

from reflections.api.exceptions import configure_global_exception_handlers
from reflections.api.routers import configure_routers
from reflections.core.settings import settings
from reflections.mcp.server import mcp_http_app


def build_app() -> FastAPI:
    # The MCP sub-app owns its own session/task-group lifespan; FastAPI must
    # adopt it so the MCP machinery starts/stops with the parent app.
    mcp_app = mcp_http_app()

    app = FastAPI(
        title=settings.API_TITLE,
        version=settings.API_VERSION,
        lifespan=mcp_app.router.lifespan_context,
    )
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
            # Narrowed from "*" — the browser UI only issues these verbs and
            # only sends Content-Type as a non-simple header (auth rides on
            # cookies). If a new endpoint needs a different method/header,
            # add it here explicitly.
            allow_methods=["GET", "POST", "PATCH", "DELETE", "OPTIONS"],
            allow_headers=["Content-Type"],
        )
    configure_routers(app)
    configure_global_exception_handlers(app)
    # Mount the FastMCP HTTP transport. Tools share the same Python process,
    # DB engine, and settings as the rest of the app.
    app.mount("/mcp", mcp_app)
    return app


app = build_app()
