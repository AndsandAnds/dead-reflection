from __future__ import annotations

import datetime as dt
from uuid import UUID

import pytest  # type: ignore[import-not-found]
from fastapi.testclient import TestClient  # type: ignore[import-not-found]

from reflections.api.main import build_app


@pytest.fixture()
def client():
    app = build_app()
    from reflections.commons.depends import database_session

    async def _dummy_db_session():  # type: ignore[no-untyped-def]
        class Dummy:
            pass

        yield Dummy()

    app.dependency_overrides[database_session] = _dummy_db_session
    return TestClient(app)


def _override_auth(client: TestClient):
    from reflections.auth.depends import current_user_required
    from reflections.auth.models import User

    user = User(
        id=UUID("00000000-0000-0000-0000-0000000000aa"),
        email="mcp@example.com",
        name="MCP Tester",
        password_hash="x",
        is_admin=False,
        created_at=dt.datetime.now(dt.UTC),
        last_login_at=None,
        disabled_at=None,
    )
    client.app.dependency_overrides[current_user_required] = lambda: user
    return user


def test_mint_token_requires_auth(client: TestClient) -> None:
    r = client.post("/mcp/tokens", json={"name": "x"})
    assert r.status_code == 401


def test_mint_token_returns_raw_once(client: TestClient) -> None:
    user = _override_auth(client)
    from reflections.mcp.api import get_mcp_service
    from reflections.mcp.repository import McpTokenRow

    fake_row = McpTokenRow(
        id=UUID("00000000-0000-0000-0000-0000000000bb"),
        user_id=user.id,
        name="Claude Desktop",
        scopes=["mcp:read", "mcp:write"],
        created_at=dt.datetime.now(dt.UTC),
        last_used_at=None,
        revoked_at=None,
    )

    class FakeService:
        async def mint(self, _session, *, user_id, name, scopes=None):  # type: ignore[no-untyped-def]
            assert user_id == user.id
            return fake_row, "ref_mcp_FAKE"

    client.app.dependency_overrides[get_mcp_service] = lambda: FakeService()

    r = client.post("/mcp/tokens", json={"name": "Claude Desktop"})
    assert r.status_code == 201
    body = r.json()
    assert body["token"] == "ref_mcp_FAKE"
    assert body["name"] == "Claude Desktop"
    assert body["id"] == str(fake_row.id)


def test_revoke_token_404_when_missing(client: TestClient) -> None:
    _override_auth(client)
    from reflections.mcp.api import get_mcp_service
    from reflections.mcp.exceptions import McpTokenNotFoundException

    class FakeService:
        async def revoke(self, *_args, **_kwargs):
            raise McpTokenNotFoundException("not_found", "missing")

    client.app.dependency_overrides[get_mcp_service] = lambda: FakeService()
    r = client.delete("/mcp/tokens/00000000-0000-0000-0000-0000000000cc")
    assert r.status_code == 404


def test_mcp_endpoint_unauth_returns_401(client: TestClient) -> None:
    """The mounted FastMCP app should reject unauthenticated requests."""
    r = client.post(
        "/mcp/",
        headers={"accept": "application/json, text/event-stream"},
        json={
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {
                "protocolVersion": "2025-06-18",
                "capabilities": {},
                "clientInfo": {"name": "tc", "version": "0"},
            },
        },
    )
    assert r.status_code == 401
