"""
Global pytest fixtures.

Keep this file small and additive (pattern-aligned with our other project), and
add heavier fixtures only when we actually introduce DB/cache/background tasks.
"""

import asyncio

import pytest  # type: ignore[import-not-found]
from fastapi import FastAPI
from fastapi.testclient import TestClient

from reflections.api.main import build_app


@pytest.fixture(scope="function")
def event_loop():
    """Function-scoped event loop for async tests."""
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    yield loop
    loop.close()


@pytest.fixture(scope="session")
def app() -> FastAPI:
    """Session-scoped FastAPI app for tests."""
    return build_app()


@pytest.fixture()
def client(app: FastAPI) -> TestClient:
    """Sync test client (covers most HTTP + WebSocket unit tests)."""
    return TestClient(app)


@pytest.fixture(scope="session")
def anyio_backend() -> str:
    """Default AnyIO backend for async tests."""
    return "asyncio"
