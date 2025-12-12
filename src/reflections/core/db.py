"""
Database manager skeleton (async SQLAlchemy).

We follow the reference project's pattern: a shared manager that owns the engine
and sessionmaker, and a dependency that yields sessions.
"""

from __future__ import annotations

from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from sqlalchemy.ext.asyncio import (  # type: ignore[import-not-found]
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from reflections.commons.exceptions import BaseCoreException
from reflections.commons.logging import logger
from reflections.core.settings import settings


class DatabaseException(BaseCoreException):
    pass


class DatabaseManager:
    def __init__(self) -> None:
        self.engine: AsyncEngine | None = None
        self.sessionmaker: async_sessionmaker[AsyncSession] | None = None

    def _build_dsn(self) -> str:
        # psycopg async driver
        return (
            "postgresql+psycopg://"
            f"{settings.REFLECTIONS_DB_USER}:{settings.REFLECTIONS_DB_PASSWORD}"
            f"@{settings.REFLECTIONS_DB_HOST}:{settings.REFLECTIONS_DB_PORT}"
            f"/{settings.REFLECTIONS_DB_NAME}"
        )

    async def initialize(self) -> None:
        if self.engine is not None:
            return
        try:
            dsn = self._build_dsn()
            self.engine = create_async_engine(dsn, echo=False)
            self.sessionmaker = async_sessionmaker(self.engine, expire_on_commit=False)
            logger.info("Database initialized")
        except Exception as exc:
            raise DatabaseException("Failed to initialize database", str(exc)) from exc

    async def shutdown(self) -> None:
        if self.engine is None:
            return
        await self.engine.dispose()
        self.engine = None
        self.sessionmaker = None
        logger.info("Database shut down")

    @asynccontextmanager
    async def session(self) -> AsyncGenerator[AsyncSession, None]:
        if self.sessionmaker is None:
            raise DatabaseException("Database is not initialized")
        async with self.sessionmaker() as session:
            try:
                yield session
            except Exception:
                await session.rollback()
                raise
            finally:
                await session.close()


database_manager = DatabaseManager()
