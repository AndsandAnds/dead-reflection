"""
FastMCP server definition.

One module-level `mcp` instance is constructed once on import. The HTTP/SSE
ASGI app is exposed via `mcp_http_app()` and mounted into the FastAPI app in
`reflections.api.main` at the `/mcp` path. The same instance can also be run
via stdio for Claude Desktop installs that prefer the launched-process pattern.
"""

from __future__ import annotations

from fastmcp import FastMCP  # type: ignore[import-not-found]

from reflections.mcp.auth import ReflectionsTokenVerifier
from reflections.mcp.tools import calendar as calendar_tools
from reflections.mcp.tools import entities as entity_tools
from reflections.mcp.tools import memory as memory_tools
from reflections.mcp.tools import vault as vault_tools
from reflections.mcp.tools import web as web_tools


def _build() -> FastMCP:
    server = FastMCP(
        name="Reflections",
        instructions=(
            "Tools for a personal, local memory + knowledge-graph assistant. "
            "Use `record_memory` to save things worth remembering, "
            "`recall_memory` to surface relevant past notes, and the entity "
            "tools to navigate the knowledge graph of people, places, events, "
            "and topics. `export_vault` snapshots everything as markdown for "
            "Obsidian / grep / git. The `*_calendar_event` tools read/write "
            "the user's Apple Calendar via a local bridge (macOS only). The "
            "`internet_search` tool is admin-only and audits every call; all "
            "other data stays on the user's machine."
        ),
        auth=ReflectionsTokenVerifier(),
    )
    memory_tools.register(server)
    entity_tools.register(server)
    web_tools.register(server)
    calendar_tools.register(server)
    vault_tools.register(server)
    return server


mcp = _build()


def mcp_http_app():
    """Return the ASGI app to mount at /mcp in FastAPI.

    `path="/"` so the app handles requests at its mount root; the mount in
    `api/main.py` provides the `/mcp` prefix.
    """
    return mcp.http_app(path="/", transport="http")
