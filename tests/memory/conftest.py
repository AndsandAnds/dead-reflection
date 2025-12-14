"""
Memory module pytest fixtures (pattern-aligned).

We avoid a live DB for unit tests by overriding the DB/session dependency and
injecting a fake MemoryService.
"""

import httpx
import pytest  # type: ignore[import-not-found]
from fastapi import FastAPI
from uuid import UUID
from uuid6 import uuid7  # type: ignore[import-not-found]

from reflections.api.main import build_app
from reflections.auth.depends import current_user_required
from reflections.commons.depends import database_session as original_database_session
from reflections.memory import api as memory_api


class FakeMemoryService:
    async def ingest_episodic(
        self, session, *, user_id, avatar_id, turns, chunk_turn_window
    ):
        return ([uuid7(), uuid7()], 1, 1)

    async def search(self, session, *, user_id, avatar_id, query, top_k, **kwargs):
        return []

    async def inspect(self, session, *, user_id, avatar_id, limit, offset, **kwargs):
        return []

    async def delete(self, session, *, user_id, ids):
        return len(ids)


@pytest.fixture(scope="session")
def memory_app() -> FastAPI:
    app = build_app()

    # Stable fake user id for unit tests.
    test_user_id = UUID("00000000-0000-0000-0000-000000000001")

    async def fake_database_session():
        yield None

    class FakeUser:
        id = test_user_id

    app.dependency_overrides[original_database_session] = fake_database_session
    app.dependency_overrides[current_user_required] = lambda: FakeUser()
    app.dependency_overrides[memory_api.get_memory_service] = (
        lambda: FakeMemoryService()
    )
    return app


@pytest.fixture()
async def memory_async_client(memory_app: FastAPI):
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=memory_app),
        base_url="http://test",
    ) as client:
        yield client
