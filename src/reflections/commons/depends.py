from __future__ import annotations

from collections.abc import AsyncGenerator

from sqlalchemy.ext.asyncio import AsyncSession  # type: ignore[import-not-found]

from reflections.core.db import database_manager


async def database_session() -> AsyncGenerator[AsyncSession, None]:
    # Ensure DB is initialized before yielding sessions.
    await database_manager.initialize()
    async with database_manager.session() as session:
        yield session
